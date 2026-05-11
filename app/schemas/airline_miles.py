"""Pydantic schemas for the airline miles tracker.



The page render needs the whole graph in one call — programs with

their memberships and the latest snapshot per membership — so the

response model nests memberships under each program. Updates use

flatter Create / Update shapes with explicit FKs.

"""

from datetime import date as date_type, datetime

from typing import Optional



from pydantic import BaseModel, Field





# ---------------------------------------------------------------------

# Program

# ---------------------------------------------------------------------

class AirlineProgramCreate(BaseModel):

    code: str = Field(min_length=1, max_length=64)

    name: str = Field(min_length=1, max_length=128)

    alliance: str = Field(default="none")

    brand_color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")

    logo_path: Optional[str] = None

    display_order: int = 0





class AirlineProgramResponse(BaseModel):

    id: int

    code: str

    name: str

    alliance: str

    brand_color: str

    logo_path: Optional[str] = None

    display_order: int

    created_at: datetime

    updated_at: datetime



    model_config = {"from_attributes": True}





# ---------------------------------------------------------------------

# Membership

# ---------------------------------------------------------------------

class MembershipCreate(BaseModel):

    program_id: int

    person_id: int

    member_number: Optional[str] = None

    elite_status: Optional[str] = None

    notes: Optional[str] = None





class MembershipUpdate(BaseModel):

    """Fields editable from the per-row form. program/person can't change

    (that's a different membership); the upsert key is fixed."""

    member_number: Optional[str] = None

    elite_status: Optional[str] = None

    notes: Optional[str] = None





class MembershipRow(BaseModel):

    """One row inside the program card. Includes the latest snapshot

    flattened so the UI doesn't have to reach into a sub-object."""

    id: int

    program_id: int

    person_id: int

    person_name: str

    person_display_order: int

    member_number: Optional[str] = None

    elite_status: Optional[str] = None

    notes: Optional[str] = None

    latest_balance: Optional[int] = None

    latest_as_of_date: Optional[date_type] = None



    model_config = {"from_attributes": True}





# ---------------------------------------------------------------------

# Page payload — programs with their memberships nested

# ---------------------------------------------------------------------

class ProgramWithMemberships(BaseModel):

    id: int

    code: str

    name: str

    alliance: str

    brand_color: str

    logo_path: Optional[str] = None

    display_order: int

    memberships: list[MembershipRow]

    total_balance: int  # sum of latest_balance across rows; 0 if none



    model_config = {"from_attributes": True}





# ---------------------------------------------------------------------

# Snapshot

# ---------------------------------------------------------------------

class SnapshotCreate(BaseModel):

    membership_id: int

    as_of_date: date_type

    balance: int = Field(ge=0)

    notes: Optional[str] = None





class SnapshotResponse(BaseModel):

    id: int

    membership_id: int

    as_of_date: date_type

    balance: int

    notes: Optional[str] = None

    created_at: datetime



    model_config = {"from_attributes": True}

