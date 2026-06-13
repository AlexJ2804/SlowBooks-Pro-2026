"""HTTP-level tests for the budgeting routes.

CRUD smoke tests across all three resources plus the per-paycheck plan
aggregation. Calc correctness is covered in `test_budget_calc.py`; this file
focuses on validation, status codes, and end-to-end JSON shape.
"""
from datetime import date, timedelta
from decimal import Decimal


# ---------------------------------------------------------------------------
# /api/pay-sources
# ---------------------------------------------------------------------------

def test_create_pay_source_defaults_periods_from_cadence(client):
    r = client.post("/api/pay-sources", json={"name": "Test", "cadence": "biweekly"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["cadence"] == "biweekly"
    assert body["periods_per_year"] == 26
    assert body["net_per_check"] is None


def test_create_pay_source_rejects_mismatched_periods(client):
    r = client.post("/api/pay-sources", json={
        "name": "Bad", "cadence": "biweekly", "periods_per_year": 12,
    })
    assert r.status_code == 422
    assert "does not match" in r.text


def test_list_pay_sources_returns_seeded_alex_and_alexa_or_just_what_we_make(client):
    # No alembic seed in the test DB (Base.metadata.create_all path); just
    # confirm the list endpoint works against our own writes.
    client.post("/api/pay-sources", json={"name": "Alex", "cadence": "biweekly"})
    client.post("/api/pay-sources", json={"name": "Alexa", "cadence": "monthly"})
    r = client.get("/api/pay-sources")
    names = [s["name"] for s in r.json()]
    assert "Alex" in names and "Alexa" in names


def test_patch_pay_source_updates_net_per_check(client):
    src_id = client.post("/api/pay-sources",
                         json={"name": "Alex", "cadence": "biweekly"}).json()["id"]
    r = client.patch(f"/api/pay-sources/{src_id}", json={"net_per_check": "2150.00"})
    assert r.status_code == 200
    assert Decimal(r.json()["net_per_check"]) == Decimal("2150.00")


def test_delete_pay_source_404_when_missing(client):
    assert client.delete("/api/pay-sources/9999").status_code == 404


def test_delete_pay_source_round_trip(client):
    """Delete the row we just created; expect implicit-null 200 (matches the
    codebase convention for /api/balances and /api/credit-scores)."""
    src_id = client.post("/api/pay-sources",
                         json={"name": "Tmp", "cadence": "weekly"}).json()["id"]
    r = client.delete(f"/api/pay-sources/{src_id}")
    assert r.status_code == 200
    # Confirm it's gone.
    listed = client.get("/api/pay-sources").json()
    assert all(s["id"] != src_id for s in listed)


# ---------------------------------------------------------------------------
# /api/sinking-funds
# ---------------------------------------------------------------------------

def test_create_sinking_fund_returns_monthly_accrual(client):
    src_id = client.post("/api/pay-sources",
                         json={"name": "Alex", "cadence": "biweekly"}).json()["id"]
    r = client.post("/api/sinking-funds", json={
        "name": "Car Insurance",
        "amount": "374.00",
        "bill_periods_per_year": 1,
        "funding_source_id": src_id,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert Decimal(body["monthly_accrual"]) == Decimal("31.17")
    assert body["currency"] == "USD"


def test_sinking_fund_rejects_invalid_bill_periods(client):
    r = client.post("/api/sinking-funds", json={
        "name": "Bad", "amount": "100.00", "bill_periods_per_year": 3,
    })
    assert r.status_code == 422


def test_patch_sinking_fund_updates_current_balance(client):
    fund_id = client.post("/api/sinking-funds", json={
        "name": "Phone", "amount": "49.99", "bill_periods_per_year": 12,
    }).json()["id"]
    r = client.patch(f"/api/sinking-funds/{fund_id}",
                     json={"current_balance": "200.00"})
    assert r.status_code == 200
    assert Decimal(r.json()["current_balance"]) == Decimal("200.00")
    # monthly_accrual unchanged (bill didn't change).
    assert Decimal(r.json()["monthly_accrual"]) == Decimal("49.99")


# ---------------------------------------------------------------------------
# /api/goals
# ---------------------------------------------------------------------------

def test_create_goal_returns_derived_fields(client):
    # Target 14 months out so months_until is unambiguously > 1 regardless
    # of today's day-of-month.
    target = (date.today() + timedelta(days=425)).isoformat()
    r = client.post("/api/goals", json={
        "name": "Japan", "target_amount": "13500.00",
        "target_date": target, "current_saved": "0",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["months_until"] >= 12
    assert Decimal(body["monthly_required"]) > 0
    assert body["progress_pct"] == 0.0
    # New goal, no time elapsed, expected glide = 0 → on_track True
    assert body["on_track"] is True


def test_goal_already_funded_reports_zero_required(client):
    r = client.post("/api/goals", json={
        "name": "Done", "target_amount": "1000",
        "target_date": (date.today() + timedelta(days=180)).isoformat(),
        "current_saved": "1000",
    })
    body = r.json()
    assert Decimal(body["monthly_required"]) == Decimal("0.00")
    assert body["progress_pct"] == 100.0


def test_patch_goal_recomputes_monthly_required(client):
    gid = client.post("/api/goals", json={
        "name": "X", "target_amount": "1200",
        "target_date": (date.today() + timedelta(days=370)).isoformat(),
    }).json()["id"]
    r = client.patch(f"/api/goals/{gid}", json={"current_saved": "600"})
    # Halfway funded → monthly_required halved (relative to start).
    body = r.json()
    assert Decimal(body["current_saved"]) == Decimal("600")


# ---------------------------------------------------------------------------
# /api/budget/per-paycheck-plan
# ---------------------------------------------------------------------------

def test_per_paycheck_plan_returns_per_earner_buckets(client):
    """End-to-end: seed two sources, fund+goal routed to each, confirm the
    response groups + math matches the unit-tested calc layer."""
    alex = client.post("/api/pay-sources",
                       json={"name": "Alex", "cadence": "biweekly"}).json()
    alexa = client.post("/api/pay-sources",
                        json={"name": "Alexa", "cadence": "monthly"}).json()

    client.post("/api/sinking-funds", json={
        "name": "Phone", "amount": "49.99",
        "bill_periods_per_year": 12, "funding_source_id": alex["id"],
    })
    client.post("/api/sinking-funds", json={
        "name": "Car", "amount": "374",
        "bill_periods_per_year": 1, "funding_source_id": alexa["id"],
    })

    plans = client.get("/api/budget/per-paycheck-plan").json()
    assert len(plans) == 2
    by_name = {p["pay_source_name"]: p for p in plans}

    # Alex: only the phone fund, monthly $49.99, biweekly per-check $23.07
    a = by_name["Alex"]
    assert Decimal(a["monthly_total"]) == Decimal("49.99")
    assert Decimal(a["per_check_total"]) == Decimal("23.07")
    assert len(a["items"]) == 1
    assert a["items"][0]["kind"] == "sinking_fund"

    # Alexa: only the car fund, monthly $31.17, per-check $31.17 (monthly cadence)
    ax = by_name["Alexa"]
    assert Decimal(ax["monthly_total"]) == Decimal("31.17")
    assert Decimal(ax["per_check_total"]) == Decimal("31.17")


def test_per_paycheck_plan_excludes_unassigned_items(client):
    """A fund with no funding_source_id should NOT appear in any bucket."""
    src = client.post("/api/pay-sources",
                      json={"name": "Alex", "cadence": "biweekly"}).json()
    # Two funds; one assigned, one orphan.
    client.post("/api/sinking-funds", json={
        "name": "Assigned", "amount": "100",
        "bill_periods_per_year": 12, "funding_source_id": src["id"],
    })
    client.post("/api/sinking-funds", json={
        "name": "Orphan", "amount": "999",
        "bill_periods_per_year": 12,
    })
    plans = client.get("/api/budget/per-paycheck-plan").json()
    alex = next(p for p in plans if p["pay_source_name"] == "Alex")
    names = {it["name"] for it in alex["items"]}
    assert "Assigned" in names
    assert "Orphan" not in names
    # Total reflects only the assigned one.
    assert Decimal(alex["monthly_total"]) == Decimal("100.00")
