"""/api/net-worth dashboard aggregation tests.

fx_service.get_rate is mocked across all tests so we never hit the
Bank of Canada API. Each test populates the rate map for the pairs
the dashboard will request.
"""

from datetime import date
from decimal import Decimal

import pytest


@pytest.fixture
def mock_fx(monkeypatch):
    """Stub for fx_get_rate. Tests populate `state['rates']` with
    {(from, to): Decimal} entries. Missing pairs return rate=None to
    simulate an unavailable rate."""
    state = {"rates": {}, "calls": []}

    def fake_get_rate(from_code, to_code):
        f = (from_code or "").upper()
        t = (to_code or "").upper()
        state["calls"].append((f, t))
        if f == t:
            return {"rate": Decimal("1"), "observation_date": None,
                    "source": "identity", "error": None}
        v = state["rates"].get((f, t))
        if v is None:
            return {"rate": None, "observation_date": None,
                    "source": None, "error": "rate unavailable"}
        return {"rate": v, "observation_date": "2026-05-04",
                "source": "bankofcanada-direct", "error": None}

    monkeypatch.setattr("app.routes.net_worth.fx_get_rate", fake_get_rate)
    return state


def _seed_personal(db_session):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import seed_personal_accounts as seed_module
    seed_module.apply_seed(db_session, today=date(2026, 5, 4))
    db_session.commit()


def _add_snapshot(client, account_id, balance, as_of="2026-05-04", currency=None):
    payload = {
        "account_id": account_id,
        "as_of_date": as_of,
        "balance": str(balance),
    }
    if currency:
        payload["currency"] = currency
    r = client.post("/api/balances", json=payload)
    assert r.status_code == 201, r.text


def _by_id(seq, name):
    """Helper: fetch the account named `name` (DB-side via session)."""
    return seq.query.filter_by(name=name).first()


# --- Smoke / shape ---------------------------------------------------------

def test_dashboard_runs_with_just_seed_no_extra_balances(client, db_session, mock_fx):
    _seed_personal(db_session)
    r = client.get("/api/net-worth")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["home_currency"] == "USD"
    # Seed creates snapshots for US House + US Mortgage only.
    # House (asset, 50/50/0): 299000 → +299000 USD
    # Mortgage (liability, 50/50/0): 232000 → -232000 USD
    # Household net = 299000 - 232000 = 67000.
    assert Decimal(body["totals"]["household"]["net"]) == Decimal("67000.00")
    assert Decimal(body["totals"]["alex"]["net"]) == Decimal("33500.00")
    assert Decimal(body["totals"]["alexa"]["net"]) == Decimal("33500.00")
    assert Decimal(body["totals"]["kids"]["net"]) == Decimal("0.00")


def test_dashboard_response_contains_per_account_breakdown(client, db_session, mock_fx):
    _seed_personal(db_session)
    body = client.get("/api/net-worth").json()
    accounts = body["accounts"]
    # All 19 personal accounts appear, even those without snapshots.
    # The 19th — PennyMac Escrow — landed in alembic j2a3b4c5d6e7
    # alongside the people / ownerships refactor; this assertion was
    # stale at 18 from before that migration shipped.
    assert len(accounts) == 19
    by_name = {a["name"]: a for a in accounts}
    house = by_name["US House"]
    assert house["kind"] == "property"
    assert house["is_liability"] is False
    assert Decimal(house["latest_balance_native"]) == Decimal("299000.00")
    assert house["fx_source"] == "identity"


# --- FX conversion + caching ----------------------------------------------

def test_eur_account_converts_to_home_usd_via_live_rate(client, db_session, mock_fx):
    _seed_personal(db_session)
    mock_fx["rates"][("EUR", "USD")] = Decimal("1.10")
    from app.models.accounts import Account
    revolut_ie = db_session.query(Account).filter_by(name="Revolut IE").first()
    _add_snapshot(client, revolut_ie.id, "1000.00")  # 1000 EUR (account is EUR)

    body = client.get("/api/net-worth").json()
    by_name = {a["name"]: a for a in body["accounts"]}
    revolut = by_name["Revolut IE"]
    assert Decimal(revolut["latest_balance_native"]) == Decimal("1000.00")
    assert Decimal(revolut["balance_in_home_currency"]) == Decimal("1100.00")
    assert revolut["fx_source"] == "bankofcanada-direct"


def test_fx_rates_are_cached_per_request(client, db_session, mock_fx):
    """Multiple EUR accounts → one BoC call for EUR/USD, not N calls."""
    _seed_personal(db_session)
    mock_fx["rates"][("EUR", "USD")] = Decimal("1.10")
    from app.models.accounts import Account
    eur_account_names = ["Revolut IE", "Bank of Ireland", "Capital Credit Union"]
    for name in eur_account_names:
        a = db_session.query(Account).filter_by(name=name).first()
        _add_snapshot(client, a.id, "500.00")

    mock_fx["calls"].clear()
    client.get("/api/net-worth")
    eur_usd_calls = [c for c in mock_fx["calls"] if c == ("EUR", "USD")]
    assert len(eur_usd_calls) == 1, (
        f"Expected EUR->USD to be looked up exactly once across the dashboard "
        f"render; got {len(eur_usd_calls)} calls. Cache is broken."
    )


def test_fx_fallback_to_hardcoded_when_live_unavailable(client, db_session, mock_fx):
    """fx_service returns rate=None → use hardcoded USD/EUR=1.08 and
    surface the fallback in fx_status."""
    _seed_personal(db_session)
    # Don't populate mock_fx['rates'] for EUR/USD — simulates BoC failure.
    from app.models.accounts import Account
    revolut_ie = db_session.query(Account).filter_by(name="Revolut IE").first()
    _add_snapshot(client, revolut_ie.id, "1000.00")

    body = client.get("/api/net-worth").json()
    by_name = {a["name"]: a for a in body["accounts"]}
    assert by_name["Revolut IE"]["fx_source"] == "hardcoded-fallback"
    # 1000 EUR * 1.080 = 1080 USD
    assert Decimal(by_name["Revolut IE"]["balance_in_home_currency"]) == Decimal("1080.00")
    # fx_status reports mixed (because identity USD->USD pairs are also
    # in play) or fallback (if all FX accounts fell back).
    assert body["fx_status"] in ("fallback", "mixed")


def test_fx_unsupported_pair_falls_back_to_identity_with_warning(
    client, db_session, mock_fx,
):
    """A currency we don't have a hardcoded fallback for (e.g. GBP)
    falls back to rate=1.0 with a loud fx_warning so the user
    notices the affected account is misvalued."""
    _seed_personal(db_session)
    from app.models.accounts import Account
    # Force an unusual currency on an existing account.
    revolut_ie = db_session.query(Account).filter_by(name="Revolut IE").first()
    revolut_ie.currency = "GBP"
    db_session.commit()
    _add_snapshot(client, revolut_ie.id, "1000.00", currency="GBP")

    body = client.get("/api/net-worth").json()
    by_name = {a["name"]: a for a in body["accounts"]}
    assert by_name["Revolut IE"]["fx_source"] == "identity-fallback"
    # No hardcoded GBP/USD → identity (1.0) → 1000 USD
    assert Decimal(by_name["Revolut IE"]["balance_in_home_currency"]) == Decimal("1000.00")
    assert any("Revolut IE" in w and "GBP->USD" in w for w in body["fx_warnings"])


# --- Liability sign convention ---------------------------------------------

def test_credit_card_balance_subtracts_from_net_worth(
    client, db_session, mock_fx,
):
    _seed_personal(db_session)
    from app.models.accounts import Account
    chase = db_session.query(Account).filter_by(name="Chase United Explorer").first()
    _add_snapshot(client, chase.id, "1500.00")

    body = client.get("/api/net-worth").json()
    by_name = {a["name"]: a for a in body["accounts"]}
    chase_row = by_name["Chase United Explorer"]
    assert chase_row["is_liability"] is True
    # Native balance is the positive 1500 the user entered; signed (for
    # totals math) is -1500.
    assert Decimal(chase_row["latest_balance_native"]) == Decimal("1500.00")
    assert Decimal(chase_row["signed_balance_home"]) == Decimal("-1500.00")
    # Each owner -> -750 contribution.
    assert Decimal(chase_row["contributions"]["alex"]) == Decimal("-750.00")
    assert Decimal(chase_row["contributions"]["alexa"]) == Decimal("-750.00")


def test_loan_balance_subtracts_via_kind_loan(client, db_session, mock_fx):
    """Pinned by the seed which puts US Mortgage at 232000 — net for
    each owner should drop by 116000 from that loan alone."""
    _seed_personal(db_session)
    body = client.get("/api/net-worth").json()
    # Just the seed: house +299000, mortgage -232000.
    # Alex: 50% of (299000 - 232000) = 33500.
    assert Decimal(body["totals"]["alex"]["net"]) == Decimal("33500.00")
    by_name = {a["name"]: a for a in body["accounts"]}
    mortgage = by_name["US Mortgage (PennyMac)"]
    assert mortgage["is_liability"] is True
    assert Decimal(mortgage["signed_balance_home"]) == Decimal("-232000.00")


# --- Slice splits ----------------------------------------------------------

def test_kids_only_account_contributes_only_to_kids_slice(
    client, db_session, mock_fx,
):
    _seed_personal(db_session)
    from app.models.accounts import Account
    son = db_session.query(Account).filter_by(name="Heartland Savings (son)").first()
    _add_snapshot(client, son.id, "5000.00")

    body = client.get("/api/net-worth").json()
    # Kids' net should reflect this 5000 PLUS any other kids-owned
    # account contributions. With seed alone, no other accounts have
    # kids ownership, so kids = 5000.
    assert Decimal(body["totals"]["kids"]["net"]) == Decimal("5000.00")
    by_name = {a["name"]: a for a in body["accounts"]}
    son_row = by_name["Heartland Savings (son)"]
    assert Decimal(son_row["contributions"]["alex"]) == Decimal("0.00")
    assert Decimal(son_row["contributions"]["alexa"]) == Decimal("0.00")
    assert Decimal(son_row["contributions"]["kids"]) == Decimal("5000.00")


def test_household_total_equals_sum_of_three_slices(client, db_session, mock_fx):
    """For any combination of accounts, the household net should equal
    alex + alexa + kids since ownership pcts always sum to 100."""
    _seed_personal(db_session)
    mock_fx["rates"][("EUR", "USD")] = Decimal("1.10")
    from app.models.accounts import Account

    # Mix of currencies, kinds, and ownership.
    cks = db_session.query(Account).filter_by(name="Heartland Joint Checking").first()
    revolut_us = db_session.query(Account).filter_by(name="Revolut US").first()
    vest = db_session.query(Account).filter_by(name="Vestwell 401k").first()
    boi = db_session.query(Account).filter_by(name="Bank of Ireland").first()
    chase = db_session.query(Account).filter_by(name="Chase United Explorer").first()
    _add_snapshot(client, cks.id, "10000")
    _add_snapshot(client, revolut_us.id, "2500")
    _add_snapshot(client, vest.id, "75000")
    _add_snapshot(client, boi.id, "8000")  # EUR
    _add_snapshot(client, chase.id, "3200")  # CC, liability

    body = client.get("/api/net-worth").json()
    h_net = Decimal(body["totals"]["household"]["net"])
    sum_slices = (
        Decimal(body["totals"]["alex"]["net"])
        + Decimal(body["totals"]["alexa"]["net"])
        + Decimal(body["totals"]["kids"]["net"])
    )
    assert h_net == sum_slices, (
        f"household net {h_net} != sum of slices {sum_slices}; "
        f"ownership pcts must sum to 100 for every account but the "
        f"three slices should always reconcile to household total."
    )


# --- Empty / no-snapshot accounts -----------------------------------------

def test_account_with_no_snapshot_appears_with_null_fields(
    client, db_session, mock_fx,
):
    _seed_personal(db_session)
    body = client.get("/api/net-worth").json()
    by_name = {a["name"]: a for a in body["accounts"]}
    revolut = by_name["Revolut IE"]
    assert revolut["latest_balance_native"] is None
    assert revolut["latest_balance_as_of"] is None
    assert revolut["balance_in_home_currency"] is None
    # Contributions are null per-slice rather than 0 (which would
    # incorrectly show as a real zero contribution to the dashboard).
    assert revolut["contributions"]["alex"] is None


def test_dashboard_with_zero_personal_accounts_returns_zero_totals(
    client, db_session, mock_fx,
):
    """If the seed hasn't been run, the dashboard returns sensible zero
    totals rather than crashing."""
    body = client.get("/api/net-worth").json()
    assert Decimal(body["totals"]["household"]["net"]) == Decimal("0")
    assert body["accounts"] == []
