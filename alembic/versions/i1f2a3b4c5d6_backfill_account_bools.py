"""backfill NULL is_system/is_active on accounts + add server_defaults + NOT NULL

Revision ID: i1f2a3b4c5d6
Revises: h0e1f2a3b4c5
Create Date: 2026-05-04 11:30:00.000000

Closes a latent dirty-data path that surfaced when the May-2026
IIF-bootstrap SQL inserted accounts without specifying is_system.
The Account model declares `default=False` Python-side only — there
was no `server_default`, so Postgres stored NULL on those inserts.
The /api/accounts route's Pydantic AccountResponse then 500'd because
`is_system: bool` rejected None.

Schema fix:
1. Backfill any existing NULL is_system → FALSE, NULL is_active → TRUE.
2. Add `server_default` ('false' / 'true') so future raw SQL inserts
   that omit these columns get a sane default rather than NULL.
3. Set NOT NULL — column was implicitly nullable before; pin the
   constraint so dirty rows can't reappear.

The Account model is updated in the same commit to declare the
matching server_defaults, keeping the SQLAlchemy metadata and the
actual Postgres schema in sync.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'i1f2a3b4c5d6'
down_revision: Union[str, None] = 'h0e1f2a3b4c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Backfill first — alter to NOT NULL would fail if any rows still hold NULL.
    op.execute("UPDATE accounts SET is_system = FALSE WHERE is_system IS NULL")
    op.execute("UPDATE accounts SET is_active = TRUE WHERE is_active IS NULL")

    op.alter_column(
        'accounts', 'is_system',
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.text('false'),
    )
    op.alter_column(
        'accounts', 'is_active',
        existing_type=sa.Boolean(),
        nullable=False,
        server_default=sa.text('true'),
    )


def downgrade() -> None:
    # Revert nullability + drop server defaults. Doesn't restore NULLs
    # (we don't track which rows were originally NULL); the data
    # backfill is intentionally a one-way operation.
    op.alter_column(
        'accounts', 'is_active',
        existing_type=sa.Boolean(),
        nullable=True,
        server_default=None,
    )
    op.alter_column(
        'accounts', 'is_system',
        existing_type=sa.Boolean(),
        nullable=True,
        server_default=None,
    )
