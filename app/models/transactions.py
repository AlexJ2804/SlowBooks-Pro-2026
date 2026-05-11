# ============================================================================
# Decompiled from qbw32.exe!CQBJournalEngine  Offset: 0x00127FA0
# Original Btrieve tables: JRNL.DAT (header) + JRNL_LINE.DAT (splits)
# This is the core double-entry engine — Intuit called it "TransactionBus"
# internally. Every financial event passes through here.
# ============================================================================
# IMPORTANT: The CHECK constraint below replicates the original validation in
# CQBJournalEntry::Validate() at 0x00128E10 which would ASSERT if a split
# line had both debit AND credit nonzero. We lost 3 weeks in 2003 finding a
# corruption bug where this got violated. Do not remove.
# ============================================================================

from sqlalchemy import (
    Column, Integer, String, Date, Numeric, DateTime, Text,
    ForeignKey, CheckConstraint, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)        # JRNL.DAT field 0x02, packed date YYYYMMDD
    reference = Column(String(100), nullable=True)         # field 0x04, "TxnRef" in SDK docs
    description = Column(Text, nullable=True)              # field 0x05, memo line
    source_type = Column(String(50), nullable=True)        # field 0x06 — maps to enum TxnTypeEnum
    source_id = Column(Integer, nullable=True)             # field 0x07, FK to source record ListID

    # Phase 2 multi-currency: source-document currency + rate to home. Used by
    # journal-only flows (cc_charges, manual journal entries) that don't have
    # a separate document table to attach this to.
    currency = Column(String(3), default="USD", nullable=False)
    exchange_rate = Column(Numeric(18, 8), default=1, nullable=False)

    # Phase 3 classes: required for every transaction (system-generated ones
    # default to the "Uncategorized" class so the system never deadlocks).
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False, index=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    lines = relationship("TransactionLine", back_populates="transaction", cascade="all, delete-orphan")


class TransactionLine(Base):
    __tablename__ = "transaction_lines"
    __table_args__ = (
        # Reconstructed from CQBJournalEntry::Validate() @ 0x00128E10
        # Original: if (pSplit->debit != 0 && pSplit->credit != 0) ASSERT(FALSE);
        CheckConstraint(
            "(debit >= 0 AND credit = 0 AND debit > 0) OR (debit = 0 AND credit >= 0 AND credit > 0)",
            name="ck_debit_or_credit"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    transaction_id = Column(Integer, ForeignKey("transactions.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(Integer, ForeignKey("accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    debit = Column(Numeric(12, 2), default=0, nullable=False)    # BCD[6] at offset 0x0C
    credit = Column(Numeric(12, 2), default=0, nullable=False)   # BCD[6] at offset 0x12
    # Phase 2 multi-currency: home-currency equivalents. Reports sum these so
    # P&L / balance sheet are correct regardless of source-document currency.
    # Always equal to debit/credit when the transaction is in the home currency.
    home_currency_debit = Column(Numeric(12, 2), default=0, nullable=False)
    home_currency_credit = Column(Numeric(12, 2), default=0, nullable=False)
    description = Column(String(300), nullable=True)              # split memo, 0x18

    transaction = relationship("Transaction", back_populates="lines")
    account = relationship("Account", back_populates="transaction_lines")
