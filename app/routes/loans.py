"""Loan management — net worth phase 1.

Editing loan parameters (rate, term, monthly payment, escrow) and
generating the amortization schedule on demand. The schedule is left
empty by the seed because phase-1 spec is to populate it only after
the user enters real (non-placeholder) values via the UI.

There's no POST endpoint for creating loans here: loan rows are
created at seed time alongside their kind='loan' account. If the user
ever needs to add a new loan account, the seed pattern is extended
rather than a UI loan-creation flow.
"""

from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.loans import Loan, LoanAmortizationSchedule
from app.schemas.loans import (
    LoanResponse, LoanUpdate, AmortizationGenerateResponse,
)

router = APIRouter(prefix="/api/loans", tags=["loans"])


_CENTS = Decimal("0.01")


def _to_response(loan: Loan, schedule_row_count: int) -> LoanResponse:
    resp = LoanResponse.model_validate(loan)
    resp.account_name = loan.account.name if loan.account else None
    resp.asset_account_name = loan.asset_account.name if loan.asset_account else None
    resp.schedule_row_count = schedule_row_count
    return resp


def _count_schedule_rows(db: Session, loan_id: int) -> int:
    return (
        db.query(LoanAmortizationSchedule)
        .filter(LoanAmortizationSchedule.loan_id == loan_id)
        .count()
    )


@router.get("/by-account/{account_id}", response_model=LoanResponse)
def get_loan_by_account(account_id: int, db: Session = Depends(get_db)):
    """Resolve a loan via its liability account. The UI's account-edit
    modal uses this to fetch loan params for the loan-section it shows
    when account_kind='loan'."""
    loan = db.query(Loan).filter(Loan.account_id == account_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="No loan tied to this account")
    return _to_response(loan, _count_schedule_rows(db, loan.id))


@router.get("/{loan_id}", response_model=LoanResponse)
def get_loan(loan_id: int, db: Session = Depends(get_db)):
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    return _to_response(loan, _count_schedule_rows(db, loan_id))


@router.put("/{loan_id}", response_model=LoanResponse)
def update_loan(loan_id: int, data: LoanUpdate, db: Session = Depends(get_db)):
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(loan, key, val)
    db.commit()
    db.refresh(loan)
    return _to_response(loan, _count_schedule_rows(db, loan_id))


@router.post("/{loan_id}/generate-schedule", response_model=AmortizationGenerateResponse)
def generate_schedule(loan_id: int, db: Session = Depends(get_db)):
    """Wipe and regenerate the amortization schedule for this loan.

    Phase-1 spec is that this fires once the user has saved real values
    over the placeholders. Idempotent — replaces any existing schedule
    rows (cascade delete via `cascade='all, delete-orphan'` on the
    relationship is the cleaner mechanism).
    """
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")

    rows = _compute_amortization(
        original_amount=Decimal(loan.original_amount),
        interest_rate_pct=Decimal(loan.interest_rate),
        term_months=int(loan.term_months),
        start_date=loan.start_date,
        monthly_payment=Decimal(loan.monthly_payment),
        escrow_amount=Decimal(loan.escrow_amount or 0),
    )

    # Replace existing rows in one transaction.
    db.query(LoanAmortizationSchedule).filter(
        LoanAmortizationSchedule.loan_id == loan_id
    ).delete(synchronize_session=False)
    for r in rows:
        db.add(LoanAmortizationSchedule(loan_id=loan_id, **r))
    db.commit()

    final_balance = rows[-1]["remaining_balance"] if rows else Decimal("0")
    return AmortizationGenerateResponse(
        loan_id=loan_id,
        rows_generated=len(rows),
        final_remaining_balance=final_balance,
    )


def _compute_amortization(
    *,
    original_amount: Decimal,
    interest_rate_pct: Decimal,
    term_months: int,
    start_date: date,
    monthly_payment: Decimal,
    escrow_amount: Decimal,
) -> list:
    """Standard fixed-rate amortization split into principal/interest each
    period. Uses the user's stored `monthly_payment` as the authoritative
    total payment; principal is `monthly_payment - escrow_amount - interest`.

    Notes:
    - `interest_rate_pct` is the annual percentage rate as a Decimal
      (e.g. 6.5 means 6.5% APR). Monthly rate = APR / 100 / 12.
    - 0% APR is handled (interest = 0 every period).
    - If the user enters values where `monthly_payment - escrow_amount`
      is less than the period's interest, principal goes negative.
      Rather than silently clamping, we let it through so the UI can
      surface the bad inputs visibly. The user is expected to correct
      placeholder values before clicking Generate.
    - Final period's principal is adjusted so `remaining_balance` lands
      at exactly 0 — avoids a stray fractional cent left from the
      monthly_payment rounding.
    """
    monthly_rate = (interest_rate_pct / Decimal(100) / Decimal(12)) if interest_rate_pct > 0 else Decimal(0)
    rows = []
    remaining = original_amount

    for n in range(1, term_months + 1):
        interest = (remaining * monthly_rate).quantize(_CENTS, rounding=ROUND_HALF_UP)
        principal = (monthly_payment - escrow_amount - interest).quantize(_CENTS, rounding=ROUND_HALF_UP)

        # Final period: nudge principal so remaining ends at exactly zero,
        # absorbing any sub-cent drift from rounding.
        if n == term_months:
            principal = remaining

        new_remaining = (remaining - principal).quantize(_CENTS, rounding=ROUND_HALF_UP)
        rows.append({
            "payment_number": n,
            "payment_date": _add_months(start_date, n - 1),
            "principal_amount": principal,
            "interest_amount": interest,
            "escrow_amount": escrow_amount,
            "remaining_balance": new_remaining,
        })
        remaining = new_remaining

    return rows


def _add_months(d: date, months: int) -> date:
    """Add `months` to a date, clamping the day to the new month's last
    valid day if the original was e.g. the 31st in a 30-day month."""
    if months == 0:
        return d
    new_year = d.year + (d.month - 1 + months) // 12
    new_month = (d.month - 1 + months) % 12 + 1
    # Clamp day to last valid day of the new month.
    import calendar
    last_day = calendar.monthrange(new_year, new_month)[1]
    return date(new_year, new_month, min(d.day, last_day))
