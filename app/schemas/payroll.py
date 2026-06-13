from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


class EmployeeCreate(BaseModel):
    first_name: str
    last_name: str
    ssn_last_four: Optional[str] = None
    pay_type: str = "hourly"
    pay_rate: float = 0
    filing_status: str = "single"
    allowances: int = 0
    address1: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    hire_date: Optional[date] = None


class EmployeeUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    pay_type: Optional[str] = None
    pay_rate: Optional[float] = None
    filing_status: Optional[str] = None
    allowances: Optional[int] = None
    is_active: Optional[bool] = None


class EmployeeResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    ssn_last_four: Optional[str] = None
    pay_type: str
    pay_rate: float = 0
    filing_status: str
    allowances: int = 0
    is_active: bool = True
    hire_date: Optional[date] = None
    model_config = {"from_attributes": True}


class PayStubInput(BaseModel):
    employee_id: int
    hours: float = 0


class PayRunCreate(BaseModel):
    period_start: date
    period_end: date
    pay_date: date
    stubs: list[PayStubInput] = []


class PayStubResponse(BaseModel):
    id: int
    employee_id: int
    employee_name: Optional[str] = None
    hours: float = 0
    gross_pay: float = 0
    federal_tax: float = 0
    state_tax: float = 0
    ss_tax: float = 0
    medicare_tax: float = 0
    net_pay: float = 0
    model_config = {"from_attributes": True}


class PayRunResponse(BaseModel):
    id: int
    period_start: date
    period_end: date
    pay_date: date
    status: str
    total_gross: float = 0
    total_net: float = 0
    total_taxes: float = 0
    stubs: list[PayStubResponse] = []
    model_config = {"from_attributes": True}
