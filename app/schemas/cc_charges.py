from datetime import date
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class CCChargeCreate(BaseModel):
    date: date
    payee: Optional[str] = None
    account_id: int
    amount: Decimal
    memo: Optional[str] = None
    reference: Optional[str] = None
    currency: str = "USD"
    exchange_rate: Decimal = Decimal("1")
    class_id: Optional[int] = None


class CCChargeResponse(BaseModel):
    id: int
    date: date
    payee: str = ""
    account_name: str = ""
    amount: float
    memo: str = ""
    reference: str = ""
    currency: str = "USD"
    exchange_rate: float = 1
    home_currency_amount: float = 0
    class_id: int = 0
