"""airline_programs + airline_program_memberships + airline_miles_snapshots

Revision ID: k3b4c5d6e7f8
Revises: j2a3b4c5d6e7
Create Date: 2026-05-08 00:00:00.000000

Phase 1.5 task 2 — household airline-miles tracker. Models loyalty
programs (AAdvantage, SkyMiles, ...) as first-class rows so brand
metadata (colour, logo) lives in one place rather than being
duplicated across each person's membership row.

Three-table shape:
  airline_programs              one row per loyalty programme
  airline_program_memberships   one row per (programme, person)
  airline_miles_snapshots       one row per (membership, as-of date)

The split between memberships and snapshots mirrors balance_snapshots
deliberately — the user wants a points history over time, not just a
current balance, and re-entering a balance for the same date should
overwrite rather than fail (same upsert pattern as the balance form).

FK choices:
  airline_program_memberships.program_id ON DELETE RESTRICT
    deleting a programme while memberships exist should fail loudly;
    the user must transfer or delete those memberships first.
  airline_program_memberships.person_id  ON DELETE RESTRICT
    matches the rule on account_ownerships — deleting a person who
    still has miles balances is almost certainly a mistake.
  airline_miles_snapshots.membership_id  ON DELETE CASCADE
    snapshots have no meaning without their parent membership; if a
    membership is removed, the history goes with it.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'k3b4c5d6e7f8'
down_revision: Union[str, None] = 'j2a3b4c5d6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. airline_programs
    # ------------------------------------------------------------------
    # `code` is the URL-safe slug used to reference logo files in
    # /static/airline_logos/<code>.<ext>. Held unique so the slug stays
    # a stable identifier even if `name` is later edited for typos.
    op.create_table(
        'airline_programs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        # alliance values: 'oneworld' / 'star' / 'skyteam' / 'none'.
        # CHECK constraint rather than ENUM type — same rationale as
        # people.role (cheaper to extend later).
        sa.Column('alliance', sa.Text(), nullable=False, server_default='none'),
        # brand_color: 7-char hex string (#rrggbb) including the leading
        # hash. The UI passes this straight into a CSS custom property
        # on each card so styling stays data-driven without per-program
        # CSS edits.
        sa.Column('brand_color', sa.Text(), nullable=False),
        # logo_path: relative to /static, e.g. 'airline_logos/aadvantage.jpeg'.
        # Nullable so a program can be created before its logo is uploaded.
        sa.Column('logo_path', sa.Text(), nullable=True),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        'uq_airline_programs_code', 'airline_programs', ['code'],
    )
    op.create_check_constraint(
        'ck_airline_programs_alliance_values', 'airline_programs',
        "alliance IN ('oneworld', 'star', 'skyteam', 'none')",
    )

    # ------------------------------------------------------------------
    # 2. airline_program_memberships
    # ------------------------------------------------------------------
    # member_number is nullable because the household wants to track
    # programmes a person hasn't joined yet (placeholder rows show up
    # blank in the UI as "no membership"). Same for elite_status.
    op.create_table(
        'airline_program_memberships',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('program_id', sa.Integer(),
                  sa.ForeignKey('airline_programs.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        sa.Column('person_id', sa.Integer(),
                  sa.ForeignKey('people.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        sa.Column('member_number', sa.Text(), nullable=True),
        sa.Column('elite_status', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        'uq_airline_program_memberships_program_person',
        'airline_program_memberships',
        ['program_id', 'person_id'],
    )

    # ------------------------------------------------------------------
    # 3. airline_miles_snapshots
    # ------------------------------------------------------------------
    # balance is BIGINT (some programmes accrue 8-figure point totals
    # via credit-card transfers; a plain INT tops out at 2.1B which is
    # plenty in practice but BIGINT is two extra bytes for peace of mind).
    op.create_table(
        'airline_miles_snapshots',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('membership_id', sa.Integer(),
                  sa.ForeignKey('airline_program_memberships.id',
                                ondelete='CASCADE'),
                  nullable=False, index=True),
        sa.Column('as_of_date', sa.Date(), nullable=False),
        sa.Column('balance', sa.BigInteger(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        'uq_airline_miles_snapshots_membership_date',
        'airline_miles_snapshots',
        ['membership_id', 'as_of_date'],
    )
    op.create_check_constraint(
        'ck_airline_miles_snapshots_balance_nonneg',
        'airline_miles_snapshots',
        'balance >= 0',
    )


def downgrade() -> None:
    # Drop in FK-dependency order: snapshots → memberships → programs.
    op.drop_table('airline_miles_snapshots')
    op.drop_table('airline_program_memberships')
    op.drop_table('airline_programs')
