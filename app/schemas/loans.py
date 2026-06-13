from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class LoanResponse(BaseModel):
    id: int
    account_id: int
    asset_account_id: Optional[int]
    original_amount: Decimal
    interest_rate: Decimal
    term_months: int
    start_date: date
    monthly_payment: Decimal
    escrow_amount: Decimal
    currency: str
    created_at: datetime
    updated_at: datetime
    # Convenience fields populated by the route handler so the UI
    # doesn't have to do a second lookup.
    account_name: Optional[str] = None
    asset_account_name: Optional[str] = None
    schedule_row_count: int = 0

    model_config = {"from_attributes": True}


class LoanUpdate(BaseModel):
    """Editable loan fields. Account_id and asset_account_id are NOT in
    this set — those are set at seed time and don't change. If you need
    to point a loan at a different asset, do it in the DB."""
    original_amount: Optional[Decimal] = Field(default=None, ge=0)
    interest_rate: Optional[Decimal] = Field(default=None, ge=0, le=100)
    term_months: Optional[int] = Field(default=None, gt=0, le=600)
    start_date: Optional[date] = None
    monthly_payment: Optional[Decimal] = Field(default=None, ge=0)
    escrow_amount: Optional[Decimal] = Field(default=None, ge=0)
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)


class AmortizationRow(BaseModel):
    payment_number: int
    payment_date: date
    principal_amount: Decimal
    interest_amount: Decimal
    escrow_amount: Decimal
    remaining_balance: Decimal


class AmortizationGenerateResponse(BaseModel):
    loan_id: int
    rows_generated: int
    final_remaining_balance: Decimal


# ---------------------------------------------------------------------------
# Forward projection (Phase 1, Task 1C)
# ---------------------------------------------------------------------------

class ForwardProjectRequest(BaseModel):
    """Inputs to project a loan's amortization from its current state.

    Origination data (original_amount, term_months, start_date) is NOT
    required — the engine walks forward from `current_principal` over
    `remaining_months` (or solves for it) using the same fixed-payment
    math as the from-origination engine.
    """
    current_principal: Decimal = Field(gt=0)
    interest_rate_pct: Decimal = Field(ge=0, le=100)
    monthly_payment: Decimal = Field(gt=0)
    escrow_amount: Optional[Decimal] = Field(default=Decimal("0"), ge=0)
    next_payment_date: date
    # If omitted, the engine solves for remaining_months from the standard
    # amortization formula. Pass it explicitly only when you have a known
    # term you'd rather pin (e.g. matching an Irish mortgage's stated term).
    remaining_months: Optional[int] = Field(default=None, gt=0, le=600)


class ForwardProjectResponse(BaseModel):
    loan_id: int
    rows_generated: int
    first_payment_date: date
    last_payment_date: date
    final_remaining_balance: Decimal


# ---------------------------------------------------------------------------
# Home equity rollup (Phase 1, Task 1C)
# ---------------------------------------------------------------------------

class HomeEquityResponse(BaseModel):
    """`property_value − mortgage_balance`, with provenance fields so the
    UI can show e.g. 'value as of 2026-05-01; mortgage as of 2026-06-01'.

    Partial-data shape (200, not error):
      * no linked property asset on the loan → `property_account_id`,
        `property_value`, `equity` all null. Mortgage side still resolves.
      * linked asset present but no snapshot yet → `property_value`,
        `equity` null; `property_account_id` + `property_account_name`
        populated so the UI can deep-link to /#/balances for that account.

    `mortgage_source` is one of:
        snapshot              — most-recent balance_snapshots row
        schedule              — most-recent loan_amortization_schedule row
        loan.original_amount  — fallback when neither exists
    """
    loan_id: int
    currency: str
    property_account_id: Optional[int]
    property_account_name: Optional[str]
    property_value: Optional[Decimal]
    property_as_of: Optional[date]
    mortgage_account_id: int
    mortgage_balance: Decimal
    mortgage_as_of: Optional[date]
    mortgage_source: str
    equity: Optional[Decimal]
