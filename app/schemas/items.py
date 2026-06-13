from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel

from app.models.items import ItemType


class ItemCreate(BaseModel):
    name: str
    item_type: ItemType
    description: Optional[str] = None
    rate: Decimal = Decimal("0")
    cost: Decimal = Decimal("0")
    income_account_id: Optional[int] = None
    expense_account_id: Optional[int] = None
    is_taxable: bool = True


class ItemUpdate(BaseModel):
    name: Optional[str] = None
    item_type: Optional[ItemType] = None
    description: Optional[str] = None
    rate: Optional[Decimal] = None
    cost: Optional[Decimal] = None
    income_account_id: Optional[int] = None
    expense_account_id: Optional[int] = None
    is_taxable: Optional[bool] = None
    is_active: Optional[bool] = None


class ItemResponse(BaseModel):
    id: int
    name: str
    item_type: ItemType
    description: Optional[str]
    rate: Decimal
    cost: Decimal
    income_account_id: Optional[int]
    expense_account_id: Optional[int]
    is_taxable: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
