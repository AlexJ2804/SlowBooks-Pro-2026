"""People + account ownerships — phase 1.5.

Replaces the alex_pct / alexa_pct / kids_pct three-column ownership
model on `accounts` with a proper join table. Each personal account
gets one or more rows in `account_ownerships` keyed by (account_id,
person_id), with share_pct that sums to 100 across the rows for any
given account_id. System COA accounts (Service Income etc.) get zero
rows — they're not personally owned.

Sum-to-100 enforcement is layered:
  - DB trigger `trg_account_ownerships_sum` (Postgres only, deferrable)
    catches raw-SQL inserts that bypass the API.
  - Pydantic validation in app/schemas/accounts.py catches API input
    before it hits the DB. Tests use SQLite which has no trigger, so
    app-level validation is doing the work there.

Theodore = kids_pct mapping is one-way and historical — see the
docstring in alembic/versions/j2a3b4c5d6e7_people_and_ownerships.py.
"""
import enum

from sqlalchemy import (
    CheckConstraint, Column, DateTime, ForeignKey, Integer, Text, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class PersonRole(str, enum.Enum):
    """Lowercase string values to match the DB CHECK constraint.
    Stored as TEXT in the column, not as a Postgres ENUM type."""
    PARENT = "parent"
    CHILD = "child"
    OTHER = "other"


class Person(Base):
    __tablename__ = "people"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(Text, nullable=False)
    # role: 'parent' / 'child' / 'other'. App-layer code that gates
    # operations on parents (e.g. credit-score entry, where minors have
    # no credit history) reads this column. CHECK constraint below
    # rejects unknown values at the DB layer.
    role = Column(Text, nullable=False)
    # display_order controls stable rendering in the UI (so Alex always
    # appears before Alexa, regardless of insertion order).
    display_order = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            "role IN ('parent', 'child', 'other')",
            name="ck_people_role_values",
        ),
    )

    ownerships = relationship("AccountOwnership", back_populates="person")


class AccountOwnership(Base):
    """Join row: which person owns what share of which account.

    share_pct is a positive integer 1..100. The DB-level row CHECK
    rejects 0 and out-of-range values. The deferrable constraint
    trigger validates the per-account total at COMMIT.
    """
    __tablename__ = "account_ownerships"

    account_id = Column(Integer,
                        ForeignKey("accounts.id", ondelete="CASCADE"),
                        primary_key=True)
    person_id = Column(Integer,
                       ForeignKey("people.id", ondelete="RESTRICT"),
                       primary_key=True)
    share_pct = Column(Integer, nullable=False)

    __table_args__ = (
        CheckConstraint(
            "share_pct > 0 AND share_pct <= 100",
            name="ck_account_ownerships_share_range",
        ),
    )

    account = relationship("Account", back_populates="ownerships")
    person = relationship("Person", back_populates="ownerships")
