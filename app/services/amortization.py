"""Mortgage / loan amortization engine (Phase 1, Task 1C).

Extracted from app/routes/loans.py so the same engine powers both:

  * the from-origination schedule generator (the existing
    /api/loans/{id}/generate-schedule, which needs original_amount +
    term_months + first_payment_date — populated only after the user
    enters those via the UI)

  * forward-projection from current state (the new
    /api/loans/{id}/project-forward endpoint), which doesn't need
    origination data. The math is identical: amortization of a balance
    `B` over `N` periods at rate `r` against a fixed payment `P` doesn't
    care whether `B` is the original principal or a partway-through
    balance. We just pass current_principal as `original_amount`.

Currency-agnostic — the engine only sees Decimals and dates. Currency
metadata lives on the Loan record; the engine never assumes USD or a
US monthly convention. Adapting to an Irish (or any) mortgage means
passing different inputs, not changing the engine.
"""

from __future__ import annotations

import calendar
from datetime import date
from decimal import Decimal, ROUND_HALF_UP


_CENTS = Decimal("0.01")


def compute_amortization(
    *,
    original_amount: Decimal,
    interest_rate_pct: Decimal,
    term_months: int,
    start_date: date,
    monthly_payment: Decimal,
    escrow_amount: Decimal,
) -> list[dict]:
    """Standard fixed-rate amortization split into principal/interest each period.

    `monthly_payment` is the authoritative total payment; principal for the
    period is `monthly_payment - escrow_amount - interest`. The final
    period's principal is nudged so `remaining_balance` lands at exactly 0,
    absorbing the sub-cent rounding drift from quantizing `monthly_payment`.

    Inputs:
        original_amount      Decimal — the balance the schedule starts from
                             (for from-origination: the loan's original
                             principal; for forward-projection: the current
                             remaining principal).
        interest_rate_pct    Decimal — annual percentage rate, e.g. 6.99.
                             0% is handled (interest = 0 every period).
        term_months          int    — number of payments in the schedule.
        start_date           date   — the date of payment #1.
        monthly_payment      Decimal — full P&I (and escrow if escrow_amount > 0).
        escrow_amount        Decimal — the escrow portion of monthly_payment.

    Returns a list of dicts shaped for SQLAlchemy's
    `LoanAmortizationSchedule(**row)` bulk insert.

    If `monthly_payment - escrow_amount` is less than the period's interest,
    principal goes negative — we let it through so the UI surfaces obviously-
    bad inputs visibly rather than silently misamortizing.
    """
    monthly_rate = (
        interest_rate_pct / Decimal(100) / Decimal(12)
        if interest_rate_pct > 0
        else Decimal(0)
    )
    rows: list[dict] = []
    remaining = original_amount
    pi_room = Decimal(monthly_payment) - Decimal(escrow_amount)

    for n in range(1, term_months + 1):
        interest = (remaining * monthly_rate).quantize(_CENTS, rounding=ROUND_HALF_UP)
        principal = (monthly_payment - escrow_amount - interest).quantize(
            _CENTS, rounding=ROUND_HALF_UP
        )

        # Final-row trueing: principal absorbs the remainder so balance ends
        # at exactly 0. GUARD: if the remaining balance at the final row
        # exceeds the P&I capacity of a single monthly_payment, the inputs
        # don't actually amortize over `term_months` — silently setting
        # principal=remaining would persist a "final payment" larger than
        # any normal payment, hiding the misamortization behind the
        # zeroed balance. Raise instead so bad inputs (wrong rate, wrong
        # term, an estimated APR that turned out off) surface visibly.
        if n == term_months:
            if remaining > pi_room:
                raise ValueError(
                    f"Schedule misamortizes: at the final payment, remaining "
                    f"balance {remaining} exceeds the P&I capacity of "
                    f"(monthly_payment {monthly_payment} - escrow {escrow_amount}) "
                    f"= {pi_room}. Check rate, term, or monthly_payment."
                )
            principal = remaining

        new_remaining = (remaining - principal).quantize(
            _CENTS, rounding=ROUND_HALF_UP
        )

        # Intermediate-balance guard: a pre-final row going negative means
        # a normal payment overshot the principal — the loan would have
        # paid off before term_months. Raise instead of running phantom
        # extra rows past payoff.
        if n < term_months and new_remaining < 0:
            raise ValueError(
                f"Schedule misamortizes: intermediate balance went negative "
                f"at payment {n} (remaining={new_remaining}). Loan likely "
                f"pays off before payment {term_months}; check term_months "
                f"or monthly_payment."
            )

        rows.append({
            "payment_number": n,
            "payment_date": add_months(start_date, n - 1),
            "principal_amount": principal,
            "interest_amount": interest,
            "escrow_amount": escrow_amount,
            "remaining_balance": new_remaining,
        })
        remaining = new_remaining

    return rows


def project_forward(
    *,
    current_principal: Decimal,
    interest_rate_pct: Decimal,
    monthly_payment: Decimal,
    escrow_amount: Decimal,
    next_payment_date: date,
    remaining_months: int | None = None,
) -> list[dict]:
    """Project an amortization schedule forward from a known current state.

    No origination data required — given the current balance, the rate, and
    the fixed monthly payment, we can derive (or be told) the remaining
    term and walk the schedule forward.

    If `remaining_months` is None it's solved for from the standard
    amortization formula:
        n = -ln(1 - (B * r) / (PMT - E)) / ln(1 + r)
    where B = current_principal, PMT = monthly_payment, E = escrow_amount,
    r = monthly_rate. The solved n is rounded up so the final payment
    absorbs any sub-cent leftover. If PMT-E ≤ B*r (payment can't even cover
    interest), we surface that as a ValueError rather than spiral into
    infinite term.

    Returns the same row shape as `compute_amortization`. payment_number
    starts at 1 (this is a fresh schedule for the projection window, not a
    continuation of historic payment numbers).
    """
    if remaining_months is None:
        remaining_months = _solve_remaining_months(
            current_principal=current_principal,
            interest_rate_pct=interest_rate_pct,
            monthly_payment=monthly_payment,
            escrow_amount=escrow_amount,
        )
    return compute_amortization(
        original_amount=current_principal,
        interest_rate_pct=interest_rate_pct,
        term_months=remaining_months,
        start_date=next_payment_date,
        monthly_payment=monthly_payment,
        escrow_amount=escrow_amount,
    )


def _solve_remaining_months(
    *,
    current_principal: Decimal,
    interest_rate_pct: Decimal,
    monthly_payment: Decimal,
    escrow_amount: Decimal,
) -> int:
    """Derive remaining payments from the standard amortization formula.

    For 0% APR: remaining_months = ceil(current_principal / (PMT - E)).
    For >0% APR: invert PMT = PV * r / (1 - (1+r)^-n).
    """
    import math

    pmt_pi = Decimal(monthly_payment) - Decimal(escrow_amount)
    if pmt_pi <= 0:
        raise ValueError(
            f"monthly_payment ({monthly_payment}) - escrow ({escrow_amount}) "
            f"must be > 0 to amortize a positive balance"
        )

    if interest_rate_pct <= 0:
        # No interest accruing — number of full PMT-sized chunks rounded up.
        # ceil(B / pmt_pi)
        chunks = (current_principal + pmt_pi - Decimal("0.01")) / pmt_pi
        return max(1, int(chunks))

    r = float(interest_rate_pct) / 100.0 / 12.0
    B = float(current_principal)
    P = float(pmt_pi)
    interest_only = B * r
    if P <= interest_only:
        raise ValueError(
            f"P&I portion of payment ({pmt_pi}) does not cover interest "
            f"({Decimal(interest_only).quantize(_CENTS)}) on principal "
            f"{current_principal} at {interest_rate_pct}% APR — loan would "
            f"never amortize"
        )

    # n = -ln(1 - B*r/P) / ln(1+r)
    n = -math.log(1.0 - (B * r) / P) / math.log(1.0 + r)
    return max(1, math.ceil(n))


def add_months(d: date, months: int) -> date:
    """Add `months` to a date, clamping the day to the new month's last
    valid day if the original was e.g. the 31st in a 30-day month.

    add_months(date(2026, 1, 31), 1) → 2026-02-28
    add_months(date(2024, 1, 31), 1) → 2024-02-29  (leap year aware)
    """
    if months == 0:
        return d
    new_year = d.year + (d.month - 1 + months) // 12
    new_month = (d.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    return date(new_year, new_month, min(d.day, last_day))
