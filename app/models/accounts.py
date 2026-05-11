# ============================================================================
# Decompiled from qbw32.exe!CChartOfAccounts  Offset: 0x000B12A0
# Original Btrieve table: ACCT.DAT (record size 0x0180, key 0 = AcctNum)
# Field mappings reconstructed from CQBAccount::Serialize() vtable
# ============================================================================

import enum

from sqlalchemy import Column, Integer, String, Enum, Boolean, ForeignKey, Numeric, DateTime, func
from sqlalchemy.orm import relationship

from app.database import Base


class AccountType(str, enum.Enum):
    # enum QBAccountType @ 0x000B14E8 — originally stored as WORD (0-5)
    ASSET = "asset"          # 0x0000
    LIABILITY = "liability"  # 0x0001
    EQUITY = "equity"        # 0x0002
    INCOME = "income"        # 0x0003
    EXPENSE = "expense"      # 0x0004
    COGS = "cogs"            # 0x0005


class Account(Base):
    __tablename__ = "accounts"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)               # ACCT.DAT field 0x02, LPSTR[159]
    account_number = Column(String(20), unique=True, nullable=True)  # field 0x01, key 0
    account_type = Column(Enum(AccountType), nullable=False)  # field 0x03, WORD
    parent_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)  # field 0x0A, sub-account ref
    description = Column(String(500), nullable=True)          # field 0x04, LPSTR[255]
    # is_active / is_system gain server_defaults + NOT NULL in alembic
    # i1f2a3b4c5d6 (May-2026 follow-up). Pre-h0e1f2a3b4c5 these were
    # nullable; raw SQL inserts that omitted the column landed with NULL,
    # which broke /api/accounts via Pydantic validation. Mirror the
    # server-side state here so SQLAlchemy autogenerate doesn't try to
    # diff them away on the next `alembic revision --autogenerate`.
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    is_system = Column(Boolean, nullable=False, default=False, server_default="false")  # seed accounts can't be deleted
    balance = Column(Numeric(12, 2), default=0)               # field 0x06, BCD[6] packed decimal

    # DEPRECATED in phase 1.5 (alembic j2a3b4c5d6e7). Ownership now lives
    # in the account_ownerships join table, accessible via the
    # `ownerships` relationship below. These three columns are still
    # populated via dual-write at the application layer (see
    # app/routes/accounts.py) so reads against pre-1.5 callers don't
    # silently break, and so the data is recoverable if 1.5 needs to be
    # rolled back. They are scheduled to be dropped in a follow-up
    # migration once 1.5 is stable for ~1 week. Do not add new readers.
    alex_pct = Column(Integer, nullable=False, default=0, server_default="0")
    alexa_pct = Column(Integer, nullable=False, default=0, server_default="0")
    kids_pct = Column(Integer, nullable=False, default=0, server_default="0")

    # account_kind sub-classifies asset/liability into the categories the
    # net-worth dashboard groups by. Distinct from account_type which is
    # the QB-coarse dimension (asset/liability/equity/income/expense/cogs).
    # Nullable because existing system accounts (Service Income etc.)
    # don't fit any of these — they're just income/expense lines.
    account_kind = Column(String(20), nullable=True)
    update_strategy = Column(String(20), nullable=True)

    # Native currency of the account. Per-account because Revolut IE / BoI /
    # Capital Credit Union are EUR while Heartland / Vanguard / Vestwell
    # are USD. Defaults USD; the personal-accounts seed sets it explicitly.
    currency = Column(String(3), nullable=False, default="USD", server_default="USD")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    parent = relationship("Account", remote_side=[id], backref="children")
    transaction_lines = relationship("TransactionLine", back_populates="account")

    # Phase 1.5: each personal account has 0..N rows in account_ownerships.
    # Zero rows = system COA / not personally owned. cascade='all, delete-orphan'
    # means deleting an Account ORM object also deletes its ownership rows
    # (mirrors the ON DELETE CASCADE on the FK).
    ownerships = relationship(
        "AccountOwnership",
        back_populates="account",
        cascade="all, delete-orphan",
        lazy="select",
    )
