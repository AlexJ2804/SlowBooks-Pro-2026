"""Pure-function tests for app/services/budget_calc.py.

Locks the three acceptance criteria from the work order plus the precision
rule (per_check is derived from unrounded monthly so the spec's $14.38 holds
for $374-annual / biweekly — see the precision-rule docstring in
budget_calc.py).
"""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.budget_calc import (
    build_per_paycheck_plan,
    monthly_accrual,
    monthly_required,
    months_until,
    per_check,
)


# ---------------------------------------------------------------------------
# Lightweight stand-ins for the ORM objects — the calc layer only reads a
# few attributes, so duck-typing with SimpleNamespace keeps these tests
# fixture-free and lets them run without spinning up the DB.
# ---------------------------------------------------------------------------

def _src(**kw):
    """PaySource shim. Defaults to Alex biweekly."""
    return SimpleNamespace(
        id=kw.get("id", 1),
        name=kw.get("name", "Alex"),
        cadence=kw.get("cadence", "biweekly"),
        periods_per_year=kw.get("periods_per_year", 26),
    )


def _fund(**kw):
    return SimpleNamespace(
        id=kw.get("id", 100),
        name=kw.get("name", "Fund"),
        amount=kw.get("amount", Decimal("0")),
        bill_periods_per_year=kw.get("bill_periods_per_year", 12),
        funding_source_id=kw.get("funding_source_id", None),
    )


def _goal(**kw):
    return SimpleNamespace(
        id=kw.get("id", 200),
        name=kw.get("name", "Goal"),
        target_amount=kw.get("target_amount", Decimal("0")),
        current_saved=kw.get("current_saved", Decimal("0")),
        target_date=kw.get("target_date", date(2027, 1, 1)),
        funding_source_id=kw.get("funding_source_id", None),
    )


# ---------------------------------------------------------------------------
# Acceptance fixtures from the work order
# ---------------------------------------------------------------------------

def test_fund_374_annual_biweekly_per_check_is_14_38():
    """Spec: amount=374, bill_periods_per_year=1 → monthly 31.17;
    Alex (biweekly/26) per-check 14.38. Requires unrounded-monthly
    derivation — quantizing monthly first gives 14.39."""
    fund = _fund(amount=Decimal("374"), bill_periods_per_year=1)
    assert monthly_accrual(fund) == Decimal("31.17")
    alex = _src(periods_per_year=26)
    # per_check takes the EXACT monthly; the helper monthly_accrual quantizes.
    # We pass the exact-monthly Decimal here (374*1/12).
    from app.services.budget_calc import _monthly_accrual_exact
    assert per_check(alex, _monthly_accrual_exact(fund)) == Decimal("14.38")


def test_fund_49_99_monthly_biweekly_per_check_is_23_07():
    """Spec: amount=49.99, bill_periods_per_year=12 → monthly 49.99;
    Alex biweekly per-check 23.07."""
    fund = _fund(amount=Decimal("49.99"), bill_periods_per_year=12)
    assert monthly_accrual(fund) == Decimal("49.99")
    alex = _src(periods_per_year=26)
    from app.services.budget_calc import _monthly_accrual_exact
    assert per_check(alex, _monthly_accrual_exact(fund)) == Decimal("23.07")


def test_goal_13500_12_months_monthly_per_check_is_1125():
    """Spec: target=13500, saved=0, target_date 12 months out → monthly
    1125.00; Alexa (monthly/12) per-check 1125.00."""
    today = date(2026, 1, 1)
    goal = _goal(
        target_amount=Decimal("13500"),
        current_saved=Decimal("0"),
        target_date=date(2027, 1, 1),  # exactly 12 months out
    )
    assert monthly_required(goal, today) == Decimal("1125.00")
    alexa = _src(name="Alexa", cadence="monthly", periods_per_year=12)
    from app.services.budget_calc import _monthly_required_exact
    assert per_check(alexa, _monthly_required_exact(goal, today)) == Decimal("1125.00")


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_months_until_same_day_next_month_is_one():
    assert months_until(date(2026, 7, 13), today=date(2026, 6, 13)) == 1


def test_months_until_target_day_before_today_drops_one_month():
    # June 13 → July 12: target's day-of-month is BEFORE today's, so 0 full
    # months crossed, clamped to 1.
    assert months_until(date(2026, 7, 12), today=date(2026, 6, 13)) == 1


def test_months_until_past_due_clamps_to_one():
    assert months_until(date(2025, 1, 1), today=date(2026, 6, 13)) == 1


def test_months_until_year_boundary():
    # Dec 1 2026 → Feb 1 2027 = 2 months.
    assert months_until(date(2027, 2, 1), today=date(2026, 12, 1)) == 2


def test_goal_already_at_target_asks_zero():
    today = date(2026, 1, 1)
    goal = _goal(
        target_amount=Decimal("5000"),
        current_saved=Decimal("5000"),
        target_date=date(2027, 1, 1),
    )
    assert monthly_required(goal, today) == Decimal("0.00")


def test_goal_above_target_asks_zero_not_negative():
    today = date(2026, 1, 1)
    goal = _goal(
        target_amount=Decimal("5000"),
        current_saved=Decimal("5500"),
        target_date=date(2027, 1, 1),
    )
    assert monthly_required(goal, today) == Decimal("0.00")


def test_per_check_of_zero_monthly_is_zero():
    assert per_check(_src(), Decimal("0")) == Decimal("0.00")


# ---------------------------------------------------------------------------
# build_per_paycheck_plan — aggregation contract
# ---------------------------------------------------------------------------

def test_plan_buckets_by_funding_source_and_sorts_by_name():
    today = date(2026, 1, 1)
    alex = _src(id=1, name="Alex", cadence="biweekly", periods_per_year=26)
    alexa = _src(id=2, name="Alexa", cadence="monthly", periods_per_year=12)
    f_alex = _fund(id=10, name="Phone", amount=Decimal("49.99"),
                   bill_periods_per_year=12, funding_source_id=alex.id)
    f_alexa = _fund(id=11, name="Car Insurance", amount=Decimal("374"),
                    bill_periods_per_year=1, funding_source_id=alexa.id)
    g_alexa = _goal(id=20, name="Japan", target_amount=Decimal("13500"),
                    current_saved=Decimal("0"),
                    target_date=date(2027, 1, 1),
                    funding_source_id=alexa.id)

    plans = build_per_paycheck_plan([alex, alexa], [f_alex, f_alexa], [g_alexa], today)

    # Sorted by name → Alex first, Alexa second.
    assert [p.pay_source_name for p in plans] == ["Alex", "Alexa"]

    alex_plan = plans[0]
    assert alex_plan.monthly_total == Decimal("49.99")
    assert alex_plan.per_check_total == Decimal("23.07")
    assert len(alex_plan.items) == 1
    assert alex_plan.items[0].name == "Phone"
    assert alex_plan.items[0].monthly == Decimal("49.99")
    assert alex_plan.items[0].per_check == Decimal("23.07")

    alexa_plan = plans[1]
    # Monthly total = monthly_accrual(374 annual) + monthly_required(13500/12) =
    # 31.1666... + 1125 = 1156.1666... → 1156.17
    assert alexa_plan.monthly_total == Decimal("1156.17")
    # per_check_total derived from UNROUNDED sum: 1156.1666... × 12/12 = 1156.17
    assert alexa_plan.per_check_total == Decimal("1156.17")
    assert {it.name for it in alexa_plan.items} == {"Car Insurance", "Japan"}


def test_plan_drops_items_without_funding_source():
    today = date(2026, 1, 1)
    alex = _src(id=1, name="Alex", periods_per_year=26)
    orphan = _fund(amount=Decimal("100"), bill_periods_per_year=12,
                   funding_source_id=None)
    plans = build_per_paycheck_plan([alex], [orphan], [], today)
    assert len(plans) == 1
    assert plans[0].monthly_total == Decimal("0.00")
    assert plans[0].items == []


def test_plan_with_no_pay_sources_returns_empty():
    assert build_per_paycheck_plan([], [], [], date(2026, 1, 1)) == []
