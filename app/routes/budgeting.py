"""Budgeting API — pay sources, sinking funds, goals, per-paycheck plan.

Phase 1, Task 1B. Three CRUD resources plus a read-only aggregation endpoint
that the dashboard widget consumes. All math goes through
app.services.budget_calc — this module is pure plumbing.
"""
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.budgeting import Goal, PaySource, SinkingFund
from app.schemas.budgeting import (
    GoalCreate, GoalResponse, GoalUpdate,
    PaySourceCreate, PaySourceResponse, PaySourceUpdate,
    PerCheckLineResponse, PerCheckPlanResponse,
    SinkingFundCreate, SinkingFundResponse, SinkingFundUpdate,
)
from app.services.budget_calc import (
    _monthly_required_exact,
    build_per_paycheck_plan,
    monthly_accrual,
    monthly_required,
    months_until,
)


# ---------------------------------------------------------------------------
# /api/pay-sources
# ---------------------------------------------------------------------------

pay_sources_router = APIRouter(prefix="/api/pay-sources", tags=["budgeting"])


@pay_sources_router.get("", response_model=list[PaySourceResponse])
def list_pay_sources(db: Session = Depends(get_db)):
    return db.query(PaySource).order_by(PaySource.name).all()


@pay_sources_router.post("", response_model=PaySourceResponse, status_code=201)
def create_pay_source(data: PaySourceCreate, db: Session = Depends(get_db)):
    row = PaySource(
        name=data.name,
        cadence=data.cadence,
        periods_per_year=data.periods_per_year,
        net_per_check=data.net_per_check,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@pay_sources_router.patch("/{pay_source_id}", response_model=PaySourceResponse)
def update_pay_source(pay_source_id: int, data: PaySourceUpdate,
                     db: Session = Depends(get_db)):
    row = db.query(PaySource).filter(PaySource.id == pay_source_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Pay source not found")
    payload = data.model_dump(exclude_unset=True)
    for k, v in payload.items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@pay_sources_router.delete("/{pay_source_id}")
def delete_pay_source(pay_source_id: int, db: Session = Depends(get_db)):
    row = db.query(PaySource).filter(PaySource.id == pay_source_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Pay source not found")
    # ON DELETE SET NULL on FKs from sinking_funds / goals — pre-existing
    # routing just goes back to "unassigned." Safe.
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# /api/sinking-funds
# ---------------------------------------------------------------------------

sinking_funds_router = APIRouter(prefix="/api/sinking-funds", tags=["budgeting"])


def _fund_to_response(fund: SinkingFund) -> SinkingFundResponse:
    """Serialize a fund including its derived `monthly_accrual`."""
    return SinkingFundResponse(
        id=fund.id,
        name=fund.name,
        amount=fund.amount,
        bill_periods_per_year=fund.bill_periods_per_year,
        next_due=fund.next_due,
        current_balance=fund.current_balance,
        linked_account_id=fund.linked_account_id,
        funding_source_id=fund.funding_source_id,
        currency=fund.currency,
        monthly_accrual=monthly_accrual(fund),
        created_at=fund.created_at,
        updated_at=fund.updated_at,
    )


@sinking_funds_router.get("", response_model=list[SinkingFundResponse])
def list_sinking_funds(db: Session = Depends(get_db)):
    rows = db.query(SinkingFund).order_by(SinkingFund.name).all()
    return [_fund_to_response(r) for r in rows]


@sinking_funds_router.post("", response_model=SinkingFundResponse, status_code=201)
def create_sinking_fund(data: SinkingFundCreate, db: Session = Depends(get_db)):
    row = SinkingFund(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _fund_to_response(row)


@sinking_funds_router.patch("/{fund_id}", response_model=SinkingFundResponse)
def update_sinking_fund(fund_id: int, data: SinkingFundUpdate,
                       db: Session = Depends(get_db)):
    row = db.query(SinkingFund).filter(SinkingFund.id == fund_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Sinking fund not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _fund_to_response(row)


@sinking_funds_router.delete("/{fund_id}")
def delete_sinking_fund(fund_id: int, db: Session = Depends(get_db)):
    row = db.query(SinkingFund).filter(SinkingFund.id == fund_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Sinking fund not found")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# /api/goals
# ---------------------------------------------------------------------------

goals_router = APIRouter(prefix="/api/goals", tags=["budgeting"])


def _goal_to_response(goal: Goal) -> GoalResponse:
    """Serialize a goal with derived progress + on-track fields.

    on_track compares `current_saved` to the linear glide-path expectation
    from goal creation → target_date. The displayed `months_until` uses the
    clamped helper for UX (a target due tomorrow reads "1 month," not 0),
    but the glide-path math uses NAIVE year/month subtraction on both ends
    so a freshly-created goal computes elapsed=0 cleanly instead of being
    knocked one month forward by the clamp.
    """
    from datetime import date as date_type

    mu_display = months_until(goal.target_date)
    target = Decimal(goal.target_amount)
    saved = Decimal(goal.current_saved)
    progress = float(saved / target * 100) if target > 0 else 0.0

    today = date_type.today()
    created_d = goal.created_at.date() if goal.created_at else today
    total_months_naive = (goal.target_date.year - created_d.year) * 12 + (
        goal.target_date.month - created_d.month
    )
    mu_naive = (goal.target_date.year - today.year) * 12 + (
        goal.target_date.month - today.month
    )

    if total_months_naive <= 0:
        on_track = saved >= target
    else:
        elapsed = max(0, total_months_naive - mu_naive)
        expected = target * Decimal(elapsed) / Decimal(total_months_naive)
        on_track = saved >= expected

    return GoalResponse(
        id=goal.id,
        name=goal.name,
        target_amount=goal.target_amount,
        target_date=goal.target_date,
        current_saved=goal.current_saved,
        linked_account_id=goal.linked_account_id,
        funding_source_id=goal.funding_source_id,
        currency=goal.currency,
        monthly_required=monthly_required(goal),
        months_until=mu_display,
        progress_pct=progress,
        on_track=on_track,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


@goals_router.get("", response_model=list[GoalResponse])
def list_goals(db: Session = Depends(get_db)):
    rows = db.query(Goal).order_by(Goal.target_date).all()
    return [_goal_to_response(r) for r in rows]


@goals_router.post("", response_model=GoalResponse, status_code=201)
def create_goal(data: GoalCreate, db: Session = Depends(get_db)):
    row = Goal(**data.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _goal_to_response(row)


@goals_router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(goal_id: int, data: GoalUpdate, db: Session = Depends(get_db)):
    row = db.query(Goal).filter(Goal.id == goal_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return _goal_to_response(row)


@goals_router.delete("/{goal_id}")
def delete_goal(goal_id: int, db: Session = Depends(get_db)):
    row = db.query(Goal).filter(Goal.id == goal_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Goal not found")
    db.delete(row)
    db.commit()


# ---------------------------------------------------------------------------
# /api/budget/per-paycheck-plan — aggregation widget feed
# ---------------------------------------------------------------------------

plan_router = APIRouter(prefix="/api/budget", tags=["budgeting"])


@plan_router.get("/per-paycheck-plan", response_model=list[PerCheckPlanResponse])
def per_paycheck_plan(db: Session = Depends(get_db)):
    """Per pay_source: monthly total + per-check total + the item breakdown.

    Items without a `funding_source_id` are excluded from the plan
    (unassigned).
    """
    sources = db.query(PaySource).all()
    funds = db.query(SinkingFund).all()
    goals = db.query(Goal).all()
    plans = build_per_paycheck_plan(sources, funds, goals)
    return [
        PerCheckPlanResponse(
            pay_source_id=p.pay_source_id,
            pay_source_name=p.pay_source_name,
            cadence=p.cadence,
            periods_per_year=p.periods_per_year,
            monthly_total=p.monthly_total,
            per_check_total=p.per_check_total,
            items=[
                PerCheckLineResponse(
                    kind=it.kind, id=it.id, name=it.name,
                    monthly=it.monthly, per_check=it.per_check,
                )
                for it in p.items
            ],
        )
        for p in plans
    ]
