"""Manual balance snapshots — net-worth phase 1.

For accounts whose balance is `update_strategy='balance_only'` (brokerage,
retirement, property, loan), the user enters periodic balance readings
through the UI. The dashboard reads the latest snapshot per account.

Currency is denormalized from the parent account so historical
snapshots stay accurate if the account's native currency is ever
changed in the future. (account.currency doesn't currently exist as a
column; it lives implicitly per-account in app code. Storing on each
snapshot pins the read.)
"""

from sqlalchemy import (
    Column, Integer, String, Date, Numeric, DateTime, ForeignKey,
    UniqueConstraint, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class BalanceSnapshot(Base):
    __tablename__ = "balance_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=False, index=True)
    as_of_date = Column(Date, nullable=False)
    balance = Column(Numeric(12, 2), nullable=False)
    currency = Column(String(3), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("account_id", "as_of_date", name="uq_balance_snapshots_account_date"),
    )

    account = relationship("Account")
