"""Budgeting calculation layer (Phase 1, Task 1B).

Single source of truth for the per-paycheck math. The household has two pay
cadences (biweekly + monthly), so a stored "per-paycheck" number would be
ambiguous. We store the natural inputs and derive everything from them here.

Formulas (LOCKED — match the acceptance criteria in the work order):

    monthly_accrual(fund) = (fund.amount * fund.bill_periods_per_year) / 12

    monthly_required(goal) = max(0, (goal.target_amount - goal.current_saved)
                                     / months_until(goal.target_date))
        # months_until clamped to >= 1 so a same-month or past-due goal
        # asks for the full remaining amount this month rather than dividing
        # by zero.

    per_check(pay_source, monthly_total) =
        monthly_total * 12 / pay_source.periods_per_year

PRECISION RULE:
    Internally we keep Decimals at full precision and only quantize to cents
    at the display boundary. If we quantized monthly first and then derived
    per_check from the quantized value, a $374 annual fund on a biweekly
    cadence comes out 14.39 (374/12 → 31.17 → ×12/26 → 14.39) rather than
    14.38 (374/26 = 14.3846 → 14.38). The acceptance criteria require 14.38,
    so per_check is derived from the UNROUNDED monthly, not from the rounded
    one that the API also exposes. Both rounded values appear in the JSON
    response; readers should treat them as independently rounded views of
    the same underlying figure, not as exact arithmetic neighbours.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Iterable, Optional

from app.models.budgeting import Goal, PaySource, SinkingFund


_CENT = Decimal("0.01")
_TWELVE = Decimal("12")


def _to_cents(value: Decimal) -> Decimal:
    """Quantize to 2dp half-up. Used at the display boundary only."""
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def months_until(target: date, today: Optional[date] = None) -> int:
    """Whole calendar months from `today` to `target`, clamped to >= 1.

    Day-of-month aware: today=2026-06-13, target=2026-07-12 → target's day
    is BEFORE today's day in July, so 0 full months crossed → clamp to 1.
    target=2026-07-13 (same day next month) → 1 month.
    """
    if today is None:
        today = date.today()
    months = (target.year - today.year) * 12 + (target.month - today.month)
    if target.day < today.day:
        months -= 1
    return max(1, months)


# ---------------------------------------------------------------------------
# Exact (unrounded) primitives — internal use only.
# ---------------------------------------------------------------------------

def _monthly_accrual_exact(fund: SinkingFund) -> Decimal:
    return Decimal(fund.amount) * Decimal(fund.bill_periods_per_year) / _TWELVE


def _monthly_required_exact(goal: Goal, today: Optional[date] = None) -> Decimal:
    remaining = Decimal(goal.target_amount) - Decimal(goal.current_saved)
    if remaining <= 0:
        return Decimal("0")
    return remaining / Decimal(months_until(goal.target_date, today))


def _per_check_exact(pay_source: PaySource, monthly_exact: Decimal) -> Decimal:
    if monthly_exact <= 0:
        return Decimal("0")
    return monthly_exact * _TWELVE / Decimal(pay_source.periods_per_year)


# ---------------------------------------------------------------------------
# Display-quantized variants — what the route layer / templates show.
# ---------------------------------------------------------------------------

def monthly_accrual(fund: SinkingFund) -> Decimal:
    """How much to set aside this month for a recurring bill (quantized)."""
    return _to_cents(_monthly_accrual_exact(fund))


def monthly_required(goal: Goal, today: Optional[date] = None) -> Decimal:
    """Monthly contribution to hit `target_amount` by `target_date` (quantized).

    Clamped to >= 0: a goal at or above its target asks for nothing.
    """
    return _to_cents(_monthly_required_exact(goal, today))


def per_check(pay_source: PaySource, monthly_total: Decimal) -> Decimal:
    """Convert an UNROUNDED monthly set-aside into a per-check figure.

    Quantized to cents for display. Callers building a paycheck plan should
    pass the unrounded monthly (e.g. from `_monthly_accrual_exact`) — see
    the precision-rule docstring at the top of this file.
    """
    return _to_cents(_per_check_exact(pay_source, Decimal(monthly_total)))


# ---------------------------------------------------------------------------
# Aggregation: build the "Per-Paycheck Plan" shape consumed by the route +
# the dashboard widget. Pure function over already-loaded ORM objects so the
# tests can drive it without a DB session.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PerCheckLine:
    """One contributor (fund OR goal) within a pay source's plan."""
    kind: str                    # "sinking_fund" | "goal"
    id: int
    name: str
    monthly: Decimal             # displayed contribution this month (quantized)
    per_check: Decimal           # converted to this earner's cadence (quantized)


@dataclass(frozen=True)
class PerCheckPlan:
    """One pay_source's set-aside totals + the per-item breakdown."""
    pay_source_id: int
    pay_source_name: str
    cadence: str
    periods_per_year: int
    monthly_total: Decimal       # sum of all items routed to this source (quantized)
    per_check_total: Decimal     # derived from the UNROUNDED sum (quantized)
    items: list[PerCheckLine]


def build_per_paycheck_plan(
    pay_sources: Iterable[PaySource],
    sinking_funds: Iterable[SinkingFund],
    goals: Iterable[Goal],
    today: Optional[date] = None,
) -> list[PerCheckPlan]:
    """Bucket every fund + goal by `funding_source_id` and compute totals.

    Items without a `funding_source_id` are dropped from the per-source plan
    (the plan is "what to set aside per check, per earner"; unassigned items
    are shown elsewhere in the UI).

    Per-check figures are derived from UNROUNDED monthly amounts (see the
    precision-rule docstring at the top of this file). Output is sorted by
    pay_source name so the widget renders deterministically.
    """
    sources_by_id = {s.id: s for s in pay_sources}

    # Per-source bucket of (kind, id, name, monthly_exact) tuples.
    buckets: dict[int, list[tuple[str, int, str, Decimal]]] = {
        sid: [] for sid in sources_by_id
    }

    for fund in sinking_funds:
        if fund.funding_source_id and fund.funding_source_id in buckets:
            buckets[fund.funding_source_id].append(
                ("sinking_fund", fund.id, fund.name, _monthly_accrual_exact(fund))
            )

    for goal in goals:
        if goal.funding_source_id and goal.funding_source_id in buckets:
            buckets[goal.funding_source_id].append(
                ("goal", goal.id, goal.name, _monthly_required_exact(goal, today))
            )

    plans: list[PerCheckPlan] = []
    for sid, src in sources_by_id.items():
        rows = buckets[sid]
        monthly_total_exact = sum((m for _, _, _, m in rows), Decimal("0"))
        items = [
            PerCheckLine(
                kind=kind, id=iid, name=name,
                monthly=_to_cents(monthly_exact),
                per_check=per_check(src, monthly_exact),
            )
            for kind, iid, name, monthly_exact in rows
        ]
        plans.append(PerCheckPlan(
            pay_source_id=sid,
            pay_source_name=src.name,
            cadence=src.cadence.value if hasattr(src.cadence, "value") else src.cadence,
            periods_per_year=src.periods_per_year,
            monthly_total=_to_cents(monthly_total_exact),
            per_check_total=per_check(src, monthly_total_exact),
            items=items,
        ))

    plans.sort(key=lambda p: p.pay_source_name.lower())
    return plans
