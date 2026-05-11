"""Seed the household airline miles tracker — phase 1.5 task 2.

Idempotent: re-running against a partially-seeded DB skips programmes
and memberships that already exist instead of duplicating.

Programmes seeded with brand colours and logo paths matching the
images in app/static/airline_logos/. Alex's five real memberships
land with member numbers and an initial snapshot dated `today`. Every
other person in the people table gets blank placeholder memberships
across all five programmes — the UI shows them as empty rows the user
can fill in later via the per-row Update form.

Usage:
    from seed_airline_miles import apply_seed
    apply_seed(db_session, today=date(2026, 5, 8))
    db_session.commit()
"""
from datetime import date as date_type, date

from sqlalchemy.orm import Session

from app.models.airline_miles import (
    AirlineMilesSnapshot, AirlineProgram, AirlineProgramMembership,
)
from app.models.people import Person


# Five programmes the household is enrolled in. Brand colours sampled
# from each carrier's published brand guidelines / press kits.
PROGRAMS = [
    {
        "code": "aadvantage",
        "name": "American AAdvantage",
        "alliance": "oneworld",
        "brand_color": "#c8102e",
        "logo_path": "airline_logos/aadvantage.jpeg",
        "display_order": 0,
    },
    {
        "code": "skymiles",
        "name": "Delta SkyMiles",
        "alliance": "skyteam",
        "brand_color": "#003366",
        "logo_path": "airline_logos/skymiles.png",
        "display_order": 1,
    },
    {
        "code": "mileageplus",
        "name": "United MileagePlus",
        "alliance": "star",
        "brand_color": "#002244",
        "logo_path": "airline_logos/mileageplus.png",
        "display_order": 2,
    },
    {
        "code": "aerclub",
        "name": "Aer Lingus AerClub",
        "alliance": "oneworld",
        "brand_color": "#00754a",
        "logo_path": "airline_logos/aerclub.jpg",
        "display_order": 3,
    },
    {
        "code": "aeroplan",
        "name": "Air Canada Aeroplan",
        "alliance": "star",
        "brand_color": "#d22630",
        "logo_path": "airline_logos/aeroplan.png",
        "display_order": 4,
    },
]


# Alex's existing memberships, keyed by program code so the lookup
# stays stable even if program ids shift between environments.
ALEX_MEMBERSHIPS = {
    "aadvantage":  {"member_number": "1TU70K8",                       "balance": 18730},
    "skymiles":    {"member_number": "9283122365",                    "balance": 57670},
    "mileageplus": {"member_number": "UF461456",                      "balance": 10304},
    "aerclub":     {"member_number": "Alexj2804/3081471028162765",    "balance":  5446},
    "aeroplan":    {"member_number": "370845117",                     "balance":     4},
}


def _find_primary_person(db: Session) -> Person | None:
    """The 'primary' person for seeded data: the parent with the lowest
    display_order. Falls back to first row by name='Alex' if no parents
    exist for some reason."""
    primary = (
        db.query(Person)
        .filter(Person.role == "parent")
        .order_by(Person.display_order, Person.id)
        .first()
    )
    if primary is not None:
        return primary
    return db.query(Person).filter(Person.name == "Alex").first()


def apply_seed(db: Session, today: date_type | None = None) -> None:
    if today is None:
        today = date.today()

    # ------------------------------------------------------------------
    # Programmes
    # ------------------------------------------------------------------
    program_by_code: dict[str, AirlineProgram] = {}
    for spec in PROGRAMS:
        existing = (
            db.query(AirlineProgram)
            .filter(AirlineProgram.code == spec["code"])
            .first()
        )
        if existing is not None:
            program_by_code[spec["code"]] = existing
            continue
        prog = AirlineProgram(**spec)
        db.add(prog)
        db.flush()
        program_by_code[spec["code"]] = prog

    # ------------------------------------------------------------------
    # Memberships — every person × every programme
    # ------------------------------------------------------------------
    primary = _find_primary_person(db)
    primary_id = primary.id if primary is not None else None

    people = (
        db.query(Person)
        .order_by(Person.display_order, Person.id)
        .all()
    )

    for person in people:
        for code, prog in program_by_code.items():
            existing = (
                db.query(AirlineProgramMembership)
                .filter(
                    AirlineProgramMembership.program_id == prog.id,
                    AirlineProgramMembership.person_id == person.id,
                )
                .first()
            )
            if existing is not None:
                continue

            data = (
                ALEX_MEMBERSHIPS.get(code, {})
                if person.id == primary_id
                else {}
            )
            membership = AirlineProgramMembership(
                program_id=prog.id,
                person_id=person.id,
                member_number=data.get("member_number"),
            )
            db.add(membership)
            db.flush()

            # Initial snapshot only for the primary person, only if a
            # balance was supplied for that programme.
            if person.id == primary_id and "balance" in data:
                snap_existing = (
                    db.query(AirlineMilesSnapshot)
                    .filter(
                        AirlineMilesSnapshot.membership_id == membership.id,
                        AirlineMilesSnapshot.as_of_date == today,
                    )
                    .first()
                )
                if snap_existing is None:
                    db.add(AirlineMilesSnapshot(
                        membership_id=membership.id,
                        as_of_date=today,
                        balance=data["balance"],
                    ))


if __name__ == "__main__":
    # Allow `python seed_airline_miles.py` to seed against the live DB.
    from app.database import SessionLocal

    session = SessionLocal()
    try:
        apply_seed(session)
        session.commit()
        print("Airline miles seed applied.")
    finally:
        session.close()
