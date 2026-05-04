"""Tests for scripts/seed_personal_accounts.py.

Pins:
- Idempotency: re-running the seed creates zero new rows the second time.
- The exact 18-account roster the spec calls for, with correct
  ownership splits, currencies, kinds, and update strategies.
- Initial balance snapshots only exist for property + loan.
- Mortgage loan row is created with the documented placeholder values
  but the amortization schedule stays empty (spec: regenerate via UI
  after the user enters real values).
"""

import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

# scripts/ isn't on the import path by default — add the repo root.
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))
sys.path.insert(0, str(_REPO_ROOT / "scripts"))

import seed_personal_accounts as seed_module  # noqa: E402


from app.models.accounts import Account, AccountType
from app.models.balance_snapshots import BalanceSnapshot
from app.models.loans import Loan, LoanAmortizationSchedule


_FROZEN_TODAY = date(2026, 5, 4)


def test_seed_creates_18_accounts_with_correct_ownership(db_session):
    counts = seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()

    assert counts["accounts_created"] == 18, counts
    assert counts["accounts_skipped"] == 0

    accounts = db_session.query(Account).filter(Account.is_system == False).all()
    by_name = {a.name: a for a in accounts}

    # Spot-check one account from each kind to pin schema mapping.
    cks = by_name["Heartland Joint Checking"]
    assert cks.account_type == AccountType.ASSET
    assert cks.account_kind == "bank"
    assert cks.update_strategy == "transactional"
    assert cks.currency == "USD"
    assert (cks.alex_pct, cks.alexa_pct, cks.kids_pct) == (50, 50, 0)

    revolut_ie = by_name["Revolut IE"]
    assert revolut_ie.currency == "EUR"
    assert (revolut_ie.alex_pct, revolut_ie.alexa_pct, revolut_ie.kids_pct) == (100, 0, 0)

    cc = by_name["Chase United Explorer"]
    assert cc.account_type == AccountType.LIABILITY
    assert cc.account_kind == "credit_card"

    vg_kids = by_name["Vanguard (kids)"]
    assert vg_kids.account_kind == "brokerage"
    assert vg_kids.update_strategy == "balance_only"
    assert (vg_kids.alex_pct, vg_kids.alexa_pct, vg_kids.kids_pct) == (0, 0, 100)

    irl = by_name["Irish Life PRSA"]
    assert irl.account_kind == "retirement"
    assert irl.currency == "EUR"

    house = by_name["US House"]
    assert house.account_kind == "property"
    assert house.account_type == AccountType.ASSET

    mortgage = by_name["US Mortgage (PennyMac)"]
    assert mortgage.account_kind == "loan"
    assert mortgage.account_type == AccountType.LIABILITY


def test_seed_initial_snapshots_property_and_loan_only(db_session):
    seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()

    snapshots = db_session.query(BalanceSnapshot).all()
    assert len(snapshots) == 2

    by_account_name = {s.account.name: s for s in snapshots}
    assert by_account_name["US House"].balance == Decimal("299000.00")
    assert by_account_name["US House"].currency == "USD"
    assert by_account_name["US House"].as_of_date == _FROZEN_TODAY

    assert by_account_name["US Mortgage (PennyMac)"].balance == Decimal("232000.00")
    assert by_account_name["US Mortgage (PennyMac)"].currency == "USD"


def test_seed_mortgage_loan_row_with_placeholder_values_no_schedule(db_session):
    seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()

    loans = db_session.query(Loan).all()
    assert len(loans) == 1
    loan = loans[0]
    assert loan.account.name == "US Mortgage (PennyMac)"
    assert loan.asset_account.name == "US House"
    assert loan.original_amount == Decimal("240000.00")
    assert loan.interest_rate == Decimal("6.5000")
    assert loan.term_months == 360
    assert loan.start_date == date(2022, 1, 1)
    assert loan.monthly_payment == Decimal("2100.00")
    assert loan.escrow_amount == Decimal("400.00")
    assert loan.currency == "USD"

    # Spec: schedule stays empty until the user clicks "Generate schedule"
    # in the UI after editing the placeholder values to match a real
    # PennyMac statement.
    schedule_rows = db_session.query(LoanAmortizationSchedule).all()
    assert schedule_rows == []


def test_seed_is_idempotent_on_re_run(db_session):
    """Re-running the seed against the same DB creates zero new rows.
    Pinned because the bootstrap shell flow involves dropping into psql
    and re-running this script multiple times during account-roster
    refinement before the dashboard is finalised."""
    first = seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()
    assert first["accounts_created"] == 18
    assert first["snapshots_created"] == 2
    assert first["loans_created"] == 1

    second = seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()
    assert second["accounts_created"] == 0, second
    assert second["accounts_skipped"] == 18
    assert second["snapshots_created"] == 0
    assert second["snapshots_skipped"] == 2
    assert second["loans_created"] == 0
    assert second["loans_skipped"] == 1

    # And the totals on disk haven't doubled.
    assert db_session.query(Account).filter(Account.is_system == False).count() == 18
    assert db_session.query(BalanceSnapshot).count() == 2
    assert db_session.query(Loan).count() == 1


def test_seed_ownership_pcts_each_account_sums_to_100(db_session):
    """Every personal account must have ownership pcts summing to exactly
    100 — the CHECK constraint allows 0/0/0 for system COA rows but the
    seed script should never produce one."""
    seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()

    for a in db_session.query(Account).filter(Account.is_system == False).all():
        total = a.alex_pct + a.alexa_pct + a.kids_pct
        assert total == 100, f"{a.name}: ownership pcts sum to {total}, not 100"
