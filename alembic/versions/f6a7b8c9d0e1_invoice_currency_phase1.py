"""invoice multi-currency phase 1: currency, exchange_rate, home_currency_amount on invoices; home_currency setting

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-04-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a7b8c9d0e1'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('invoices', sa.Column('currency', sa.String(3), server_default='USD', nullable=False))
    op.add_column('invoices', sa.Column('exchange_rate', sa.Numeric(18, 8), server_default='1', nullable=False))
    op.add_column('invoices', sa.Column('home_currency_amount', sa.Numeric(12, 2), server_default='0', nullable=False))

    # Backfill: existing rows are USD-based history per the migration spec.
    op.execute("UPDATE invoices SET currency='USD', exchange_rate=1, home_currency_amount=total")

    # Seed home_currency setting (settings is a key/value table).
    op.execute(
        "INSERT INTO settings (key, value) VALUES ('home_currency', 'USD') "
        "ON CONFLICT (key) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("DELETE FROM settings WHERE key='home_currency'")
    op.drop_column('invoices', 'home_currency_amount')
    op.drop_column('invoices', 'exchange_rate')
    op.drop_column('invoices', 'currency')
