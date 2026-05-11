"""bank_transactions.currency — per-row currency for multi-ccy accounts

Revision ID: p8g9h0i1j2k3
Revises: o7f8g9h0i1j2
Create Date: 2026-05-10 00:00:00.000000

Adds a nullable varchar(3) currency column to bank_transactions so a
single bank_account can hold transactions in multiple currencies. This
is needed for Revolut-style multi-currency accounts where the same
ledger contains EUR purchases, CZK vault transfers, GBP card payments,
etc.

NULL means "use the parent bank_account's native currency" — preserves
backward-compat for the ~540 existing single-currency rows (Citi, HCU,
etc.) which all sum cleanly in USD.

For dedup purposes the currency joins (date, amount, normalised
description) in the fingerprint so a CZK 50.00 charge on the same day
as a EUR 50.00 charge no longer collapses to one row.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'p8g9h0i1j2k3'
down_revision: Union[str, None] = 'o7f8g9h0i1j2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bank_transactions',
        sa.Column('currency', sa.String(length=3), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('bank_transactions', 'currency')
