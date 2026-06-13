"""Phase 1, Task 1C — HTTP-level tests for the two new loan endpoints.

  POST /api/loans/{id}/project-forward
  GET  /api/loans/{id}/home-equity

Engine math is unit-tested in `test_amortization_service.py`; this file
covers the wiring, validation, fallback behaviour, and end-to-end DB
side effects against the personal-accounts seed (US Mortgage / US House /
PennyMac Escrow).
"""
from datetime import date
from decimal import Decimal


# Mirror the helper used by the existing test_loans_api file.
def _seed_personal(db_session):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import seed_personal_accounts as seed_module
    seed_module.apply_seed(db_session, today=date(2026, 5, 4))
    db_session.commit()


def _get_mortgage_loan_id(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    mortgage = db_session.query(Account).filter_by(name="US Mortgage (PennyMac)").first()
    r = client.get(f"/api/loans/by-account/{mortgage.id}")
    return r.json()["id"]


# ---------------------------------------------------------------------------
# POST /api/loans/{id}/project-forward
# ---------------------------------------------------------------------------

def test_project_forward_pennymac_current_state(client, db_session):
    """Work-order acceptance scenario end-to-end: post the current PennyMac
    figures, expect ~340–355 rows written, final balance ≈ $0."""
    loan_id = _get_mortgage_loan_id(client, db_session)
    r = client.post(f"/api/loans/{loan_id}/project-forward", json={
        "current_principal": "232058.65",
        "interest_rate_pct": "6.99",
        "monthly_payment": "2013.14",
        "escrow_amount": "462.62",
        "next_payment_date": "2026-07-01",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert 340 <= body["rows_generated"] <= 355
    assert body["first_payment_date"] == "2026-07-01"
    assert Decimal(body["final_remaining_balance"]) == Decimal("0.00")

    # And the rows really landed in the DB.
    from app.models.loans import LoanAmortizationSchedule
    n = db_session.query(LoanAmortizationSchedule).filter_by(loan_id=loan_id).count()
    assert n == body["rows_generated"]


def test_project_forward_respects_explicit_remaining_months(client, db_session):
    """Pin the term (e.g. matching an Irish stated term) rather than solve."""
    loan_id = _get_mortgage_loan_id(client, db_session)
    r = client.post(f"/api/loans/{loan_id}/project-forward", json={
        "current_principal": "50000",
        "interest_rate_pct": "4.5",
        "monthly_payment": "700",
        "next_payment_date": "2026-06-01",
        "remaining_months": 84,
    })
    assert r.status_code == 200
    assert r.json()["rows_generated"] == 84


def test_project_forward_replaces_existing_schedule(client, db_session):
    """Calling project-forward twice replaces — never appends."""
    loan_id = _get_mortgage_loan_id(client, db_session)
    base = {
        "current_principal": "100000",
        "interest_rate_pct": "5",
        "monthly_payment": "500",
        "next_payment_date": "2026-01-01",
    }
    r1 = client.post(f"/api/loans/{loan_id}/project-forward", json=base)
    n1 = r1.json()["rows_generated"]
    r2 = client.post(f"/api/loans/{loan_id}/project-forward",
                     json={**base, "current_principal": "50000"})
    n2 = r2.json()["rows_generated"]
    assert n1 > n2  # smaller balance → fewer rows
    from app.models.loans import LoanAmortizationSchedule
    final_count = db_session.query(LoanAmortizationSchedule).filter_by(loan_id=loan_id).count()
    assert final_count == n2  # replaced, not appended


def test_project_forward_unknown_loan_returns_404(client):
    r = client.post("/api/loans/99999/project-forward", json={
        "current_principal": "1000", "interest_rate_pct": "5",
        "monthly_payment": "100", "next_payment_date": "2026-01-01",
    })
    assert r.status_code == 404


def test_project_forward_underwater_payment_returns_422(client, db_session):
    """Payment can't cover interest → engine raises, route returns 422."""
    loan_id = _get_mortgage_loan_id(client, db_session)
    r = client.post(f"/api/loans/{loan_id}/project-forward", json={
        "current_principal": "232058.65",
        "interest_rate_pct": "6.99",
        "monthly_payment": "100",   # less than monthly interest accrual
        "next_payment_date": "2026-07-01",
    })
    assert r.status_code == 422
    assert "never amortize" in r.text


# ---------------------------------------------------------------------------
# GET /api/loans/{id}/home-equity
# ---------------------------------------------------------------------------

def test_home_equity_from_snapshots(client, db_session):
    """Both property and mortgage have snapshots → snapshot source."""
    loan_id = _get_mortgage_loan_id(client, db_session)
    from app.models.accounts import Account
    house = db_session.query(Account).filter_by(name="US House").first()
    mortgage = db_session.query(Account).filter_by(name="US Mortgage (PennyMac)").first()

    # Override the seed-time snapshot with a current value for the house.
    client.post("/api/balances", json={
        "account_id": house.id, "as_of_date": "2026-06-01", "balance": "335000.00",
    })
    # And a recent mortgage snapshot.
    client.post("/api/balances", json={
        "account_id": mortgage.id, "as_of_date": "2026-06-01", "balance": "232058.65",
    })

    r = client.get(f"/api/loans/{loan_id}/home-equity")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["currency"] == "USD"
    assert Decimal(body["property_value"]) == Decimal("335000.00")
    assert Decimal(body["mortgage_balance"]) == Decimal("232058.65")
    assert Decimal(body["equity"]) == Decimal("102941.35")
    assert body["mortgage_source"] == "snapshot"
    assert body["property_account_name"] == "US House"


def test_home_equity_falls_back_to_schedule_when_no_mortgage_snapshot(client, db_session):
    """No mortgage snapshot → take the most recent schedule row's balance."""
    loan_id = _get_mortgage_loan_id(client, db_session)
    from app.models.accounts import Account
    from app.models.balance_snapshots import BalanceSnapshot
    mortgage = db_session.query(Account).filter_by(name="US Mortgage (PennyMac)").first()

    # Wipe any seeded snapshot on the mortgage so the schedule fallback fires.
    db_session.query(BalanceSnapshot).filter_by(account_id=mortgage.id).delete()
    db_session.commit()

    # Project a schedule first so the fallback has something to read.
    client.post(f"/api/loans/{loan_id}/project-forward", json={
        "current_principal": "232058.65", "interest_rate_pct": "6.99",
        "monthly_payment": "2013.14", "escrow_amount": "462.62",
        "next_payment_date": "2026-07-01",
    })

    r = client.get(f"/api/loans/{loan_id}/home-equity")
    body = r.json()
    assert body["mortgage_source"] == "schedule"
    # The fallback is the LAST row of the schedule (final $0), which is
    # technically wrong as an "as-of today" view but is the documented
    # fallback — UI should prefer snapshots. Just assert the contract.
    assert Decimal(body["mortgage_balance"]) == Decimal("0.00")


def test_home_equity_returns_null_property_value_when_no_snapshot(client, db_session):
    """No property snapshot → property_value=null, equity=null. The UI is
    expected to prompt the user to enter a value via Balance Entry."""
    loan_id = _get_mortgage_loan_id(client, db_session)
    from app.models.accounts import Account
    from app.models.balance_snapshots import BalanceSnapshot
    house = db_session.query(Account).filter_by(name="US House").first()
    db_session.query(BalanceSnapshot).filter_by(account_id=house.id).delete()
    db_session.commit()

    r = client.get(f"/api/loans/{loan_id}/home-equity")
    body = r.json()
    assert body["property_value"] is None
    assert body["equity"] is None
    # Mortgage side still resolves (either snapshot or fallback).
    assert body["mortgage_balance"] is not None


def test_home_equity_unknown_loan_returns_404(client):
    r = client.get("/api/loans/99999/home-equity")
    assert r.status_code == 404


def test_home_equity_returns_partial_200_when_no_asset_account_linked(
    client, db_session,
):
    """No `loan.asset_account_id` (e.g. a fresh install or MBC-template
    use) must return a 200 with null property fields, not a 422 the
    UI then has to special-case."""
    loan_id = _get_mortgage_loan_id(client, db_session)
    from app.models.loans import Loan
    loan = db_session.query(Loan).filter_by(id=loan_id).first()
    loan.asset_account_id = None
    db_session.commit()

    r = client.get(f"/api/loans/{loan_id}/home-equity")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["property_account_id"] is None
    assert body["property_account_name"] is None
    assert body["property_value"] is None
    assert body["property_as_of"] is None
    assert body["equity"] is None
    # Mortgage side still resolves.
    assert body["mortgage_balance"] is not None
    assert body["mortgage_source"] in ("snapshot", "schedule", "loan.original_amount")
