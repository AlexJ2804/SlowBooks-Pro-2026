"""/api/credit-scores tests — phase 1.5 task 3."""

from datetime import date


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _seed_people(db_session):
    """The migration that seeds Alex/Alexa/Theodore doesn't run under
    SQLite tests, so we create them inline."""
    from app.models.people import Person
    p1 = Person(name="Alex", role="parent", display_order=0)
    p2 = Person(name="Alexa", role="parent", display_order=1)
    p3 = Person(name="Theodore", role="child", display_order=2)
    db_session.add_all([p1, p2, p3])
    db_session.commit()
    return p1, p2, p3


# ---------------------------------------------------------------------
# Single create
# ---------------------------------------------------------------------
def test_post_creates_credit_score_for_parent(client, db_session):
    alex, _, _ = _seed_people(db_session)

    r = client.post("/api/credit-scores", json={
        "person_id": alex.id,
        "bureau": "Equifax",
        "score": 780,
        "as_of_date": "2026-05-09",
        "source": "Credit Karma",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["score"] == 780
    assert body["score_model"] == "FICO 8"  # default
    assert body["person_name"] == "Alex"


def test_post_for_child_role_returns_422(client, db_session):
    _, _, theo = _seed_people(db_session)

    r = client.post("/api/credit-scores", json={
        "person_id": theo.id,
        "bureau": "Equifax",
        "score": 700,
        "as_of_date": "2026-05-09",
    })
    assert r.status_code == 422, r.text
    assert "parent" in r.json()["detail"].lower()


def test_post_score_below_300_rejected(client, db_session):
    alex, _, _ = _seed_people(db_session)

    r = client.post("/api/credit-scores", json={
        "person_id": alex.id,
        "bureau": "Equifax",
        "score": 299,
        "as_of_date": "2026-05-09",
    })
    assert r.status_code == 422, r.text


def test_post_score_above_850_rejected(client, db_session):
    alex, _, _ = _seed_people(db_session)

    r = client.post("/api/credit-scores", json={
        "person_id": alex.id,
        "bureau": "Equifax",
        "score": 851,
        "as_of_date": "2026-05-09",
    })
    assert r.status_code == 422, r.text


def test_post_score_at_exact_bounds_accepted(client, db_session):
    alex, _, _ = _seed_people(db_session)

    for score in (300, 850):
        r = client.post("/api/credit-scores", json={
            "person_id": alex.id,
            "bureau": "Equifax",
            "score": score,
            # Different model so the unique tuple doesn't collide.
            "score_model": f"FICO 8 ({score})",
            "as_of_date": "2026-05-09",
        })
        assert r.status_code == 201, r.text


def test_post_unknown_bureau_rejected(client, db_session):
    alex, _, _ = _seed_people(db_session)

    r = client.post("/api/credit-scores", json={
        "person_id": alex.id,
        "bureau": "TransUion",  # typo
        "score": 700,
        "as_of_date": "2026-05-09",
    })
    assert r.status_code == 422, r.text


def test_post_upserts_same_unique_tuple(client, db_session):
    """Re-posting for the same (person, bureau, model, date) should
    overwrite the score rather than 409."""
    alex, _, _ = _seed_people(db_session)

    r1 = client.post("/api/credit-scores", json={
        "person_id": alex.id,
        "bureau": "Equifax",
        "score": 720,
        "as_of_date": "2026-05-09",
    })
    assert r1.status_code == 201, r1.text

    r2 = client.post("/api/credit-scores", json={
        "person_id": alex.id,
        "bureau": "Equifax",
        "score": 745,
        "as_of_date": "2026-05-09",
    })
    assert r2.status_code == 201, r2.text
    assert r2.json()["id"] == r1.json()["id"]
    assert r2.json()["score"] == 745


# ---------------------------------------------------------------------
# Batch
# ---------------------------------------------------------------------
def test_batch_creates_three_bureaus_at_once(client, db_session):
    alex, _, _ = _seed_people(db_session)

    r = client.post("/api/credit-scores/batch", json={
        "person_id": alex.id,
        "as_of_date": "2026-05-09",
        "source": "Experian.com",
        "entries": [
            {"bureau": "Equifax", "score": 780},
            {"bureau": "Experian", "score": 776},
            {"bureau": "TransUnion", "score": 782},
        ],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body) == 3
    assert {b["bureau"] for b in body} == {"Equifax", "Experian", "TransUnion"}
    assert all(b["source"] == "Experian.com" for b in body)


def test_batch_for_child_returns_422_with_no_writes(client, db_session):
    _, _, theo = _seed_people(db_session)

    from app.models.credit_scores import CreditScore

    r = client.post("/api/credit-scores/batch", json={
        "person_id": theo.id,
        "as_of_date": "2026-05-09",
        "entries": [{"bureau": "Equifax", "score": 700}],
    })
    assert r.status_code == 422, r.text
    assert db_session.query(CreditScore).count() == 0


def test_batch_dedupes_same_bureau_within_request(client, db_session):
    """Two entries for the same (bureau, model) — last one wins."""
    alex, _, _ = _seed_people(db_session)

    r = client.post("/api/credit-scores/batch", json={
        "person_id": alex.id,
        "as_of_date": "2026-05-09",
        "entries": [
            {"bureau": "Equifax", "score": 700},
            {"bureau": "Equifax", "score": 720},
        ],
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body) == 1
    assert body[0]["score"] == 720


# ---------------------------------------------------------------------
# List + filters
# ---------------------------------------------------------------------
def test_list_filters_by_person_id_and_bureau(client, db_session):
    alex, alexa, _ = _seed_people(db_session)

    # Seed a small spread.
    rows = [
        (alex.id,  "Equifax",    780, "2026-05-09"),
        (alex.id,  "Experian",   776, "2026-05-09"),
        (alexa.id, "Equifax",    810, "2026-05-09"),
        (alexa.id, "TransUnion", 805, "2026-05-09"),
    ]
    for pid, bureau, score, day in rows:
        client.post("/api/credit-scores", json={
            "person_id": pid, "bureau": bureau, "score": score,
            "as_of_date": day,
        })

    r_all = client.get("/api/credit-scores")
    assert len(r_all.json()) == 4

    r_alex = client.get(f"/api/credit-scores?person_id={alex.id}")
    assert len(r_alex.json()) == 2
    assert all(s["person_id"] == alex.id for s in r_alex.json())

    r_eqf = client.get("/api/credit-scores?bureau=Equifax")
    assert len(r_eqf.json()) == 2
    assert all(s["bureau"] == "Equifax" for s in r_eqf.json())


def test_list_orders_by_date_desc_then_created_desc(client, db_session):
    alex, _, _ = _seed_people(db_session)

    for day, score in [("2026-05-01", 770), ("2026-05-09", 780), ("2026-05-05", 775)]:
        client.post("/api/credit-scores", json={
            "person_id": alex.id, "bureau": "Equifax",
            "score": score, "as_of_date": day,
            "score_model": f"M-{day}",  # avoid unique collision
        })

    r = client.get("/api/credit-scores")
    days = [s["as_of_date"] for s in r.json()]
    assert days == ["2026-05-09", "2026-05-05", "2026-05-01"]


def test_latest_per_person_bureau_lookup_is_deterministic(client, db_session):
    """Two readings for same (person, bureau) on different dates;
    list endpoint returns them both and the most recent comes first
    so the UI's 'latest' selector is just rows[0]."""
    alex, _, _ = _seed_people(db_session)

    client.post("/api/credit-scores", json={
        "person_id": alex.id, "bureau": "Equifax", "score": 720,
        "as_of_date": "2026-04-01",
    })
    client.post("/api/credit-scores", json={
        "person_id": alex.id, "bureau": "Equifax", "score": 745,
        "as_of_date": "2026-05-09",
    })

    r = client.get(f"/api/credit-scores?person_id={alex.id}&bureau=Equifax")
    body = r.json()
    assert len(body) == 2
    assert body[0]["as_of_date"] == "2026-05-09"
    assert body[0]["score"] == 745


# ---------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------
def test_delete_removes_one_row(client, db_session):
    alex, _, _ = _seed_people(db_session)

    r = client.post("/api/credit-scores", json={
        "person_id": alex.id, "bureau": "Equifax", "score": 780,
        "as_of_date": "2026-05-09",
    })
    score_id = r.json()["id"]

    r_del = client.delete(f"/api/credit-scores/{score_id}")
    assert r_del.status_code == 200, r_del.text

    r_list = client.get("/api/credit-scores")
    assert len(r_list.json()) == 0


def test_delete_unknown_id_returns_404(client, db_session):
    _seed_people(db_session)
    r = client.delete("/api/credit-scores/9999")
    assert r.status_code == 404
