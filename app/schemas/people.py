"""Pydantic schemas for the people / account_ownerships domain.

Two flavors of OwnershipShare exist:
  - OwnershipShareIn: minimal shape accepted from the client when
    POSTing or PUTting an account (just person_id + share_pct).
  - OwnershipShareOut: returned to the client; same fields as -In.
    The UI looks up person names separately via GET /api/people, so we
    don't denormalize names onto each ownership row.
"""
from datetime import datetime

from pydantic import BaseModel, Field


_VALID_ROLES = {"parent", "child", "other"}


class PersonResponse(BaseModel):
    id: int
    name: str
    role: str
    display_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class OwnershipShareIn(BaseModel):
    """Single ownership entry in a request body."""
    person_id: int
    share_pct: int = Field(ge=1, le=100)


class OwnershipShareOut(BaseModel):
    """Single ownership entry in a response body."""
    person_id: int
    share_pct: int

    model_config = {"from_attributes": True}
