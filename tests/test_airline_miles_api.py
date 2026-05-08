"""/api/airline-miles tests — phase 1.5 task 2."""

from datetime import date


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _seed_people(db_session):
    """The miles feature depends on people existing. The migration that
    seeds Alex/Alexa/Theodore doesn't run under SQLite tests, so we
    create them inline here."""
    from app.models.people import Person
    p1 = Person(name="Alex", role="parent", display_order=0)
    p2 = Person(name="Alexa", role="parent", display_order=1)
    p3 = Person(name="Theodore", role="child", display_order=2)
    db_session.add_all([p1, p2, p3])
    db_session.commit()
    return p1, p2, p3


def _seed_miles(db_session, today=None):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import seed_airline_miles as seed_module
    seed_module.apply_seed(db_session, today=today or date(2026, 5, 8))
    db_session.commit()


# ---------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------
def test_seed_creates_five_programs_with_unique_codes(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)

    r = client.get("/api/airline-miles/programs")
    assert r.status_code == 200, r.text
    programs = r.json()
    assert len(programs) == 5
    codes = {p["code"] for p in programs}
    assert codes == {"aadvantage", "skymiles", "mileageplus", "aerclub", "aeroplan"}
    # Brand colours present and shaped like a hex literal.
    for p in programs:
        assert p["brand_color"].startswith("#")
        assert len(p["brand_color"]) == 7


def test_seed_is_idempotent(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)
    _seed_miles(db_session)  # second pass should not duplicate
    r = client.get("/api/airline-miles/programs")
    assert len(r.json()) == 5


# ---------------------------------------------------------------------
# Page payload — programs with memberships
# ---------------------------------------------------------------------
def test_page_payload_groups_memberships_under_programs(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)

    r = client.get("/api/airline-miles")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert len(payload) == 5

    # Each programme card carries a row for every person (3 people × 5 programmes = 15).
    total_rows = sum(len(p["memberships"]) for p in payload)
    assert total_rows == 15
    for prog in payload:
        assert len(prog["memberships"]) == 3
        # Rows ordered by person display_order (Alex first).
        orders = [m["person_display_order"] for m in prog["memberships"]]
        assert orders == sorted(orders)


def test_alex_membership_carries_member_number_and_balance(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)

    r = client.get("/api/airline-miles")
    payload = r.json()

    aadvantage = next(p for p in payload if p["code"] == "aadvantage")
    alex_row = next(m for m in aadvantage["memberships"] if m["person_name"] == "Alex")
    assert alex_row["member_number"] == "1TU70K8"
    assert alex_row["latest_balance"] == 18730
    assert alex_row["latest_as_of_date"] == "2026-05-08"

    # The other two people get blank placeholder rows on the same programme.
    others = [m for m in aadvantage["memberships"] if m["person_name"] != "Alex"]
    assert all(m["member_number"] is None for m in others)
    assert all(m["latest_balance"] is None for m in others)


def test_program_total_balance_sums_only_present_snapshots(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)

    r = client.get("/api/airline-miles")
    payload = r.json()
    skymiles = next(p for p in payload if p["code"] == "skymiles")
    # Only Alex has a snapshot (57670); blank rows contribute 0.
    assert skymiles["total_balance"] == 57670


# ---------------------------------------------------------------------
# Snapshot upsert
# ---------------------------------------------------------------------
def test_snapshot_post_creates_then_upserts_same_date(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)

    from app.models.airline_miles import (
        AirlineMilesSnapshot, AirlineProgram, AirlineProgramMembership,
    )
    from app.models.people import Person

    aadvantage = (
        db_session.query(AirlineProgram).filter_by(code="aadvantage").first()
    )
    alexa = db_session.query(Person).filter_by(name="Alexa").first()
    membership = (
        db_session.query(AirlineProgramMembership)
        .filter_by(program_id=aadvantage.id, person_id=alexa.id)
        .first()
    )

    # First entry — creates a new snapshot.
    r = client.post("/api/airline-miles/snapshots", json={
        "membership_id": membership.id,
        "as_of_date": "2026-05-08",
        "balance": 5000,
    })
    assert r.status_code == 201, r.text
    assert r.json()["balance"] == 5000

    # Same date again — should overwrite, not 409.
    r = client.post("/api/airline-miles/snapshots", json={
        "membership_id": membership.id,
        "as_of_date": "2026-05-08",
        "balance": 7500,
    })
    assert r.status_code == 201, r.text
    assert r.json()["balance"] == 7500

    rows = (
        db_session.query(AirlineMilesSnapshot)
        .filter_by(membership_id=membership.id, as_of_date=date(2026, 5, 8))
        .all()
    )
    assert len(rows) == 1
    assert rows[0].balance == 7500


def test_snapshot_negative_balance_rejected(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)

    from app.models.airline_miles import AirlineProgram, AirlineProgramMembership
    from app.models.people import Person

    aero = db_session.query(AirlineProgram).filter_by(code="aeroplan").first()
    alex = db_session.query(Person).filter_by(name="Alex").first()
    m = (
        db_session.query(AirlineProgramMembership)
        .filter_by(program_id=aero.id, person_id=alex.id)
        .first()
    )

    r = client.post("/api/airline-miles/snapshots", json={
        "membership_id": m.id,
        "as_of_date": "2026-05-08",
        "balance": -100,
    })
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------
# Membership create/update
# ---------------------------------------------------------------------
def test_create_membership_rejects_duplicate(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)

    from app.models.airline_miles import AirlineProgram
    from app.models.people import Person

    aer = db_session.query(AirlineProgram).filter_by(code="aerclub").first()
    alex = db_session.query(Person).filter_by(name="Alex").first()

    r = client.post("/api/airline-miles/memberships", json={
        "program_id": aer.id,
        "person_id": alex.id,
    })
    assert r.status_code == 409, r.text


def test_patch_membership_updates_only_supplied_fields(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)

    from app.models.airline_miles import AirlineProgram, AirlineProgramMembership
    from app.models.people import Person

    united = db_session.query(AirlineProgram).filter_by(code="mileageplus").first()
    alexa = db_session.query(Person).filter_by(name="Alexa").first()
    m = (
        db_session.query(AirlineProgramMembership)
        .filter_by(program_id=united.id, person_id=alexa.id)
        .first()
    )

    # Only update member_number — elite_status (currently None) must stay None.
    r = client.patch(f"/api/airline-miles/memberships/{m.id}", json={
        "member_number": "UA999",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["member_number"] == "UA999"
    assert body["elite_status"] is None


def test_delete_membership_cascades_snapshots(client, db_session):
    _seed_people(db_session)
    _seed_miles(db_session)

    from app.models.airline_miles import (
        AirlineMilesSnapshot, AirlineProgram, AirlineProgramMembership,
    )
    from app.models.people import Person

    aa = db_session.query(AirlineProgram).filter_by(code="aadvantage").first()
    alex = db_session.query(Person).filter_by(name="Alex").first()
    m = (
        db_session.query(AirlineProgramMembership)
        .filter_by(program_id=aa.id, person_id=alex.id)
        .first()
    )
    membership_id = m.id

    # Pre-delete: Alex has the seed snapshot.
    assert (
        db_session.query(AirlineMilesSnapshot)
        .filter_by(membership_id=membership_id)
        .count()
        == 1
    )

    r = client.delete(f"/api/airline-miles/memberships/{membership_id}")
    assert r.status_code == 200, r.text

    db_session.expire_all()
    assert (
        db_session.query(AirlineMilesSnapshot)
        .filter_by(membership_id=membership_id)
        .count()
        == 0
    )
