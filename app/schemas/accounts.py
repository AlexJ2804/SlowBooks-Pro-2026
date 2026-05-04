from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, model_validator

from app.models.accounts import AccountType


# Net worth phase 1 — accepted account_kind values, mirrored from the
# DB CHECK constraint in alembic h0e1f2a3b4c5. Kept here so the API
# layer can reject bad input before it hits the DB and produces a
# generic constraint-violation 500.
_VALID_ACCOUNT_KINDS = {"bank", "credit_card", "brokerage", "retirement", "property", "loan"}
_VALID_UPDATE_STRATEGIES = {"transactional", "balance_only"}


class AccountCreate(BaseModel):
    name: str
    account_number: Optional[str] = None
    account_type: AccountType
    parent_id: Optional[int] = None
    description: Optional[str] = None
    account_kind: Optional[str] = None
    update_strategy: Optional[str] = None
    currency: Optional[str] = None
    alex_pct: Optional[int] = None
    alexa_pct: Optional[int] = None
    kids_pct: Optional[int] = None

    @model_validator(mode="after")
    def _check_kind_and_pct(self):
        if self.account_kind is not None and self.account_kind not in _VALID_ACCOUNT_KINDS:
            raise ValueError(f"account_kind must be one of {sorted(_VALID_ACCOUNT_KINDS)}")
        if self.update_strategy is not None and self.update_strategy not in _VALID_UPDATE_STRATEGIES:
            raise ValueError(f"update_strategy must be one of {sorted(_VALID_UPDATE_STRATEGIES)}")
        _validate_ownership_total(self.alex_pct, self.alexa_pct, self.kids_pct)
        return self


class AccountUpdate(BaseModel):
    name: Optional[str] = None
    account_number: Optional[str] = None
    account_type: Optional[AccountType] = None
    parent_id: Optional[int] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    account_kind: Optional[str] = None
    update_strategy: Optional[str] = None
    currency: Optional[str] = None
    alex_pct: Optional[int] = None
    alexa_pct: Optional[int] = None
    kids_pct: Optional[int] = None

    @model_validator(mode="after")
    def _check_kind_and_pct(self):
        if self.account_kind is not None and self.account_kind not in _VALID_ACCOUNT_KINDS:
            raise ValueError(f"account_kind must be one of {sorted(_VALID_ACCOUNT_KINDS)}")
        if self.update_strategy is not None and self.update_strategy not in _VALID_UPDATE_STRATEGIES:
            raise ValueError(f"update_strategy must be one of {sorted(_VALID_UPDATE_STRATEGIES)}")
        # PUT uses exclude_unset so partial updates are normal — only
        # validate the ownership total when ALL three pcts were sent.
        if (self.alex_pct is not None and self.alexa_pct is not None
                and self.kids_pct is not None):
            _validate_ownership_total(self.alex_pct, self.alexa_pct, self.kids_pct)
        return self


def _validate_ownership_total(alex_pct, alexa_pct, kids_pct):
    """Mirror the DB CHECK: all-zero OR sum-to-100. Return early if any
    value is None (means caller didn't send a complete set)."""
    if alex_pct is None and alexa_pct is None and kids_pct is None:
        return
    a, b, c = (alex_pct or 0), (alexa_pct or 0), (kids_pct or 0)
    if a < 0 or b < 0 or c < 0:
        raise ValueError("ownership pcts must be non-negative")
    total = a + b + c
    if total != 0 and total != 100:
        raise ValueError(
            f"ownership pcts must be all-zero (system account) or sum to 100; "
            f"got {a}/{b}/{c} = {total}"
        )


class AccountResponse(BaseModel):
    id: int
    name: str
    account_number: Optional[str]
    account_type: AccountType
    parent_id: Optional[int]
    description: Optional[str]
    is_active: bool
    is_system: bool
    balance: Decimal
    created_at: datetime
    updated_at: datetime
    # Net worth phase 1 fields. All defaults nullable / 0 so existing
    # callers that don't care about them keep working.
    account_kind: Optional[str] = None
    update_strategy: Optional[str] = None
    currency: str = "USD"
    alex_pct: int = 0
    alexa_pct: int = 0
    kids_pct: int = 0
    # Latest balance snapshot — computed by the route handler, not on
    # the ORM model. Optional so accounts with zero snapshots return
    # cleanly as null rather than 0 (which would be misleading).
    latest_balance: Optional[Decimal] = None
    latest_balance_as_of: Optional[date] = None
    latest_balance_currency: Optional[str] = None

    model_config = {"from_attributes": True}
