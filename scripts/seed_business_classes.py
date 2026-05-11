"""Seed the household's business classes for per-business attribution.

Phase 3 — spending analytics. Classes tag bank_transactions (and the
BankRules that auto-set them) with which business they belong to,
orthogonal to the COA category. The spending dashboard can then slice
"this is Alex Music's spend, that's Alexa VIPKid's spend".

Classes seeded:
  Personal              — explicit personal/household bucket. Some
                          users prefer a named class over the implicit
                          "class_id IS NULL = personal" convention.
  Alex Music (1099)     — Alex's gig + royalty income, both folded in.
  Alexa VIPKid (1099)
  Alex PEJR LLC (1099)
  Alex Consulting
  Alex Teaching
  AirBnB                — pre-operational; expenses only until the
                          first booking lands.

Idempotent: each row is upserted by case-insensitive name. Re-running
won't create duplicates, and won't touch is_archived state on rows
the user already toggled in the UI.

Run:
    docker exec slowbooks-pro-2026-slowbooks-1 \\
        python -m scripts.seed_business_classes
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func

from app.database import SessionLocal
from app.models.classes import Class


_CLASSES = [
    "Personal",
    "Alex Music (1099)",
    "Alexa VIPKid (1099)",
    "Alex PEJR LLC (1099)",
    "Alex Consulting",
    "Alex Teaching",
    "AirBnB",
]


def apply_seed(db) -> dict:
    counts = {"created": 0, "skipped": 0}
    for name in _CLASSES:
        existing = (
            db.query(Class)
            .filter(func.lower(Class.name) == name.lower())
            .first()
        )
        if existing:
            counts["skipped"] += 1
            continue
        db.add(Class(name=name, is_archived=False, is_system_default=False))
        counts["created"] += 1
    db.flush()
    return counts


def seed():
    db = SessionLocal()
    try:
        counts = apply_seed(db)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    print(f"Business classes: created={counts['created']}, "
          f"skipped (already existed)={counts['skipped']}")
    print()
    print("Next: open /#/categorize — the Class dropdown is populated.")
    print("Leaving Class blank on a row means 'no business attribution'")
    print("(implicit personal/household).")


if __name__ == "__main__":
    seed()
