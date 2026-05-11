"""Tests for scripts/seed_personal_accounts.py.

Pins:
- Idempotency: re-running the seed creates zero new rows the second time.
- The exact 19-account roster (18 phase-1 + PennyMac Escrow added in
  phase 1.5) with correct ownership splits, currencies, kinds, and
  update strategies.
- Initial balance snapshots only exist for property + loan.
- Mortgage loan row is created with the documented placeholder values
  but the amortization schedule stays empty (spec: regenerate via UI
  after the user enters real values).
- Phase 1.5: people directory + account_ownerships join rows are
  populated alongside the legacy alex/alexa/kids columns.
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
from app.models.people import AccountOwnership, Person


_FROZEN_TODAY = date(2026, 5, 4)
_EXPECTED_ACCOUNT_COUNT = 19  # 18 phase-1 + PennyMac Escrow (phase 1.5)


def test_seed_creates_19_accounts_with_correct_ownership(db_session):
    counts = seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()

    assert counts["accounts_created"] == _EXPECTED_ACCOUNT_COUNT, counts
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

    # Phase 1.5 addition — escrow companion to the mortgage.
    escrow = by_name["PennyMac Escrow"]
    assert escrow.account_kind == "bank"
    assert escrow.update_strategy == "balance_only"
    assert escrow.currency == "USD"
    assert escrow.account_type == AccountType.ASSET
    assert (escrow.alex_pct, escrow.alexa_pct, escrow.kids_pct) == (50, 50, 0)


def test_seed_initial_snapshots_property_and_loan_only(db_session):
    seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()

    snapshots = db_session.query(BalanceSnapshot).all()
    # Phase 1.5 spec: PennyMac Escrow gets NO initial snapshot, the
    # user enters that from the next statement. So snapshot count
    # stays at 2 (House + Mortgage).
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
    assert first["accounts_created"] == _EXPECTED_ACCOUNT_COUNT
    assert first["snapshots_created"] == 2
    assert first["loans_created"] == 1
    assert first["people_created"] == 3

    second = seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()
    assert second["accounts_created"] == 0, second
    assert second["accounts_skipped"] == _EXPECTED_ACCOUNT_COUNT
    assert second["snapshots_created"] == 0
    assert second["snapshots_skipped"] == 2
    assert second["loans_created"] == 0
    assert second["loans_skipped"] == 1
    assert second["people_created"] == 0
    assert second["people_skipped"] == 3
    assert second["ownerships_created"] == 0
    # ownership rows skipped count equals the total non-zero pct slots
    # across all 19 accounts. Don't pin the exact number to avoid this
    # test breaking every time the roster grows; just assert > 0.
    assert second["ownerships_skipped"] > 0

    # And the totals on disk haven't doubled.
    assert db_session.query(Account).filter(Account.is_system == False).count() == _EXPECTED_ACCOUNT_COUNT
    assert db_session.query(BalanceSnapshot).count() == 2
    assert db_session.query(Loan).count() == 1
    assert db_session.query(Person).count() == 3


def test_seed_ownership_pcts_each_account_sums_to_100(db_session):
    """Every personal account must have ownership pcts summing to exactly
    100 — the CHECK constraint allows 0/0/0 for system COA rows but the
    seed script should never produce one."""
    seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()

    for a in db_session.query(Account).filter(Account.is_system == False).all():
        total = a.alex_pct + a.alexa_pct + a.kids_pct
        assert total == 100, f"{a.name}: ownership pcts sum to {total}, not 100"


def test_seed_creates_three_people_with_expected_roles(db_session):
    """Phase 1.5: the household roster lives in the people table.
    Pin the seed creates Alex/Alexa/Theodore with the right roles and
    explicit IDs so the join-table mappings stay stable."""
    seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()

    people = db_session.query(Person).order_by(Person.id).all()
    assert [(p.id, p.name, p.role) for p in people] == [
        (1, "Alex",     "parent"),
        (2, "Alexa",    "parent"),
        (3, "Theodore", "child"),
    ]


def test_seed_account_ownerships_mirror_legacy_pct_columns(db_session):
    """For each personal account, the join-table rows reproduce the
    same allocation as the legacy alex_pct/alexa_pct/kids_pct columns.
    This is the central pin on the dual-write seed mapping — when the
    legacy columns get dropped, the join rows are the only source of
    truth, so they must match exactly today."""
    seed_module.apply_seed(db_session, today=_FROZEN_TODAY)
    db_session.commit()

    pct_to_pid = {"alex_pct": 1, "alexa_pct": 2, "kids_pct": 3}

    for acct in db_session.query(Account).filter(Account.is_system == False).all():
        rows = (
            db_session.query(AccountOwnership)
            .filter(AccountOwnership.account_id == acct.id)
            .all()
        )
        rows_by_pid = {r.person_id: r.share_pct for r in rows}
        for col, pid in pct_to_pid.items():
            legacy_pct = getattr(acct, col)
            if legacy_pct > 0:
                assert rows_by_pid.get(pid) == legacy_pct, (
                    f"{acct.name}: {col}={legacy_pct} but join row "
                    f"for person_id={pid} is {rows_by_pid.get(pid)}"
                )
            else:
                assert pid not in rows_by_pid, (
                    f"{acct.name}: {col}=0 but join table has "
                    f"unexpected row for person_id={pid}"
                )
        # Sum of join-table shares equals 100 (system accounts wouldn't
        # be in this loop because is_system filter excludes them).
        assert sum(rows_by_pid.values()) == 100, (
            f"{acct.name}: ownership rows sum to {sum(rows_by_pid.values())}"
        )
