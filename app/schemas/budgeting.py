"""Pydantic schemas for the budgeting feature (Phase 1, Task 1B).

Three resources: pay_sources, sinking_funds, goals. Plus a response model
for the per-paycheck plan.
"""
from datetime import date as date_type, datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


Cadence = Literal["weekly", "biweekly", "semimonthly", "monthly"]
_PERIODS_BY_CADENCE: dict[str, int] = {
    "weekly": 52,
    "biweekly": 26,
    "semimonthly": 24,
    "monthly": 12,
}


# ---------------------------------------------------------------------------
# PaySource
# ---------------------------------------------------------------------------

class PaySourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    cadence: Cadence
    periods_per_year: Optional[int] = Field(default=None, ge=1, le=366)
    net_per_check: Optional[Decimal] = None

    @model_validator(mode="after")
    def _periods_match_cadence(self):
        expected = _PERIODS_BY_CADENCE[self.cadence]
        if self.periods_per_year is None:
            self.periods_per_year = expected
        elif self.periods_per_year != expected:
            raise ValueError(
                f"periods_per_year {self.periods_per_year} does not match "
                f"cadence {self.cadence!r} (expected {expected})"
            )
        return self


class PaySourceUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    cadence: Optional[Cadence] = None
    periods_per_year: Optional[int] = None
    net_per_check: Optional[Decimal] = None

    @model_validator(mode="after")
    def _check_periods(self):
        if self.cadence is not None:
            expected = _PERIODS_BY_CADENCE[self.cadence]
            if self.periods_per_year is None:
                self.periods_per_year = expected
            elif self.periods_per_year != expected:
                raise ValueError(
                    f"periods_per_year {self.periods_per_year} does not match "
                    f"cadence {self.cadence!r} (expected {expected})"
                )
        return self


class PaySourceResponse(BaseModel):
    id: int
    name: str
    cadence: str
    periods_per_year: int
    net_per_check: Optional[Decimal]
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("cadence", mode="before")
    @classmethod
    def _cadence_to_str(cls, v):
        # Column is String(20) now, but kept for forward-compat if a caller
        # ever passes a PayCadence enum directly.
        return v.value if hasattr(v, "value") else v


# ---------------------------------------------------------------------------
# SinkingFund
# ---------------------------------------------------------------------------

BillPeriods = Literal[1, 2, 4, 12]


class SinkingFundCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    amount: Decimal = Field(gt=0)
    bill_periods_per_year: BillPeriods
    next_due: Optional[date_type] = None
    current_balance: Decimal = Field(default=Decimal("0"), ge=0)
    linked_account_id: Optional[int] = None
    funding_source_id: Optional[int] = None
    currency: str = Field(default="USD", min_length=3, max_length=3)


class SinkingFundUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    amount: Optional[Decimal] = Field(default=None, gt=0)
    bill_periods_per_year: Optional[BillPeriods] = None
    next_due: Optional[date_type] = None
    current_balance: Optional[Decimal] = Field(default=None, ge=0)
    linked_account_id: Optional[int] = None
    funding_source_id: Optional[int] = None
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)


class SinkingFundResponse(BaseModel):
    id: int
    name: str
    amount: Decimal
    bill_periods_per_year: int
    next_due: Optional[date_type]
    current_balance: Decimal
    linked_account_id: Optional[int]
    funding_source_id: Optional[int]
    currency: str
    # Derived (computed by the route, not stored):
    monthly_accrual: Decimal
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Goal
# ---------------------------------------------------------------------------

class GoalCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_amount: Decimal = Field(gt=0)
    target_date: date_type
    current_saved: Decimal = Field(default=Decimal("0"), ge=0)
    linked_account_id: Optional[int] = None
    funding_source_id: Optional[int] = None
    currency: str = Field(default="USD", min_length=3, max_length=3)


class GoalUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    target_amount: Optional[Decimal] = Field(default=None, gt=0)
    target_date: Optional[date_type] = None
    current_saved: Optional[Decimal] = Field(default=None, ge=0)
    linked_account_id: Optional[int] = None
    funding_source_id: Optional[int] = None
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)


class GoalResponse(BaseModel):
    id: int
    name: str
    target_amount: Decimal
    target_date: date_type
    current_saved: Decimal
    linked_account_id: Optional[int]
    funding_source_id: Optional[int]
    currency: str
    # Derived:
    monthly_required: Decimal
    months_until: int
    progress_pct: float           # 0..100 (or > 100 if overfunded)
    on_track: bool                # current_saved >= expected by today's date
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Per-Paycheck Plan (read-only aggregation)
# ---------------------------------------------------------------------------

class PerCheckLineResponse(BaseModel):
    kind: Literal["sinking_fund", "goal"]
    id: int
    name: str
    monthly: Decimal
    per_check: Decimal


class PerCheckPlanResponse(BaseModel):
    pay_source_id: int
    pay_source_name: str
    cadence: str
    periods_per_year: int
    monthly_total: Decimal
    per_check_total: Decimal
    items: list[PerCheckLineResponse]
