"""/api/balances tests — net worth phase 1, task 4."""

from datetime import date, timedelta
from decimal import Decimal


def _seed_personal(db_session):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import seed_personal_accounts as seed_module
    seed_module.apply_seed(db_session, today=date(2026, 5, 4))
    db_session.commit()


def test_post_creates_snapshot_and_falls_back_to_account_currency(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    revolut = db_session.query(Account).filter_by(name="Revolut IE").first()

    r = client.post("/api/balances", json={
        "account_id": revolut.id,
        "as_of_date": "2026-05-04",
        "balance": "1234.56",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    # Currency was omitted; should default to the account's native currency.
    assert body["currency"] == "EUR"
    assert Decimal(body["balance"]) == Decimal("1234.56")
    assert body["account_name"] == "Revolut IE"
    assert body["account_kind"] == "bank"


def test_post_upserts_when_account_date_already_exists(client, db_session):
    """Re-entering for same (account, date) should overwrite, not 409."""
    _seed_personal(db_session)
    from app.models.accounts import Account
    from app.models.balance_snapshots import BalanceSnapshot
    house = db_session.query(Account).filter_by(name="US House").first()

    r = client.post("/api/balances", json={
        "account_id": house.id,
        "as_of_date": "2026-05-04",
        "balance": "305000.00",
    })
    assert r.status_code == 201, r.text

    # Original seed had 299000; the upsert should leave exactly one row
    # with the new value, not two.
    rows = db_session.query(BalanceSnapshot).filter(
        BalanceSnapshot.account_id == house.id,
        BalanceSnapshot.as_of_date == date(2026, 5, 4),
    ).all()
    assert len(rows) == 1
    assert rows[0].balance == Decimal("305000.00")


def test_post_explicit_currency_overrides_account_default(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    cks = db_session.query(Account).filter_by(name="Heartland Joint Checking").first()

    r = client.post("/api/balances", json={
        "account_id": cks.id,
        "as_of_date": "2026-05-04",
        "balance": "1500.00",
        "currency": "EUR",  # explicit override (rare but allowed)
    })
    assert r.json()["currency"] == "EUR"


def test_post_unknown_account_returns_404(client):
    r = client.post("/api/balances", json={
        "account_id": 99999999,
        "as_of_date": "2026-05-04",
        "balance": "100",
    })
    assert r.status_code == 404


def test_list_filters_by_account(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    house = db_session.query(Account).filter_by(name="US House").first()
    mortgage = db_session.query(Account).filter_by(name="US Mortgage (PennyMac)").first()

    # Add a few snapshots on different dates so the order test has signal.
    base = date(2026, 5, 4)
    for i in range(3):
        client.post("/api/balances", json={
            "account_id": house.id,
            "as_of_date": (base + timedelta(days=i)).isoformat(),
            "balance": str(299000 + i * 1000),
        })

    r = client.get(f"/api/balances?account_id={house.id}")
    rows = r.json()
    assert all(row["account_id"] == house.id for row in rows)
    # Most-recent first ordering.
    dates = [row["as_of_date"] for row in rows]
    assert dates == sorted(dates, reverse=True)
    # The other account's snapshot should NOT appear.
    for row in rows:
        assert row["account_id"] != mortgage.id


def test_list_default_returns_recent_snapshots_most_recent_first(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    cks = db_session.query(Account).filter_by(name="Heartland Joint Checking").first()
    base = date(2026, 5, 4)
    for i in range(5):
        client.post("/api/balances", json={
            "account_id": cks.id,
            "as_of_date": (base - timedelta(days=i)).isoformat(),
            "balance": str(1000 + i * 50),
        })

    r = client.get("/api/balances")
    rows = r.json()
    assert len(rows) >= 5
    # Returned in date-desc order.
    dates = [row["as_of_date"] for row in rows]
    assert dates == sorted(dates, reverse=True)


def test_delete_removes_snapshot(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    from app.models.balance_snapshots import BalanceSnapshot
    cks = db_session.query(Account).filter_by(name="Heartland Joint Checking").first()
    r = client.post("/api/balances", json={
        "account_id": cks.id,
        "as_of_date": "2026-05-04",
        "balance": "999",
    })
    snap_id = r.json()["id"]

    r = client.delete(f"/api/balances/{snap_id}")
    assert r.status_code == 200
    assert db_session.query(BalanceSnapshot).filter_by(id=snap_id).first() is None


def test_delete_unknown_returns_404(client):
    r = client.delete("/api/balances/9999999")
    assert r.status_code == 404
