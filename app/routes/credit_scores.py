"""Credit scores tracker — phase 1.5 task 3.

Endpoints:
- GET    /api/credit-scores                  list, optional ?person_id and ?bureau filters
- POST   /api/credit-scores                  upsert one row by (person_id, bureau, score_model, as_of_date)
- POST   /api/credit-scores/batch            upsert several at once (e.g. all 3 bureaus on the same day)
- DELETE /api/credit-scores/{id}             remove a reading

Role-gating: only people with role='parent' are allowed to have
credit scores recorded. Children (Theodore is a minor at the time
this lands) get a 422 with a specific message rather than a generic
400 — the user's most likely mistake here is selecting the wrong
person from a dropdown, and we want the error to read clearly enough
that they understand why.

POST is upsert-by-unique-tuple: re-entering for the same
(person_id, bureau, score_model, as_of_date) updates the existing
row (score, source, notes) rather than 409-ing. Same pattern as
balance_snapshots and airline_miles_snapshots — the user re-pulls
their score and just wants the latest reading recorded.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.credit_scores import CreditScore
from app.models.people import Person
from app.schemas.credit_scores import (
    CreditScoreBatchCreate, CreditScoreCreate, CreditScoreResponse,
)


router = APIRouter(prefix="/api/credit-scores", tags=["credit-scores"])


def _to_response(row: CreditScore, person: Optional[Person] = None) -> dict:
    """Serialize a CreditScore row to the response shape, with the
    person name flattened in for UI convenience."""
    return {
        "id": row.id,
        "person_id": row.person_id,
        "person_name": person.name if person is not None else (
            row.person.name if row.person is not None else None
        ),
        "bureau": row.bureau,
        "score": row.score,
        "score_model": row.score_model,
        "as_of_date": row.as_of_date,
        "source": row.source,
        "notes": row.notes,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _check_person_is_parent(db: Session, person_id: int) -> Person:
    """Look up a person and reject the insert if they're not a parent.

    Raises 404 if the person doesn't exist, 422 if they exist but
    aren't role='parent'. Returned for re-use by the caller (so the
    response can carry the person's name without a second query)."""
    person = db.query(Person).filter(Person.id == person_id).first()
    if person is None:
        raise HTTPException(status_code=404, detail="Person not found")
    if person.role != "parent":
        raise HTTPException(
            status_code=422,
            detail="Credit scores can only be recorded for adult parents",
        )
    return person


def _upsert_one(
    db: Session, person_id: int, bureau: str, score: int, score_model: str,
    as_of_date, source: Optional[str], notes: Optional[str],
) -> CreditScore:
    """Insert a new row or overwrite the existing row for the unique
    tuple. Caller commits."""
    existing = (
        db.query(CreditScore)
        .filter(
            CreditScore.person_id == person_id,
            CreditScore.bureau == bureau,
            CreditScore.score_model == score_model,
            CreditScore.as_of_date == as_of_date,
        )
        .first()
    )
    if existing is not None:
        existing.score = score
        existing.source = source
        existing.notes = notes
        return existing

    row = CreditScore(
        person_id=person_id,
        bureau=bureau,
        score=score,
        score_model=score_model,
        as_of_date=as_of_date,
        source=source,
        notes=notes,
    )
    db.add(row)
    return row


# ---------------------------------------------------------------------
# List + filter
# ---------------------------------------------------------------------
@router.get("", response_model=list[CreditScoreResponse])
def list_credit_scores(
    person_id: Optional[int] = None,
    bureau: Optional[str] = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    q = db.query(CreditScore, Person).join(
        Person, Person.id == CreditScore.person_id,
    )
    if person_id is not None:
        q = q.filter(CreditScore.person_id == person_id)
    if bureau is not None:
        q = q.filter(CreditScore.bureau == bureau)
    rows = (
        q.order_by(
            CreditScore.as_of_date.desc(),
            CreditScore.created_at.desc(),
        )
        .limit(limit)
        .all()
    )
    return [_to_response(r, p) for (r, p) in rows]


# ---------------------------------------------------------------------
# Single create / upsert
# ---------------------------------------------------------------------
@router.post("", response_model=CreditScoreResponse, status_code=201)
def create_credit_score(data: CreditScoreCreate, db: Session = Depends(get_db)):
    person = _check_person_is_parent(db, data.person_id)
    row = _upsert_one(
        db, data.person_id, data.bureau, data.score, data.score_model,
        data.as_of_date, data.source, data.notes,
    )
    db.commit()
    db.refresh(row)
    return _to_response(row, person)


# ---------------------------------------------------------------------
# Batch create / upsert (the common UI flow — 3 bureaus at once)
# ---------------------------------------------------------------------
@router.post("/batch", response_model=list[CreditScoreResponse], status_code=201)
def create_credit_scores_batch(
    data: CreditScoreBatchCreate, db: Session = Depends(get_db),
):
    person = _check_person_is_parent(db, data.person_id)

    # Deduplicate within the batch on (bureau, score_model). Two entries
    # for the same bureau in one submission almost certainly means the
    # user typed the same row twice — last one wins, no error.
    seen: dict[tuple[str, str], int] = {}
    deduped = []
    for e in data.entries:
        key = (e.bureau, e.score_model)
        if key in seen:
            deduped[seen[key]] = e
        else:
            seen[key] = len(deduped)
            deduped.append(e)

    created: list[CreditScore] = []
    for e in deduped:
        row = _upsert_one(
            db, data.person_id, e.bureau, e.score, e.score_model,
            data.as_of_date, data.source, data.notes,
        )
        created.append(row)
    db.commit()
    for r in created:
        db.refresh(r)
    return [_to_response(r, person) for r in created]


# ---------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------
@router.delete("/{score_id}")
def delete_credit_score(score_id: int, db: Session = Depends(get_db)):
    row = db.query(CreditScore).filter(CreditScore.id == score_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Credit score not found")
    db.delete(row)
    db.commit()
    return {"message": "Credit score deleted"}
