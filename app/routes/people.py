"""People — phase 1.5.

Read-only endpoint for the household members. Used by the ownership
editor's person dropdown and (in later phase-1.5 commits) by the
miles / credit-score pages and the dashboard hoist.

People rows are seeded by the j2a3b4c5d6e7 migration plus the seed
script. The API doesn't expose create/update/delete — the household
roster changes rarely enough that a manual psql edit is the right
escape hatch. If that changes, add the routes here.
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.people import Person
from app.schemas.people import PersonResponse


router = APIRouter(prefix="/api/people", tags=["people"])


@router.get("", response_model=list[PersonResponse])
def list_people(db: Session = Depends(get_db)):
    """Return all people, ordered by display_order then id."""
    return (
        db.query(Person)
        .order_by(Person.display_order, Person.id)
        .all()
    )
