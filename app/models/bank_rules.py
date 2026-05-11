# ============================================================================
# Bank Rules — auto-categorize imported transactions by payee pattern
# Phase 10: Quick Wins + Medium Effort Features
# ============================================================================

from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, func

from app.database import Base


class BankRule(Base):
    __tablename__ = "bank_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    pattern = Column(String(200), nullable=False)
    account_id = Column(Integer, ForeignKey("accounts.id"), nullable=True)
    vendor_id = Column(Integer, ForeignKey("vendors.id"), nullable=True)
    # Phase 3: per-business class tagging. NULL = no business attribution
    # (implicit personal/household), matching rule still propagates the
    # category but leaves class_id untouched on the txn.
    class_id = Column(
        Integer,
        ForeignKey("classes.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    rule_type = Column(String(20), default="contains")  # contains, starts_with, exact
    priority = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
