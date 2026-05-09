"""Seed the credit_scores table — phase 1.5 task 3.

Skeleton only. The household enters their own scores through the UI
once the page lands; we don't ship synthetic data because credit
scores are sensitive enough that a fake reading sitting in the table
during dev would be confusing.

Idempotent shape mirrors seed_airline_miles.py so it can grow real
seed data later without restructuring the file.

Usage:
    from seed_credit_scores import apply_seed
    apply_seed(db_session)
    db_session.commit()
"""
import sys
from datetime import date as date_type, date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy.orm import Session

from app.models.credit_scores import CreditScore  # noqa: F401  (kept for symmetry)


# Each entry: (person_name, bureau, score_model, as_of_date, score, source).
# Empty by default — fill in real readings here only if you want them
# baked into the seed (e.g. for a demo environment). Production data
# should be entered through the UI to keep PII out of the git history.
_INITIAL_READINGS: list[dict] = []


def apply_seed(db: Session, today: date_type | None = None) -> None:
    if today is None:
        today = date.today()

    for entry in _INITIAL_READINGS:
        from app.models.people import Person
        person = (
            db.query(Person).filter(Person.name == entry["person_name"]).first()
        )
        if person is None:
            continue
        existing = (
            db.query(CreditScore)
            .filter(
                CreditScore.person_id == person.id,
                CreditScore.bureau == entry["bureau"],
                CreditScore.score_model == entry.get("score_model", "FICO 8"),
                CreditScore.as_of_date == entry["as_of_date"],
            )
            .first()
        )
        if existing is not None:
            continue
        db.add(CreditScore(
            person_id=person.id,
            bureau=entry["bureau"],
            score=entry["score"],
            score_model=entry.get("score_model", "FICO 8"),
            as_of_date=entry["as_of_date"],
            source=entry.get("source"),
            notes=entry.get("notes"),
        ))


if __name__ == "__main__":
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        apply_seed(session)
        session.commit()
        print("Credit scores seed applied.")
    finally:
        session.close()
