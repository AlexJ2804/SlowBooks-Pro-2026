"""widen bank_accounts.last_four to varchar(20)

Revision ID: o7f8g9h0i1j2
Revises: n6e7f8g9h0i1
Create Date: 2026-05-09 00:00:00.000000

bank_accounts.last_four was sized varchar(4) on the assumption it would
only ever hold the printed last-4 digits of a card. Credit unions like
HCU number their sub-accounts as <member>-<share>, e.g. 75850-0002 for
the joint checking share. Storing those identifiers verbatim is the
clearest way to distinguish the joint checking, joint savings, and
each family member's individual share from the others, so widen to
varchar(20) — enough for any reasonable member-share format with
some headroom.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'o7f8g9h0i1j2'
down_revision: Union[str, None] = 'n6e7f8g9h0i1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        'bank_accounts', 'last_four',
        existing_type=sa.String(length=4),
        type_=sa.String(length=20),
        existing_nullable=True,
    )


def downgrade() -> None:
    # Truncating downgrade: any stored value longer than 4 chars gets
    # cut to its last 4 chars rather than failing the migration. For
    # member-share IDs this preserves the share suffix (e.g.
    # '75850-0002' -> '0002') which is the more distinguishing piece.
    op.execute(
        "UPDATE bank_accounts "
        "SET last_four = RIGHT(last_four, 4) "
        "WHERE last_four IS NOT NULL AND CHAR_LENGTH(last_four) > 4"
    )
    op.alter_column(
        'bank_accounts', 'last_four',
        existing_type=sa.String(length=20),
        type_=sa.String(length=4),
        existing_nullable=True,
    )
