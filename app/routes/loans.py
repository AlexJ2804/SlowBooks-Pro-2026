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
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.accounts import Account, AccountType
from app.models.balance_snapshots import BalanceSnapshot
from app.models.loans import Loan, LoanAmortizationSchedule
from app.schemas.loans import (
    LoanResponse, LoanUpdate, AmortizationGenerateResponse,
    ForwardProjectRequest, ForwardProjectResponse, HomeEquityResponse,
)
from app.services.amortization import (
    add_months as _add_months,
    compute_amortization as _compute_amortization,
    project_forward,
)

router = APIRouter(prefix="/api/loans", tags=["loans"])


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


# ===========================================================================
# Forward projection (Phase 1, Task 1C)
# ===========================================================================

@router.post("/{loan_id}/project-forward", response_model=ForwardProjectResponse)
def project_forward_from_current(
    loan_id: int,
    data: ForwardProjectRequest,
    db: Session = Depends(get_db),
):
    """Build the schedule from the loan's current state, no origination
    data required.

    Inputs come from the request (the borrower's most recent statement):
        current_principal     today's principal owed
        next_payment_date     date of payment #1 in the projected schedule
        monthly_payment       full P&I (and escrow if escrow_amount > 0)
        interest_rate_pct     annual % (e.g. 6.99)
        escrow_amount         escrow portion of monthly_payment (default 0)
        remaining_months      optional — if omitted, derived from the
                              standard amortization formula

    The result is written to `loan_amortization_schedule` (replacing any
    existing rows for this loan), and a summary is returned. Use this when
    you know where the loan stands today but not where it began — the
    common case for a loan that pre-dates the system or whose origination
    data isn't to hand.
    """
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")

    try:
        rows = project_forward(
            current_principal=data.current_principal,
            interest_rate_pct=data.interest_rate_pct,
            monthly_payment=data.monthly_payment,
            escrow_amount=data.escrow_amount or Decimal("0"),
            next_payment_date=data.next_payment_date,
            remaining_months=data.remaining_months,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # Replace schedule rows atomically.
    db.query(LoanAmortizationSchedule).filter(
        LoanAmortizationSchedule.loan_id == loan_id
    ).delete(synchronize_session=False)
    for r in rows:
        db.add(LoanAmortizationSchedule(loan_id=loan_id, **r))
    db.commit()

    return ForwardProjectResponse(
        loan_id=loan_id,
        rows_generated=len(rows),
        first_payment_date=rows[0]["payment_date"],
        last_payment_date=rows[-1]["payment_date"],
        final_remaining_balance=rows[-1]["remaining_balance"],
    )


# ===========================================================================
# Home equity rollup (Phase 1, Task 1C)
# ===========================================================================

@router.get("/{loan_id}/home-equity", response_model=HomeEquityResponse)
def home_equity(loan_id: int, db: Session = Depends(get_db)):
    """Equity = current property value − current mortgage balance.

    `loan.asset_account_id` points at the property asset account; this
    endpoint reads the latest balance_snapshot for both the asset and the
    liability (the loan's account_id) and returns the signed delta.

    If a snapshot is missing on either side we fall back to:
        * for the mortgage: the loan's most recent schedule row
          (`remaining_balance`), or — if no schedule has been projected
          yet — the bare `Loan.original_amount` (an over-estimate, but
          a stable one).
        * for the property: null. The UI should treat null property_value
          as "enter via Balance Entry" and skip the equity line until
          there's a real value to subtract from.
    """
    loan = db.query(Loan).filter(Loan.id == loan_id).first()
    if loan is None:
        raise HTTPException(status_code=404, detail="Loan not found")
    if loan.asset_account_id is None:
        raise HTTPException(
            status_code=422,
            detail="Loan has no asset_account_id — link a property asset first",
        )

    asset = db.query(Account).filter(Account.id == loan.asset_account_id).first()

    property_snap = (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.account_id == loan.asset_account_id)
        .order_by(BalanceSnapshot.as_of_date.desc())
        .first()
    )
    mortgage_snap = (
        db.query(BalanceSnapshot)
        .filter(BalanceSnapshot.account_id == loan.account_id)
        .order_by(BalanceSnapshot.as_of_date.desc())
        .first()
    )

    property_value = property_snap.balance if property_snap else None
    property_as_of = property_snap.as_of_date if property_snap else None

    if mortgage_snap is not None:
        mortgage_balance = mortgage_snap.balance
        mortgage_as_of = mortgage_snap.as_of_date
        mortgage_source = "snapshot"
    else:
        # Fallback to the schedule's most recent row (the next payment about
        # to be made), then to original_amount as a last resort.
        last_row = (
            db.query(LoanAmortizationSchedule)
            .filter(LoanAmortizationSchedule.loan_id == loan_id)
            .order_by(LoanAmortizationSchedule.payment_number.desc())
            .first()
        )
        if last_row is not None:
            mortgage_balance = last_row.remaining_balance
            mortgage_as_of = last_row.payment_date
            mortgage_source = "schedule"
        else:
            mortgage_balance = loan.original_amount
            mortgage_as_of = loan.start_date
            mortgage_source = "loan.original_amount"

    equity = (
        property_value - mortgage_balance
        if property_value is not None else None
    )

    return HomeEquityResponse(
        loan_id=loan_id,
        currency=loan.currency,
        property_account_id=loan.asset_account_id,
        property_account_name=asset.name if asset else None,
        property_value=property_value,
        property_as_of=property_as_of,
        mortgage_account_id=loan.account_id,
        mortgage_balance=mortgage_balance,
        mortgage_as_of=mortgage_as_of,
        mortgage_source=mortgage_source,
        equity=equity,
    )
