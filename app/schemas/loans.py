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
