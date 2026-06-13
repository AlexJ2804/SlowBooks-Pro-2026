"""Pure-function tests for the amortization engine (Phase 1, Task 1C).

Covers:
  * compute_amortization — the from-origination engine (existing behaviour
    used by /generate-schedule; smoke-tested separately in test_loans_api.py
    so this file focuses on the new forward-projection paths)
  * project_forward     — forward-from-current-state variant
  * _solve_remaining_months — the term solver
  * add_months          — date math

The work-order acceptance scenario (PennyMac loan 8215172702, principal
$232,058.65, P&I $1,550.52, rate ~6.99%) is asserted: term should solve to
~340–355 payments and the balance must amortize to ~$0.
"""
from datetime import date
from decimal import Decimal

import pytest

from app.services.amortization import (
    add_months,
    compute_amortization,
    project_forward,
    _solve_remaining_months,
)


# ---------------------------------------------------------------------------
# Engine sanity (textbook 30yr / 6.5%) — same fixture the existing
# test_loans_api covers, repeated here so a regression here surfaces in the
# service-test file too.
# ---------------------------------------------------------------------------

def test_engine_first_payment_split_for_30yr_6_5_pct():
    rows = compute_amortization(
        original_amount=Decimal("240000"),
        interest_rate_pct=Decimal("6.5"),
        term_months=360,
        start_date=date(2026, 1, 1),
        monthly_payment=Decimal("1516.96"),
        escrow_amount=Decimal("0"),
    )
    assert len(rows) == 360
    first = rows[0]
    assert first["interest_amount"] == Decimal("1300.00")
    assert first["principal_amount"] == Decimal("216.96")
    assert first["remaining_balance"] == Decimal("239783.04")


def test_engine_zero_apr_handled():
    rows = compute_amortization(
        original_amount=Decimal("12000"),
        interest_rate_pct=Decimal("0"),
        term_months=12,
        start_date=date(2026, 1, 1),
        monthly_payment=Decimal("1000"),
        escrow_amount=Decimal("0"),
    )
    for r in rows:
        assert r["interest_amount"] == Decimal("0")
    assert rows[-1]["remaining_balance"] == Decimal("0")


def test_engine_final_balance_lands_at_zero_via_principal_nudge():
    """Last row absorbs sub-cent drift from quantizing monthly_payment."""
    rows = compute_amortization(
        original_amount=Decimal("100000"),
        interest_rate_pct=Decimal("5"),
        term_months=180,
        start_date=date(2026, 1, 1),
        monthly_payment=Decimal("790.79"),
        escrow_amount=Decimal("0"),
    )
    assert rows[-1]["remaining_balance"] == Decimal("0.00")


def test_engine_separates_escrow_from_principal():
    """monthly_payment includes escrow; principal = pmt - escrow - interest."""
    rows = compute_amortization(
        original_amount=Decimal("240000"),
        interest_rate_pct=Decimal("6.5"),
        term_months=360,
        start_date=date(2026, 1, 1),
        monthly_payment=Decimal("1916.96"),    # 1516.96 P&I + 400 escrow
        escrow_amount=Decimal("400"),
    )
    first = rows[0]
    assert first["escrow_amount"] == Decimal("400")
    # P&I part should match the no-escrow case: 1300 / 216.96
    assert first["interest_amount"] == Decimal("1300.00")
    assert first["principal_amount"] == Decimal("216.96")


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------

def test_solver_30yr_6_5_pct():
    """A fresh 30-year loan at 6.5% APR should resolve to 360 months."""
    n = _solve_remaining_months(
        current_principal=Decimal("240000"),
        interest_rate_pct=Decimal("6.5"),
        monthly_payment=Decimal("1516.96"),
        escrow_amount=Decimal("0"),
    )
    # Computed payment is approximate; tolerate ±2 (one extra "stub" payment).
    assert 358 <= n <= 362


def test_solver_zero_apr():
    n = _solve_remaining_months(
        current_principal=Decimal("12000"),
        interest_rate_pct=Decimal("0"),
        monthly_payment=Decimal("1000"),
        escrow_amount=Decimal("0"),
    )
    assert n == 12


def test_solver_rejects_payment_under_interest():
    """A $100 payment can't service interest on $240k at 6.5% → ValueError."""
    with pytest.raises(ValueError, match="never amortize"):
        _solve_remaining_months(
            current_principal=Decimal("240000"),
            interest_rate_pct=Decimal("6.5"),
            monthly_payment=Decimal("100"),
            escrow_amount=Decimal("0"),
        )


def test_solver_rejects_negative_pi():
    """Escrow > monthly_payment → ValueError instead of div-by-zero math."""
    with pytest.raises(ValueError, match="must be > 0"):
        _solve_remaining_months(
            current_principal=Decimal("1000"),
            interest_rate_pct=Decimal("5"),
            monthly_payment=Decimal("100"),
            escrow_amount=Decimal("200"),
        )


# ---------------------------------------------------------------------------
# project_forward — the new path
# ---------------------------------------------------------------------------

def test_project_forward_pennymac_current_state():
    """Work-order acceptance scenario.

    PennyMac loan 8215172702:
      principal   $232,058.65
      P&I         $1,550.52
      escrow      $462.62
      rate        ~6.99% APR

    Spec says: ~340–355 remaining payments, balance amortizes to ~0.
    """
    rows = project_forward(
        current_principal=Decimal("232058.65"),
        interest_rate_pct=Decimal("6.99"),
        monthly_payment=Decimal("2013.14"),
        escrow_amount=Decimal("462.62"),
        next_payment_date=date(2026, 7, 1),
    )
    assert 340 <= len(rows) <= 355
    # First period interest: 232058.65 * (6.99/12/100) ≈ 1351.74
    first_interest = rows[0]["interest_amount"]
    assert Decimal("1350.00") <= first_interest <= Decimal("1355.00")
    # P&I check: principal + interest should equal monthly_payment - escrow
    pi = rows[0]["principal_amount"] + rows[0]["interest_amount"]
    assert pi == Decimal("1550.52")
    # Final row balance lands at exactly zero (the nudge).
    assert rows[-1]["remaining_balance"] == Decimal("0.00")
    # Each row carries the escrow figure verbatim.
    assert all(r["escrow_amount"] == Decimal("462.62") for r in rows)


def test_project_forward_starts_at_payment_number_1():
    """Forward projection numbers payments 1..N for the projection window
    (not a continuation of historical payment_number)."""
    rows = project_forward(
        current_principal=Decimal("10000"),
        interest_rate_pct=Decimal("5"),
        monthly_payment=Decimal("500"),
        escrow_amount=Decimal("0"),
        next_payment_date=date(2026, 1, 1),
    )
    assert rows[0]["payment_number"] == 1
    assert rows[0]["payment_date"] == date(2026, 1, 1)


def test_project_forward_honors_explicit_remaining_months():
    """If caller knows the term (Irish-style), pin it instead of solving."""
    rows = project_forward(
        current_principal=Decimal("50000"),
        interest_rate_pct=Decimal("4.5"),
        monthly_payment=Decimal("700"),
        escrow_amount=Decimal("0"),
        next_payment_date=date(2026, 6, 1),
        remaining_months=84,
    )
    assert len(rows) == 84
    # Last row absorbs drift either way.
    assert rows[-1]["remaining_balance"] == Decimal("0.00")


def test_project_forward_propagates_solver_errors_as_value_error():
    with pytest.raises(ValueError):
        project_forward(
            current_principal=Decimal("100000"),
            interest_rate_pct=Decimal("5"),
            monthly_payment=Decimal("100"),
            escrow_amount=Decimal("0"),
            next_payment_date=date(2026, 1, 1),
        )


# ---------------------------------------------------------------------------
# Date math
# ---------------------------------------------------------------------------

def test_add_months_clamps_end_of_month():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)   # leap
    assert add_months(date(2026, 3, 31), 1) == date(2026, 4, 30)
    assert add_months(date(2026, 12, 15), 2) == date(2027, 2, 15)


def test_add_months_identity_for_zero():
    assert add_months(date(2026, 6, 13), 0) == date(2026, 6, 13)
