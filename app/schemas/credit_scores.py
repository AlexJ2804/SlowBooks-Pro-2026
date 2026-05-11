"""Pydantic schemas for the credit scores tracker.

Score range (300-850) and the bureau enum are enforced here at the
schema layer so bad inputs get a clean 422 before touching the DB.
The "parents only" role-gating happens in the route handler because
it needs a DB lookup of person.role.
"""
from datetime import date as date_type, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


Bureau = Literal["Equifax", "Experian", "TransUnion"]


class CreditScoreCreate(BaseModel):
    person_id: int
    bureau: Bureau
    score: int = Field(ge=300, le=850)
    score_model: str = Field(default="FICO 8", min_length=1, max_length=64)
    as_of_date: date_type
    source: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=500)


class CreditScoreBatchEntry(BaseModel):
    """Single (bureau, score) pair inside a batch request. Person and
    as_of_date are common to the whole batch (e.g. "all 3 bureaus on
    May 9 from Credit Karma") and live on the parent BatchCreate."""
    bureau: Bureau
    score: int = Field(ge=300, le=850)
    score_model: str = Field(default="FICO 8", min_length=1, max_length=64)


class CreditScoreBatchCreate(BaseModel):
    person_id: int
    as_of_date: date_type
    source: Optional[str] = Field(default=None, max_length=128)
    notes: Optional[str] = Field(default=None, max_length=500)
    entries: list[CreditScoreBatchEntry] = Field(min_length=1)


class CreditScoreResponse(BaseModel):
    id: int
    person_id: int
    person_name: Optional[str] = None
    bureau: str
    score: int
    score_model: str
    as_of_date: date_type
    source: Optional[str] = None
    notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
