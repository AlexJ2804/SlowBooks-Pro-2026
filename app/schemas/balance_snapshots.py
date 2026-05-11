from datetime import date as date_type, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class BalanceSnapshotCreate(BaseModel):
    account_id: int
    as_of_date: date_type
    balance: Decimal
    # Optional — if missing, the route handler fills it from the account's
    # native currency. Always denormalised onto the snapshot row so
    # historical reads stay accurate even if the account currency
    # changes later.
    currency: Optional[str] = Field(default=None, min_length=3, max_length=3)


class BalanceSnapshotResponse(BaseModel):
    id: int
    account_id: int
    as_of_date: date_type
    balance: Decimal
    currency: str
    created_at: datetime
    # Convenience: filled by the route so the UI can show the account
    # name without a separate lookup.
    account_name: Optional[str] = None
    account_kind: Optional[str] = None

    model_config = {"from_attributes": True}
