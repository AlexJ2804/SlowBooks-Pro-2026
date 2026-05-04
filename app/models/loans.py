"""Loan + amortization schedule (net-worth phase 1).

A `Loan` row is 1:1 with an `Account` of kind='loan'. Carries the
amortization parameters (rate, term, monthly payment, escrow) so the
dashboard can compute principal-vs-interest splits and project payoff.

`LoanAmortizationSchedule` is populated lazily — phase 1 spec is that
the schedule stays empty until the user clicks "Generate schedule" on
the loan edit UI after entering real (not placeholder) values. Avoids
tearing down stale rows when placeholders get corrected.
"""

from sqlalchemy import (
    Column, Integer, String, Date, Numeric, DateTime, ForeignKey,
    UniqueConstraint, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Loan(Base):
    __tablename__ = "loans"

    id = Column(Integer, primary_key=True, index=True)
    # The liability account (kind='loan') this loan tracks.
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    # Optional pointer to the asset (kind='property') secured by this loan.
    # NULL for unsecured loans (personal lines of credit, student loans, etc.).
    asset_account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)

    original_amount = Column(Numeric(12, 2), nullable=False)
    # Annual percentage rate. 6.5 means 6.5% APR. Stored to 4 decimal places
    # so we can carry sub-bp precision (e.g. 6.4375).
    interest_rate = Column(Numeric(6, 4), nullable=False)
    term_months = Column(Integer, nullable=False)
    start_date = Column(Date, nullable=False)
    monthly_payment = Column(Numeric(12, 2), nullable=False)
    escrow_amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    currency = Column(String(3), nullable=False, default="USD", server_default="USD")

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("account_id", name="uq_loans_account_id"),
    )

    account = relationship("Account", foreign_keys=[account_id])
    asset_account = relationship("Account", foreign_keys=[asset_account_id])
    schedule = relationship(
        "LoanAmortizationSchedule",
        back_populates="loan",
        cascade="all, delete-orphan",
        order_by="LoanAmortizationSchedule.payment_number",
    )


class LoanAmortizationSchedule(Base):
    __tablename__ = "loan_amortization_schedule"

    id = Column(Integer, primary_key=True, index=True)
    loan_id = Column(Integer, ForeignKey("loans.id", ondelete="CASCADE"),
                     nullable=False, index=True)
    payment_number = Column(Integer, nullable=False)
    payment_date = Column(Date, nullable=False)
    principal_amount = Column(Numeric(12, 2), nullable=False)
    interest_amount = Column(Numeric(12, 2), nullable=False)
    escrow_amount = Column(Numeric(12, 2), nullable=False, default=0, server_default="0")
    remaining_balance = Column(Numeric(12, 2), nullable=False)

    __table_args__ = (
        UniqueConstraint("loan_id", "payment_number", name="uq_loan_amort_loan_payment"),
    )

    loan = relationship("Loan", back_populates="schedule")
