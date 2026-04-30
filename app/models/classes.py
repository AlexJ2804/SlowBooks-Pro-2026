# ============================================================================
# Classes — user-defined buckets for tagging transactions (QuickBooks-style).
# Used by the P&L "by class" reports to slice income/expense by Alex W-2,
# Wife 1099, Ireland Projects, etc.
#
# A single Class with is_system_default=true ("Uncategorized") is the
# migration backfill target and the implicit default for auto-generated
# transactions (Stripe webhook posts, recurring rollouts, IIF imports,
# late fees, sales-tax payment journal). It is protected from rename and
# archive at the route level (see app/routes/classes.py).
# ============================================================================

from sqlalchemy import Column, Integer, String, Boolean, DateTime, func

from app.database import Base


class Class(Base):
    __tablename__ = "classes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(120), unique=True, nullable=False)
    is_archived = Column(Boolean, default=False, nullable=False)
    is_system_default = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
