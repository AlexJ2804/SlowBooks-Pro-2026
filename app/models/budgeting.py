# ============================================================================
# Budgeting — Goals + Sinking Funds + Pay Sources (Phase 1, Task 1B)
#
# Design principle (LOCKED): the household has two pay cadences, so a stored
# "per-paycheck" number is ambiguous. The canonical stored unit is the MONTHLY
# contribution. We store the natural inputs (bill amount + frequency, or
# target + date) and DERIVE monthly and per-paycheck figures in
# app/services/budget_calc.py. We never persist a per-paycheck amount.
#
# Architecture (LOCKED): virtual envelopes against ONE holding account
# (Monarch/YNAB model), not separate bank accounts. Funds/goals carry a
# virtual balance; linked_account_id points at the real holding savings
# account so the UI can show allocated-vs-unallocated against the real
# balance.
# ============================================================================

import enum

from sqlalchemy import (
    Column, Integer, String, Date, Numeric, DateTime, ForeignKey,
    CheckConstraint, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class PayCadence(str, enum.Enum):
    WEEKLY = "weekly"          # 52 / yr
    BIWEEKLY = "biweekly"      # 26 / yr
    SEMIMONTHLY = "semimonthly"  # 24 / yr
    MONTHLY = "monthly"        # 12 / yr


class PaySource(Base):
    """An earner / income stream with a fixed pay cadence.

    `periods_per_year` is stored explicitly (rather than derived from
    `cadence`) so the per-paycheck math is a single multiply and never has
    to branch on the enum. The two must agree; the API validates that.

    `net_per_check` is the take-home per paycheck. Nullable — the household
    enters it later; the per-paycheck PLAN math does not need it (it converts
    a monthly set-aside into a per-check figure via periods_per_year).
    """
    __tablename__ = "pay_sources"
    __table_args__ = (
        CheckConstraint(
            "cadence IN ('weekly', 'biweekly', 'semimonthly', 'monthly')",
            name="ck_pay_sources_cadence_values",
        ),
        CheckConstraint(
            "periods_per_year IN (52, 26, 24, 12)",
            name="ck_pay_sources_periods_values",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    # Cadence is stored as the lowercase string value (matches the CHECK
    # constraint + the API's `Literal` type). Using `String` instead of
    # `Enum(PayCadence)` avoids SQLAlchemy's default behaviour of writing
    # the enum NAME ('BIWEEKLY'), which would violate the CHECK that
    # accepts 'biweekly'. The `PayCadence` Python enum above is kept as
    # a typing constant for callers that prefer symbolic refs.
    cadence = Column(String(20), nullable=False)
    periods_per_year = Column(Integer, nullable=False)
    net_per_check = Column(Numeric(12, 2), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)


class SinkingFund(Base):
    """A recurring/lumpy bill we pre-fund a little each month.

    `amount` is the per-occurrence bill (e.g. $374 once a year). Combined
    with `bill_periods_per_year` (1=annual, 2=semiannual, 4=quarterly,
    12=monthly), the calc layer derives the monthly accrual:
        monthly_accrual = amount * bill_periods_per_year / 12

    `current_balance` is the VIRTUAL envelope balance — money notionally set
    aside, held inside the real `linked_account_id` account along with other
    envelopes. `funding_source_id` says which pay stream funds it.
    """
    __tablename__ = "sinking_funds"
    __table_args__ = (
        CheckConstraint(
            "bill_periods_per_year IN (1, 2, 4, 12)",
            name="ck_sinking_funds_bill_periods_values",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    amount = Column(Numeric(12, 2), nullable=False)
    bill_periods_per_year = Column(Integer, nullable=False)
    next_due = Column(Date, nullable=True)
    current_balance = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    linked_account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    funding_source_id = Column(
        Integer, ForeignKey("pay_sources.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    currency = Column(String(3), nullable=False, default="USD", server_default="USD")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    linked_account = relationship("Account", foreign_keys=[linked_account_id])
    funding_source = relationship("PaySource", foreign_keys=[funding_source_id])


class Goal(Base):
    """A savings target with a date (e.g. a Japan trip).

    The calc layer derives the monthly contribution required to hit
    `target_amount` by `target_date` from where we are now:
        monthly_required = max(0, (target_amount - current_saved)
                                   / months_until(target_date))    # months >= 1

    `current_saved` is the VIRTUAL envelope balance, same model as
    SinkingFund.current_balance.
    """
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), nullable=False)
    target_amount = Column(Numeric(12, 2), nullable=False)
    target_date = Column(Date, nullable=False)
    current_saved = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    linked_account_id = Column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    funding_source_id = Column(
        Integer, ForeignKey("pay_sources.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    currency = Column(String(3), nullable=False, default="USD", server_default="USD")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    linked_account = relationship("Account", foreign_keys=[linked_account_id])
    funding_source = relationship("PaySource", foreign_keys=[funding_source_id])
