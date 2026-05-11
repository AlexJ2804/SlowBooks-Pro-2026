"""statement_imports + bank_transactions.statement_import_id

Revision ID: n6e7f8g9h0i1
Revises: m5d6e7f8g9h0
Create Date: 2026-05-09 00:00:00.000000

Phase 2 — PDF statement ingestion. One row per uploaded PDF, parsed by
the Anthropic Vision API into structured bank_transactions. Drill-back
from any transaction to the source PDF lives on
bank_transactions.statement_import_id.

Idempotency: content_hash is SHA-256 of the PDF bytes, unique-indexed.
Re-uploading the same PDF returns 409 with a pointer to the original
import. Same pattern as the OFX importer's FITID dedup, but a content
hash instead of a per-line ID because a statement is one atomic blob.

Cost surfacing: vision_cost_cents + input_tokens + output_tokens are
captured per import so the upload-result toast can show "$0.04, 8,432
in / 1,210 out" and a future dashboard rollup can sum them by month.

raw_response_json is kept (Text, nullable) for debugging — when a
parse misses rows we want to inspect what the model actually returned
without re-uploading the PDF and burning another vision call.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'n6e7f8g9h0i1'
down_revision: Union[str, None] = 'm5d6e7f8g9h0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'statement_imports',
        sa.Column('id', sa.Integer(), primary_key=True),
        # Points at bank_accounts (not the COA accounts table) because
        # the parsed rows materialise as bank_transactions, which already
        # reference bank_account_id. Going via the COA would add a hop
        # without buying anything.
        sa.Column('bank_account_id', sa.Integer(),
                  sa.ForeignKey('bank_accounts.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        # period_start/end are nullable — the model fills them from the
        # statement header, but we don't want a malformed PDF to block
        # the upload row from being persisted (status='failed' rows
        # need to land somewhere so the user can see + retry them).
        sa.Column('period_start', sa.Date(), nullable=True),
        sa.Column('period_end', sa.Date(), nullable=True),
        sa.Column('source_pdf_path', sa.String(500), nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('vision_model', sa.String(50), nullable=True),
        sa.Column('vision_cost_cents', sa.Integer(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=True),
        sa.Column('output_tokens', sa.Integer(), nullable=True),
        # status: pending → parsing → parsed → posted ; or → failed
        # CHECK constraint instead of ENUM type — same rationale as the
        # rest of this codebase (cheaper to extend later).
        sa.Column('status', sa.String(20),
                  nullable=False, server_default='pending'),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column('raw_response_json', sa.Text(), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('parsed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('posted_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_unique_constraint(
        'uq_statement_imports_content_hash',
        'statement_imports', ['content_hash'],
    )
    op.create_check_constraint(
        'ck_statement_imports_status_values', 'statement_imports',
        "status IN ('pending', 'parsing', 'parsed', 'posted', 'failed')",
    )

    # Drill-back: every parsed bank_transaction gets a pointer back to
    # the source statement PDF. Nullable because OFX/QFX imports and
    # manually-entered transactions don't have a statement.
    # ON DELETE SET NULL — deleting the import row shouldn't cascade-
    # delete the transactions; the user might have already reconciled
    # them. The drill-back link just goes away.
    op.add_column(
        'bank_transactions',
        sa.Column('statement_import_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_bank_transactions_statement_import_id_statement_imports',
        'bank_transactions', 'statement_imports',
        ['statement_import_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_bank_transactions_statement_import_id',
        'bank_transactions', ['statement_import_id'],
    )


def downgrade() -> None:
    op.drop_index(
        'ix_bank_transactions_statement_import_id',
        table_name='bank_transactions',
    )
    op.drop_constraint(
        'fk_bank_transactions_statement_import_id_statement_imports',
        'bank_transactions', type_='foreignkey',
    )
    op.drop_column('bank_transactions', 'statement_import_id')
    op.drop_table('statement_imports')
