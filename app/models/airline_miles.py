"""Airline loyalty programmes, memberships, and miles snapshots — phase 1.5 task 2.

Three tables in a parent / child / grandchild shape:

  AirlineProgram               brand metadata for one loyalty programme
   └─ AirlineProgramMembership one row per (programme, person)
       └─ AirlineMilesSnapshot one row per (membership, as-of date)

The split mirrors balance_snapshots — current balance lives on the
snapshot rows, not the membership row, so the user gets a points
history over time and re-entering a balance for the same date
overwrites rather than fails (upsert at the route layer).
"""
from sqlalchemy import (
    BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, Integer,
    Text, UniqueConstraint, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class AirlineProgram(Base):
    __tablename__ = "airline_programs"

    id = Column(Integer, primary_key=True, index=True)
    # URL-safe slug used as the logo filename stem and as a stable
    # identifier independent of `name`.
    code = Column(Text, nullable=False)
    name = Column(Text, nullable=False)
    # alliance: 'oneworld' / 'star' / 'skyteam' / 'none'. Stored as TEXT
    # with a CHECK constraint, matching the people.role pattern.
    alliance = Column(Text, nullable=False, default="none", server_default="none")
    # 7-char hex including the leading hash, e.g. '#c8102e'. Rendered
    # straight into a CSS custom property on the program card.
    brand_color = Column(Text, nullable=False)
    # Path under /static, e.g. 'airline_logos/aadvantage.jpeg'. Nullable
    # so the row can be created before the asset is uploaded.
    logo_path = Column(Text, nullable=True)
    display_order = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("code", name="uq_airline_programs_code"),
        CheckConstraint(
            "alliance IN ('oneworld', 'star', 'skyteam', 'none')",
            name="ck_airline_programs_alliance_values",
        ),
    )

    memberships = relationship(
        "AirlineProgramMembership",
        back_populates="program",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class AirlineProgramMembership(Base):
    __tablename__ = "airline_program_memberships"

    id = Column(Integer, primary_key=True, index=True)
    program_id = Column(
        Integer, ForeignKey("airline_programs.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    person_id = Column(
        Integer, ForeignKey("people.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    # member_number / elite_status / notes are nullable so the household
    # can stub out placeholder rows for people who haven't joined a
    # programme yet — the UI shows them as blank rows on the program card.
    member_number = Column(Text, nullable=True)
    elite_status = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(),
                        onupdate=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "program_id", "person_id",
            name="uq_airline_program_memberships_program_person",
        ),
    )

    program = relationship("AirlineProgram", back_populates="memberships")
    person = relationship("Person")
    # No passive_deletes=True here: SQLite (used by the test suite) doesn't
    # enforce FK ON DELETE CASCADE without PRAGMA foreign_keys=ON, so we
    # rely on SQLAlchemy to issue child DELETEs explicitly. Postgres still
    # has the DB-level CASCADE as a safety net for raw-SQL deletes that
    # bypass the ORM.
    snapshots = relationship(
        "AirlineMilesSnapshot",
        back_populates="membership",
        cascade="all, delete-orphan",
        order_by="AirlineMilesSnapshot.as_of_date.desc()",
    )


class AirlineMilesSnapshot(Base):
    __tablename__ = "airline_miles_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    membership_id = Column(
        Integer,
        ForeignKey("airline_program_memberships.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    as_of_date = Column(Date, nullable=False)
    # BigInteger because some loyalty programmes carry 8-figure point
    # totals via credit-card transfers (Amex MR -> Aeroplan etc.).
    balance = Column(BigInteger, nullable=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint(
            "membership_id", "as_of_date",
            name="uq_airline_miles_snapshots_membership_date",
        ),
        CheckConstraint(
            "balance >= 0",
            name="ck_airline_miles_snapshots_balance_nonneg",
        ),
    )

    membership = relationship("AirlineProgramMembership", back_populates="snapshots")
