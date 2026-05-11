"""classes table + class_id FK on every transaction-bearing table

Revision ID: g8c9d0e1f2g3
Revises: f7b8c9d0e1f2
Create Date: 2026-04-30 16:00:00.000000

This adds explicit class tracking (QuickBooks-style) so transactions can be
sliced by user-defined buckets (Alex W-2, Wife 1099, Ireland Projects, etc.)
in reports.

Ordering matters and is enforced by upgrade():
1. Create the classes table and seed the eight rows (incl. Uncategorized).
2. For each transaction-bearing table, add class_id as a NULLABLE FK.
3. Backfill every existing row with the Uncategorized class id.
4. ALTER COLUMN to NOT NULL on each.

Without this ordering the backfill UPDATE has nothing to point at and the
NOT NULL fails on existing rows.

Existing per-line `class_name` String columns on InvoiceLine and EstimateLine
are unrelated legacy free-text annotations and are left untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'g8c9d0e1f2g3'
down_revision: Union[str, None] = 'f7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SEED_CLASSES = [
    ("Alex W-2 (US)", False),
    ("Alex 1099 (US)", False),
    ("Wife 1099 (US)", False),
    ("Alex Salary (Canada)", False),
    ("Alex Freelance Music (Canada)", False),
    ("Ireland Projects", False),
    ("Airbnb income from US Home", False),
    ("Uncategorized", True),
]


# Tables that get class_id NOT NULL FK. Order doesn't matter (each is
# independent), but listed in user-spec order for traceability.
TXN_TABLES = (
    "invoices",
    "bills",
    "bill_payments",
    "payments",
    "estimates",
    "credit_memos",
    "transactions",
    "recurring_invoices",
)


def upgrade() -> None:
    # 1. Create the classes table.
    op.create_table(
        'classes',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(120), unique=True, nullable=False),
        sa.Column('is_archived', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('is_system_default', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # 2. Seed the eight rows.
    classes_table = sa.table(
        'classes',
        sa.column('name', sa.String),
        sa.column('is_system_default', sa.Boolean),
    )
    op.bulk_insert(
        classes_table,
        [{"name": name, "is_system_default": is_default} for name, is_default in SEED_CLASSES],
    )

    # 3+4. For each transaction-bearing table: add nullable, backfill,
    # then enforce NOT NULL.
    for table in TXN_TABLES:
        op.add_column(table, sa.Column('class_id', sa.Integer(), nullable=True))
        op.execute(
            f"UPDATE {table} SET class_id = "
            f"(SELECT id FROM classes WHERE is_system_default = true LIMIT 1)"
        )
        op.alter_column(table, 'class_id', nullable=False)
        op.create_foreign_key(
            f'fk_{table}_class_id', table, 'classes',
            ['class_id'], ['id'],
        )
        op.create_index(f'ix_{table}_class_id', table, ['class_id'])


def downgrade() -> None:
    for table in TXN_TABLES:
        op.drop_index(f'ix_{table}_class_id', table_name=table)
        op.drop_constraint(f'fk_{table}_class_id', table, type_='foreignkey')
        op.drop_column(table, 'class_id')
    op.drop_table('classes')
