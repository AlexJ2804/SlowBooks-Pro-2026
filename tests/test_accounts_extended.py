"""Tests for the net-worth extensions to /api/accounts.

Pins:
- New columns (kind, ownership pcts, currency, update_strategy) round-trip
  through GET / PUT correctly.
- Latest-snapshot fields are attached when balance_snapshots exist.
- Ownership-pct validation rejects invalid sums via 422 (Pydantic) without
  reaching the DB CHECK constraint, so the API surfaces a clean error
  message instead of a generic 500.
- account_kind / update_strategy enum values are validated.
"""

from datetime import date
from decimal import Decimal


def _seed_personal(db_session):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import seed_personal_accounts as seed_module
    seed_module.apply_seed(db_session, today=date(2026, 5, 4))
    db_session.commit()


def test_list_accounts_includes_new_fields(client, db_session):
    _seed_personal(db_session)
    r = client.get("/api/accounts")
    assert r.status_code == 200, r.text
    rows = r.json()

    by_name = {a["name"]: a for a in rows}
    cks = by_name["Heartland Joint Checking"]
    assert cks["account_kind"] == "bank"
    assert cks["update_strategy"] == "transactional"
    assert cks["currency"] == "USD"
    assert (cks["alex_pct"], cks["alexa_pct"], cks["kids_pct"]) == (50, 50, 0)


def test_list_accounts_attaches_latest_balance(client, db_session):
    _seed_personal(db_session)
    r = client.get("/api/accounts")
    rows = r.json()
    by_name = {a["name"]: a for a in rows}

    house = by_name["US House"]
    assert Decimal(house["latest_balance"]) == Decimal("299000.00")
    assert house["latest_balance_currency"] == "USD"
    assert house["latest_balance_as_of"] == "2026-05-04"

    # Accounts with no snapshots come back with null latest_balance fields.
    revolut = by_name["Revolut IE"]
    assert revolut["latest_balance"] is None
    assert revolut["latest_balance_as_of"] is None
    assert revolut["latest_balance_currency"] is None


def test_list_accounts_filters_by_kind(client, db_session):
    _seed_personal(db_session)
    r = client.get("/api/accounts?account_kind=bank")
    rows = r.json()
    assert len(rows) == 7  # spec: 7 banks
    assert all(a["account_kind"] == "bank" for a in rows)


def test_update_account_changes_ownership_and_currency(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    revolut = db_session.query(Account).filter_by(name="Revolut IE").first()

    r = client.put(f"/api/accounts/{revolut.id}", json={
        "alex_pct": 60, "alexa_pct": 40, "kids_pct": 0,
        "currency": "GBP",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["alex_pct"] == 60
    assert body["alexa_pct"] == 40
    assert body["currency"] == "GBP"


def test_update_account_rejects_pct_sum_not_100_or_0(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    cks = db_session.query(Account).filter_by(name="Heartland Joint Checking").first()

    # Sum to 90 — invalid.
    r = client.put(f"/api/accounts/{cks.id}", json={
        "alex_pct": 30, "alexa_pct": 30, "kids_pct": 30,
    })
    assert r.status_code == 422, r.text
    # Pydantic v2 nests detail under loc/msg; check substring.
    assert "sum to 100" in r.text or "all-zero" in r.text


def test_update_account_rejects_invalid_kind(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    cks = db_session.query(Account).filter_by(name="Heartland Joint Checking").first()

    r = client.put(f"/api/accounts/{cks.id}", json={"account_kind": "crypto"})
    assert r.status_code == 422
    assert "account_kind" in r.text


def test_update_account_rejects_invalid_strategy(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    a = db_session.query(Account).filter_by(name="Vanguard (Alexa)").first()

    r = client.put(f"/api/accounts/{a.id}", json={"update_strategy": "magic"})
    assert r.status_code == 422
    assert "update_strategy" in r.text


def test_partial_update_only_one_pct_is_allowed(client, db_session):
    """If the user only sends one pct (e.g. via a partial form), Pydantic
    skips the sum-validation rather than rejecting — the DB CHECK still
    catches a final invalid state. This pins that we don't over-reject."""
    _seed_personal(db_session)
    from app.models.accounts import Account
    cks = db_session.query(Account).filter_by(name="Heartland Joint Checking").first()

    # Note: this WILL hit the DB CHECK on commit (50 + 50 + 0 → 50 + 50 + 0,
    # unchanged because we only sent alex_pct=50). So commit succeeds.
    r = client.put(f"/api/accounts/{cks.id}", json={"alex_pct": 50})
    assert r.status_code == 200, r.text


def test_get_single_account_returns_latest_balance(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    house = db_session.query(Account).filter_by(name="US House").first()

    r = client.get(f"/api/accounts/{house.id}")
    assert r.status_code == 200
    assert Decimal(r.json()["latest_balance"]) == Decimal("299000.00")


def test_account_is_system_is_active_have_server_defaults(db_session):
    """Pin that the Account model declares server-side defaults for
    is_system / is_active (matching the i1f2a3b4c5d6 migration). Raw
    SQL INSERTs that omit these columns get FALSE / TRUE rather than
    NULL — closes the dirty-data path that surfaced when the May-2026
    IIF bootstrap SQL inserted accounts without is_system."""
    from app.models.accounts import Account
    is_system_col = Account.__table__.c.is_system
    is_active_col = Account.__table__.c.is_active
    assert is_system_col.nullable is False
    assert is_active_col.nullable is False
    assert is_system_col.server_default is not None
    assert is_active_col.server_default is not None
    # Default-text inspection: SQLAlchemy stores DefaultClause; .arg holds
    # the raw text/clause. Stringify and check for the expected literal.
    assert "false" in str(is_system_col.server_default.arg).lower()
    assert "true" in str(is_active_col.server_default.arg).lower()
