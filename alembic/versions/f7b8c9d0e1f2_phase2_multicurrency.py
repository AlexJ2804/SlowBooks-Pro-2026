"""phase 2 multi-currency: bills/payments/bill_payments + journal-line home currency

Revision ID: f7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-04-30 14:00:00.000000

This phase makes the journal currency-aware so the P&L and balance sheet are
correct for non-USD activity. We add document-level currency to bills, customer
payments, and bill payments, plus journal-line home-currency columns
(home_currency_debit/credit on transaction_lines) and source-currency columns
on transactions (used by cc_charges and other journal-only flows).

Existing rows are backfilled USD/1, with home_currency_amount = the native
total/amount on each table and home_currency_debit/credit = native debit/credit
on transaction_lines.

Known data caveat: a single EUR test invoice for "Dublin Test Co" exists in
phase 1 dev data. Its journal lines were posted in EUR but will be backfilled
as if USD by this migration. Per Alex, that invoice is being deleted and
recreated post-migration, so no recompute script is included.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f7b8c9d0e1f2'
down_revision: Union[str, None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_currency_triple(table: str, native_amount_col: str) -> None:
    op.add_column(table, sa.Column('currency', sa.String(3), server_default='USD', nullable=False))
    op.add_column(table, sa.Column('exchange_rate', sa.Numeric(18, 8), server_default='1', nullable=False))
    op.add_column(table, sa.Column('home_currency_amount', sa.Numeric(12, 2), server_default='0', nullable=False))
    op.execute(
        f"UPDATE {table} SET currency='USD', exchange_rate=1, "
        f"home_currency_amount={native_amount_col}"
    )


def upgrade() -> None:
    # Document-level currency triples (same pattern as phase 1 invoices).
    _add_currency_triple('bills', 'total')
    _add_currency_triple('payments', 'amount')
    _add_currency_triple('bill_payments', 'amount')

    # Transaction-level currency for journal-only flows (cc_charges, manual
    # journal entries, deposits) so the source currency can be displayed even
    # when there's no document row to attach it to.
    op.add_column('transactions', sa.Column('currency', sa.String(3), server_default='USD', nullable=False))
    op.add_column('transactions', sa.Column('exchange_rate', sa.Numeric(18, 8), server_default='1', nullable=False))
    op.execute("UPDATE transactions SET currency='USD', exchange_rate=1")

    # Journal-line home-currency amounts. Backfilled equal to native amounts
    # under the assumption that all historical activity was USD-denominated
    # (which matches phase 1's invoice backfill).
    op.add_column('transaction_lines', sa.Column('home_currency_debit', sa.Numeric(12, 2), server_default='0', nullable=False))
    op.add_column('transaction_lines', sa.Column('home_currency_credit', sa.Numeric(12, 2), server_default='0', nullable=False))
    op.execute("UPDATE transaction_lines SET home_currency_debit=debit, home_currency_credit=credit")


def downgrade() -> None:
    op.drop_column('transaction_lines', 'home_currency_credit')
    op.drop_column('transaction_lines', 'home_currency_debit')
    op.drop_column('transactions', 'exchange_rate')
    op.drop_column('transactions', 'currency')
    for table in ('bill_payments', 'payments', 'bills'):
        op.drop_column(table, 'home_currency_amount')
        op.drop_column(table, 'exchange_rate')
        op.drop_column(table, 'currency')
