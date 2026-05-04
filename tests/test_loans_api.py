"""Loans API + amortization computation tests."""

from datetime import date
from decimal import Decimal

from app.routes.loans import _compute_amortization, _add_months


# --- amortization helper unit tests ---------------------------------------

def test_amortization_first_payment_split_for_30yr_at_6_5pct():
    """Sanity check the standard mortgage formula. $240,000 at 6.5% APR
    should split a ~$1516.96 P&I payment into ~$1300 interest /
    ~$216.96 principal in month 1. We use the user's monthly_payment
    field for the total payment (incl. escrow) so test inputs include
    escrow=0 to compare against a pure P&I figure."""
    rows = _compute_amortization(
        original_amount=Decimal("240000"),
        interest_rate_pct=Decimal("6.5"),
        term_months=360,
        start_date=date(2026, 1, 1),
        monthly_payment=Decimal("1516.96"),
        escrow_amount=Decimal("0"),
    )
    assert len(rows) == 360
    first = rows[0]
    assert first["payment_number"] == 1
    assert first["payment_date"] == date(2026, 1, 1)
    # Interest = 240000 * 0.065/12 = 1300.00 exactly.
    assert first["interest_amount"] == Decimal("1300.00")
    assert first["principal_amount"] == Decimal("216.96")
    assert first["remaining_balance"] == Decimal("239783.04")


def test_amortization_zero_apr_handled():
    """0% APR is unusual but legal. Interest is zero every month."""
    rows = _compute_amortization(
        original_amount=Decimal("12000"),
        interest_rate_pct=Decimal("0"),
        term_months=12,
        start_date=date(2026, 1, 1),
        monthly_payment=Decimal("1000"),
        escrow_amount=Decimal("0"),
    )
    assert len(rows) == 12
    for r in rows:
        assert r["interest_amount"] == Decimal("0")
    assert rows[-1]["remaining_balance"] == Decimal("0")


def test_amortization_final_balance_lands_at_zero():
    """The last period's principal is adjusted so remaining_balance ends
    exactly at zero, absorbing rounding drift from the monthly payment."""
    rows = _compute_amortization(
        original_amount=Decimal("100000"),
        interest_rate_pct=Decimal("5"),
        term_months=180,
        start_date=date(2026, 1, 1),
        monthly_payment=Decimal("790.79"),  # close to standard P&I
        escrow_amount=Decimal("0"),
    )
    assert rows[-1]["remaining_balance"] == Decimal("0.00")


def test_amortization_includes_escrow_unchanged_in_each_row():
    rows = _compute_amortization(
        original_amount=Decimal("240000"),
        interest_rate_pct=Decimal("6.5"),
        term_months=360,
        start_date=date(2026, 1, 1),
        monthly_payment=Decimal("2100"),
        escrow_amount=Decimal("400"),
    )
    for r in rows:
        assert r["escrow_amount"] == Decimal("400")


def test_add_months_handles_end_of_month_clamping():
    # Jan 31 + 1 month → Feb 28 (or Feb 29 in leap years)
    assert _add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    # Jan 31 + 1 month in 2024 (leap) → Feb 29
    assert _add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)
    # March 31 + 1 → April 30
    assert _add_months(date(2026, 3, 31), 1) == date(2026, 4, 30)
    # Crossing year
    assert _add_months(date(2026, 12, 15), 2) == date(2027, 2, 15)


# --- API tests ------------------------------------------------------------

def _seed_personal(db_session):
    """Apply the personal-accounts seed against the test session."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import seed_personal_accounts as seed_module
    seed_module.apply_seed(db_session, today=date(2026, 5, 4))
    db_session.commit()


def test_get_loan_by_account_after_seed(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    mortgage = db_session.query(Account).filter_by(name="US Mortgage (PennyMac)").first()

    r = client.get(f"/api/loans/by-account/{mortgage.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["account_name"] == "US Mortgage (PennyMac)"
    assert body["asset_account_name"] == "US House"
    assert Decimal(body["original_amount"]) == Decimal("240000.00")
    assert Decimal(body["interest_rate"]) == Decimal("6.5000")
    assert body["term_months"] == 360
    assert body["currency"] == "USD"
    # Spec: schedule starts empty.
    assert body["schedule_row_count"] == 0


def test_update_loan_changes_persisted(client, db_session):
    _seed_personal(db_session)
    from app.models.accounts import Account
    from app.models.loans import Loan
    mortgage = db_session.query(Account).filter_by(name="US Mortgage (PennyMac)").first()
    loan = db_session.query(Loan).filter_by(account_id=mortgage.id).first()

    r = client.put(f"/api/loans/{loan.id}", json={
        "interest_rate": "6.875",
        "monthly_payment": "2155.50",
        "escrow_amount": "425.00",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert Decimal(body["interest_rate"]) == Decimal("6.8750")
    assert Decimal(body["monthly_payment"]) == Decimal("2155.50")
    assert Decimal(body["escrow_amount"]) == Decimal("425.00")
    # Untouched fields preserved.
    assert Decimal(body["original_amount"]) == Decimal("240000.00")


def test_update_loan_rejects_negative_values(client, db_session):
    _seed_personal(db_session)
    from app.models.loans import Loan
    loan = db_session.query(Loan).first()

    r = client.put(f"/api/loans/{loan.id}", json={"interest_rate": "-1"})
    assert r.status_code == 422, r.text


def test_generate_schedule_creates_rows_and_zeros_final_balance(client, db_session):
    _seed_personal(db_session)
    from app.models.loans import Loan
    loan = db_session.query(Loan).first()

    r = client.post(f"/api/loans/{loan.id}/generate-schedule")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["loan_id"] == loan.id
    assert body["rows_generated"] == 360
    # Final period nudges remaining_balance to exactly 0.
    assert Decimal(body["final_remaining_balance"]) == Decimal("0.00")

    # Loan response now reflects the populated schedule.
    r = client.get(f"/api/loans/{loan.id}")
    assert r.status_code == 200
    assert r.json()["schedule_row_count"] == 360


def test_generate_schedule_is_idempotent_replaces_existing_rows(client, db_session):
    _seed_personal(db_session)
    from app.models.loans import Loan, LoanAmortizationSchedule
    loan = db_session.query(Loan).first()

    client.post(f"/api/loans/{loan.id}/generate-schedule")
    first_count = db_session.query(LoanAmortizationSchedule).filter_by(loan_id=loan.id).count()

    # Change a parameter that affects the schedule, then regenerate.
    client.put(f"/api/loans/{loan.id}", json={"term_months": 180})
    r = client.post(f"/api/loans/{loan.id}/generate-schedule")
    assert r.json()["rows_generated"] == 180

    # Final on-disk count matches the new term, no leftover 360-row schedule.
    final_count = db_session.query(LoanAmortizationSchedule).filter_by(loan_id=loan.id).count()
    assert final_count == 180
    assert first_count == 360  # sanity


def test_get_loan_by_unknown_account_returns_404(client, db_session):
    _seed_personal(db_session)
    r = client.get("/api/loans/by-account/9999999")
    assert r.status_code == 404
