# ============================================================================
# StatementImport — one row per uploaded PDF bank/CC statement.
# Phase 2: PDF statement ingestion pipeline (issue #1).
# ============================================================================
# The Anthropic Vision API parses each PDF into structured transactions
# that get materialised as bank_transactions rows with a back-pointer here
# (bank_transactions.statement_import_id) so any line can be drilled back
# to the source PDF page.
# ============================================================================

from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Text, ForeignKey, func,
)
from sqlalchemy.orm import relationship

from app.database import Base


class StatementImport(Base):
    __tablename__ = "statement_imports"

    id = Column(Integer, primary_key=True, index=True)
    # Points at bank_accounts (not the COA accounts table) because the
    # parsed rows land in bank_transactions, which keys on bank_account_id.
    bank_account_id = Column(
        Integer,
        ForeignKey("bank_accounts.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )

    period_start = Column(Date, nullable=True)
    period_end = Column(Date, nullable=True)

    source_pdf_path = Column(String(500), nullable=False)
    # SHA-256 of the PDF bytes; unique-indexed for idempotency. Re-uploading
    # the same PDF returns 409 with a pointer to the original import row.
    content_hash = Column(String(64), nullable=False, unique=True)
    file_size = Column(Integer, nullable=False)

    vision_model = Column(String(50), nullable=True)
    vision_cost_cents = Column(Integer, nullable=True)
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)

    # status: pending → parsing → parsed → posted ; or → failed
    status = Column(String(20), nullable=False, default="pending")
    error_message = Column(Text, nullable=True)
    # Raw model output kept for debugging missed-rows cases without
    # re-uploading and burning another vision call. Cleared on /post.
    raw_response_json = Column(Text, nullable=True)

    uploaded_at = Column(DateTime(timezone=True),
                         server_default=func.now(), nullable=False)
    parsed_at = Column(DateTime(timezone=True), nullable=True)
    posted_at = Column(DateTime(timezone=True), nullable=True)

    bank_account = relationship("BankAccount", foreign_keys=[bank_account_id])
    transactions = relationship(
        "BankTransaction",
        back_populates="statement_import",
        foreign_keys="BankTransaction.statement_import_id",
    )
