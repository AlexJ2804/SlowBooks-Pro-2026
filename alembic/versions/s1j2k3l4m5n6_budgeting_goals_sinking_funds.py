"""Budgeting: pay_sources + sinking_funds + goals (Phase 1, Task 1B)

Revision ID: s1j2k3l4m5n6
Revises: r0i1j2k3l4m5
Create Date: 2026-06-13 18:00:00.000000

Standalone budgeting tables (the existing `budgets` table is a monthly
account-grid for budget-vs-actual; it does not model funding cadence,
savings goals, or virtual envelopes, so Goals/Sinking Funds stand alone).

Design notes:
  * Canonical stored unit is the MONTHLY contribution. We store natural
    inputs (bill amount + frequency / target + date) and derive monthly
    and per-paycheck figures in app/services/budget_calc.py. No
    per-paycheck amount is ever persisted.
  * Virtual-envelope model: sinking_funds.current_balance and
    goals.current_saved are notional balances held inside the real
    `linked_account_id` account.

Seeds two pay_sources so the household's cadences exist out of the box:
  Alex  = biweekly (26 periods/yr)
  Alexa = monthly  (12 periods/yr)
net_per_check is left NULL on both (entered later via the UI). Names +
cadence are structural config, not personal financial figures.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 's1j2k3l4m5n6'
down_revision: Union[str, None] = 'r0i1j2k3l4m5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'pay_sources',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('cadence', sa.String(20), nullable=False),
        sa.Column('periods_per_year', sa.Integer(), nullable=False),
        sa.Column('net_per_check', sa.Numeric(12, 2), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        'ck_pay_sources_cadence_values', 'pay_sources',
        "cadence IN ('weekly', 'biweekly', 'semimonthly', 'monthly')",
    )
    op.create_check_constraint(
        'ck_pay_sources_periods_values', 'pay_sources',
        "periods_per_year IN (52, 26, 24, 12)",
    )

    op.create_table(
        'sinking_funds',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('bill_periods_per_year', sa.Integer(), nullable=False),
        sa.Column('next_due', sa.Date(), nullable=True),
        sa.Column('current_balance', sa.Numeric(12, 2),
                  nullable=False, server_default='0'),
        sa.Column('linked_account_id', sa.Integer(),
                  sa.ForeignKey('accounts.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('funding_source_id', sa.Integer(),
                  sa.ForeignKey('pay_sources.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('currency', sa.String(3),
                  nullable=False, server_default='USD'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        'ck_sinking_funds_bill_periods_values', 'sinking_funds',
        "bill_periods_per_year IN (1, 2, 4, 12)",
    )

    op.create_table(
        'goals',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False),
        sa.Column('target_amount', sa.Numeric(12, 2), nullable=False),
        sa.Column('target_date', sa.Date(), nullable=False),
        sa.Column('current_saved', sa.Numeric(12, 2),
                  nullable=False, server_default='0'),
        sa.Column('linked_account_id', sa.Integer(),
                  sa.ForeignKey('accounts.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('funding_source_id', sa.Integer(),
                  sa.ForeignKey('pay_sources.id', ondelete='SET NULL'),
                  nullable=True, index=True),
        sa.Column('currency', sa.String(3),
                  nullable=False, server_default='USD'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )

    # Seed the two household pay cadences (idempotent on name). net_per_check
    # left NULL — entered via the UI later.
    pay_sources = sa.table(
        'pay_sources',
        sa.column('name', sa.String),
        sa.column('cadence', sa.String),
        sa.column('periods_per_year', sa.Integer),
    )
    op.bulk_insert(pay_sources, [
        {"name": "Alex", "cadence": "biweekly", "periods_per_year": 26},
        {"name": "Alexa", "cadence": "monthly", "periods_per_year": 12},
    ])


def downgrade() -> None:
    op.drop_table('goals')
    op.drop_table('sinking_funds')
    op.drop_table('pay_sources')
