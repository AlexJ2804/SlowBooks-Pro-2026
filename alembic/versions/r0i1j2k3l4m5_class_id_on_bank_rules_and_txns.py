"""bank_rules.class_id + bank_transactions.class_id

Revision ID: r0i1j2k3l4m5
Revises: q9h0i1j2k3l4
Create Date: 2026-05-11 14:00:00.000000

Per-business class tagging for the categorize loop. Lets a single
BankRule mark matching transactions with BOTH a category (which COA
line they hit) AND a class (which business / income source they
belong to). The spending dashboard can then slice by class so Alex
Music / Alexa VIPKid / Alex Consulting / etc. show separate totals.

Both columns are nullable — a rule without a class_id is "no business
attribution" (the implicit default for personal/household txns), and
a transaction without a class_id either pre-dates this migration or
matches a class-less rule.

ON DELETE SET NULL on the FKs so deleting a class doesn't cascade
into wiping bank_rules / bank_transactions. The class table is small
and edits go through the UI; we never want a delete to silently
zero out rule history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'r0i1j2k3l4m5'
down_revision: Union[str, None] = 'q9h0i1j2k3l4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'bank_rules',
        sa.Column('class_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_bank_rules_class_id',
        'bank_rules', 'classes',
        ['class_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_bank_rules_class_id', 'bank_rules', ['class_id'])

    op.add_column(
        'bank_transactions',
        sa.Column('class_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_bank_transactions_class_id',
        'bank_transactions', 'classes',
        ['class_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index('ix_bank_transactions_class_id', 'bank_transactions', ['class_id'])


def downgrade() -> None:
    op.drop_index('ix_bank_transactions_class_id', table_name='bank_transactions')
    op.drop_constraint('fk_bank_transactions_class_id', 'bank_transactions', type_='foreignkey')
    op.drop_column('bank_transactions', 'class_id')

    op.drop_index('ix_bank_rules_class_id', table_name='bank_rules')
    op.drop_constraint('fk_bank_rules_class_id', 'bank_rules', type_='foreignkey')
    op.drop_column('bank_rules', 'class_id')
