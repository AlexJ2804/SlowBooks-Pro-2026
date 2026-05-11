from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ClassCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)


class ClassUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    is_archived: Optional[bool] = None


class ClassResponse(BaseModel):
    id: int
    name: str
    is_archived: bool
    is_system_default: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
