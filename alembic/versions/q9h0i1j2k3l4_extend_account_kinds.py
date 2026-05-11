"""Extend accounts.account_kind enum for personal/business P&L sub-types.

Revision ID: q9h0i1j2k3l4
Revises: p8g9h0i1j2k3
Create Date: 2026-05-11 12:00:00.000000

Phase 3 — spending analytics. The existing kind enum covered balance-
sheet sub-types only (bank, credit_card, brokerage, retirement,
property, loan). This adds P&L sub-types so we can distinguish personal
vs business expense / income, and explicitly mark "transfer" pseudo-
categories that shouldn't be summed into the spending total.

New values:
    personal_expense   — household spending (groceries, restaurants, …)
    business_expense   — business operating costs
    personal_income    — salary, refunds, personal investment income
    business_income    — revenue from a business
    transfer           — non-expense pseudo-categories (CC payment,
                         currency exchange, account top-up). These are
                         account_type=expense on the schema but the
                         spending dashboard excludes them from "where
                         did our money go" so the totals stay honest.

Backfills existing expense / income accounts whose account_number falls
in the QB business range (4xxx for income, 6xxx for expense) as
business_*. Conservatively scoped — only touches rows whose account_kind
is currently NULL, and only those numbered < 7000, so the 7000-range
personal seeds (if already inserted by an earlier version of
scripts/seed_personal_expense_categories.py) are left for the updated
seed to patch.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'q9h0i1j2k3l4'
down_revision: Union[str, None] = 'p8g9h0i1j2k3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_OLD_VALUES = ('bank', 'credit_card', 'brokerage', 'retirement', 'property', 'loan')
_NEW_VALUES = _OLD_VALUES + (
    'personal_expense',
    'business_expense',
    'personal_income',
    'business_income',
    'transfer',
)


def _kind_in_clause(values):
    return f"({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.drop_constraint('ck_accounts_kind_values', 'accounts', type_='check')
    op.create_check_constraint(
        'ck_accounts_kind_values',
        'accounts',
        f"account_kind IS NULL OR account_kind IN {_kind_in_clause(_NEW_VALUES)}",
    )

    # Backfill existing 4xxx-range income accounts (QB-default chart).
    # Conservative: only NULL kinds, only sub-7000 numbers, so 7000-range
    # personal seeds are left untouched.
    #
    # NB: SQLAlchemy built the accounttype PG enum from the AccountType
    # enum's NAMES (uppercase), not its lowercase string values. Comparing
    # account_type against 'income' raises
    # psycopg2.errors.InvalidTextRepresentation; cast to ::text first and
    # compare against the uppercase name.
    op.execute(
        "UPDATE accounts SET account_kind = 'business_income' "
        "WHERE account_type::text = 'INCOME' "
        "AND account_kind IS NULL "
        "AND (account_number LIKE '4%' OR account_number IS NULL)"
    )
    op.execute(
        "UPDATE accounts SET account_kind = 'business_expense' "
        "WHERE account_type::text IN ('EXPENSE', 'COGS') "
        "AND account_kind IS NULL "
        "AND (account_number LIKE '5%' OR account_number LIKE '6%' OR account_number IS NULL)"
    )


def downgrade() -> None:
    # Clear any new values so the tightened constraint below will hold.
    op.execute(
        "UPDATE accounts SET account_kind = NULL "
        "WHERE account_kind IN ("
        "'personal_expense', 'business_expense', "
        "'personal_income', 'business_income', 'transfer'"
        ")"
    )
    op.drop_constraint('ck_accounts_kind_values', 'accounts', type_='check')
    op.create_check_constraint(
        'ck_accounts_kind_values',
        'accounts',
        f"account_kind IS NULL OR account_kind IN {_kind_in_clause(_OLD_VALUES)}",
    )
