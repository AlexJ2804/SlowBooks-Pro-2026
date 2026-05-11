"""net worth phase 1 — ownership pcts, account_kind, update_strategy, loans, balance_snapshots

Revision ID: h0e1f2a3b4c5
Revises: g8c9d0e1f2g3
Create Date: 2026-05-04 00:00:00.000000

Phase 1 of multi-account financial tracking + net worth dashboard.

Schema changes:
1. Five new columns on `accounts`:
   - alex_pct, alexa_pct, kids_pct INT NOT NULL DEFAULT 0 (household ownership)
   - account_kind VARCHAR(20) NULL (bank/credit_card/brokerage/retirement/property/loan)
   - update_strategy VARCHAR(20) NULL (transactional/balance_only)

2. Three new tables:
   - loans (1:1 with accounts.kind=loan; carries amortization params)
   - loan_amortization_schedule (per-payment breakdown; populated lazily by UI)
   - balance_snapshots (manual balance entries; powers the dashboard)

The ownership-pct CHECK is intentionally permissive: allows ALL-zero
(for system Chart of Accounts rows that aren't personally owned) OR
sum-to-100 (for personal accounts seeded in scripts/seed_personal_accounts.py).
That avoids forcing a backfill on the 40+ existing system accounts
while still pinning data integrity for the rows that actually carry
ownership.

account_kind and update_strategy are nullable so existing rows don't
need backfill; the seed script populates them on the 18 personal
accounts it creates. Constrained to a small enum-like set via CHECK
rather than a Postgres ENUM type so adding new kinds later is a
straightforward ALTER rather than enum-type surgery.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'h0e1f2a3b4c5'
down_revision: Union[str, None] = 'g8c9d0e1f2g3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_KIND_VALUES = ('bank', 'credit_card', 'brokerage', 'retirement', 'property', 'loan')
_STRATEGY_VALUES = ('transactional', 'balance_only')


def upgrade() -> None:
    # ------------------------------------------------------------------
    # accounts: ownership pcts + account_kind + update_strategy + currency
    # ------------------------------------------------------------------
    op.add_column('accounts', sa.Column('alex_pct', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('accounts', sa.Column('alexa_pct', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('accounts', sa.Column('kids_pct', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('accounts', sa.Column('account_kind', sa.String(length=20), nullable=True))
    op.add_column('accounts', sa.Column('update_strategy', sa.String(length=20), nullable=True))
    # Native currency of the account (e.g. USD for Heartland Joint Checking,
    # EUR for Revolut IE). Defaults USD to backfill existing rows safely;
    # the seed_personal_accounts.py script overrides it on the personal
    # accounts that aren't USD. Existing system Chart of Accounts rows
    # don't have a meaningful currency — they're abstract income/expense
    # buckets — so USD is fine for them.
    op.add_column('accounts', sa.Column('currency', sa.String(length=3), nullable=False, server_default='USD'))

    # Permissive CHECK: allow all-zero (system accounts not personally owned)
    # OR sum-to-100 (personal accounts). Disallows partial states like 50/30/0.
    op.create_check_constraint(
        'ck_accounts_ownership_pct_total',
        'accounts',
        '(alex_pct = 0 AND alexa_pct = 0 AND kids_pct = 0) '
        'OR (alex_pct + alexa_pct + kids_pct = 100)',
    )
    op.create_check_constraint(
        'ck_accounts_ownership_pct_nonneg',
        'accounts',
        'alex_pct >= 0 AND alexa_pct >= 0 AND kids_pct >= 0',
    )
    op.create_check_constraint(
        'ck_accounts_kind_values',
        'accounts',
        "account_kind IS NULL OR account_kind IN "
        f"({', '.join(repr(v) for v in _KIND_VALUES)})",
    )
    op.create_check_constraint(
        'ck_accounts_update_strategy_values',
        'accounts',
        "update_strategy IS NULL OR update_strategy IN "
        f"({', '.join(repr(v) for v in _STRATEGY_VALUES)})",
    )

    # ------------------------------------------------------------------
    # loans
    # ------------------------------------------------------------------
    op.create_table(
        'loans',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False, index=True),
        sa.Column('asset_account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=True),
        sa.Column('original_amount', sa.Numeric(12, 2), nullable=False),
        # interest_rate stored as annual percentage, e.g. 6.5 means 6.5% APR.
        # NUMERIC(6, 4) accommodates rates like 12.7500 with sub-bp precision.
        sa.Column('interest_rate', sa.Numeric(6, 4), nullable=False),
        sa.Column('term_months', sa.Integer(), nullable=False),
        sa.Column('start_date', sa.Date(), nullable=False),
        sa.Column('monthly_payment', sa.Numeric(12, 2), nullable=False),
        sa.Column('escrow_amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('currency', sa.String(length=3), nullable=False, server_default='USD'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        # One loan row per liability account. UNIQUE so a stray double-insert
        # in the seed or UI fails loudly rather than corrupting the dashboard.
        sa.UniqueConstraint('account_id', name='uq_loans_account_id'),
    )

    # ------------------------------------------------------------------
    # loan_amortization_schedule (initially empty per phase-1 spec)
    # ------------------------------------------------------------------
    op.create_table(
        'loan_amortization_schedule',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('loan_id', sa.Integer(),
                  sa.ForeignKey('loans.id', ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('payment_number', sa.Integer(), nullable=False),
        sa.Column('payment_date', sa.Date(), nullable=False),
        sa.Column('principal_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('interest_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('escrow_amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('remaining_balance', sa.Numeric(12, 2), nullable=False),
        sa.UniqueConstraint('loan_id', 'payment_number', name='uq_loan_amort_loan_payment'),
    )

    # ------------------------------------------------------------------
    # balance_snapshots
    # ------------------------------------------------------------------
    op.create_table(
        'balance_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('account_id', sa.Integer(), sa.ForeignKey('accounts.id'), nullable=False, index=True),
        sa.Column('as_of_date', sa.Date(), nullable=False),
        sa.Column('balance', sa.Numeric(12, 2), nullable=False),
        # Currency denormalized from account so historical snapshots stay
        # accurate if the account's native currency is ever changed.
        sa.Column('currency', sa.String(length=3), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('account_id', 'as_of_date', name='uq_balance_snapshots_account_date'),
    )


def downgrade() -> None:
    op.drop_table('balance_snapshots')
    op.drop_table('loan_amortization_schedule')
    op.drop_table('loans')
    op.drop_constraint('ck_accounts_update_strategy_values', 'accounts', type_='check')
    op.drop_constraint('ck_accounts_kind_values', 'accounts', type_='check')
    op.drop_constraint('ck_accounts_ownership_pct_nonneg', 'accounts', type_='check')
    op.drop_constraint('ck_accounts_ownership_pct_total', 'accounts', type_='check')
    op.drop_column('accounts', 'currency')
    op.drop_column('accounts', 'update_strategy')
    op.drop_column('accounts', 'account_kind')
    op.drop_column('accounts', 'kids_pct')
    op.drop_column('accounts', 'alexa_pct')
    op.drop_column('accounts', 'alex_pct')
