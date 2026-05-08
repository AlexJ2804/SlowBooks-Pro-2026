"""people table + account_ownerships join + data backfill from legacy pct columns

Revision ID: j2a3b4c5d6e7
Revises: i1f2a3b4c5d6
Create Date: 2026-05-04 18:00:00.000000

Phase 1.5 — replace the alex_pct / alexa_pct / kids_pct three-column
ownership model on `accounts` with a proper `people` table plus an
`account_ownerships` join table. The legacy pct columns stay populated
(via dual-write at the application layer) until a follow-up migration
drops them ~1 week after this lands.

Why a join table now: phase 1 hardcoded three slots which doesn't
extend cleanly to per-person miles balances or per-person credit
scores (phase 1.5 tasks 2 + 3). Refactoring before too much code
depends on the three-column shape is cheaper than refactoring later.

THEODORE = kids_pct MAPPING (one-way, historical)
=================================================
At migration time, every existing accounts row with kids_pct > 0 gets
ONE account_ownerships row attributed to person_id=3 (Theodore). The
original kids_pct column was semantically "all kids combined" but the
household has exactly one kid (Theodore) at the time of this migration
so the mapping is lossless for current data.

Anyone reading this in 2 years should understand:
  - Historical migrated rows are correctly attributed to Theodore.
  - Future kid-share splits across multiple children must be entered
    through the join-table UI as separate (account_id, person_id) rows.
  - The legacy kids_pct column will be dropped after this migration is
    stable in production for ~1 week. Until then it's dual-written but
    not authoritative — reads come from account_ownerships.

Sum-to-100 enforcement
======================
We use a deferrable CONSTRAINT TRIGGER (INITIALLY DEFERRED) on
account_ownerships rather than a row-level CHECK because Postgres
CHECK constraints can't reference aggregates across rows. The trigger
fires at COMMIT, so a transaction that DELETEs all rows and INSERTs
new ones is fine as long as the final sum lands at 100 (or 0 for
"system COA, no personal owner"). The exception message identifies the
account and the bad sum to make debugging tractable.

App-level validation in app/schemas/accounts.py mirrors the same rule
for portability with the SQLite test database (tests don't run
migrations; they use Base.metadata.create_all and the trigger doesn't
exist there).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'j2a3b4c5d6e7'
down_revision: Union[str, None] = 'i1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. people
    # ------------------------------------------------------------------
    op.create_table(
        'people',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.Text(), nullable=False),
        # role values: 'parent' / 'child' / 'other'. Restricted via CHECK
        # rather than a Postgres ENUM type so adding new roles later is a
        # straightforward ALTER rather than enum-type surgery (same
        # rationale as account_kind in the phase-1 migration).
        sa.Column('role', sa.Text(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        'ck_people_role_values', 'people',
        "role IN ('parent', 'child', 'other')",
    )

    # Seed three rows with explicit IDs so the data backfill below can
    # reference them by id without lookups, and so application code that
    # references "Alex=1, Alexa=2, Theodore=3" stays predictable.
    # Sequence is reset afterward so future inserts don't collide.
    op.execute(
        "INSERT INTO people (id, name, role, display_order) VALUES "
        "(1, 'Alex', 'parent', 0), "
        "(2, 'Alexa', 'parent', 1), "
        "(3, 'Theodore', 'child', 2)"
    )
    op.execute(
        "SELECT setval(pg_get_serial_sequence('people', 'id'), "
        "(SELECT MAX(id) FROM people))"
    )

    # ------------------------------------------------------------------
    # 2. account_ownerships join table
    # ------------------------------------------------------------------
    # ON DELETE CASCADE on accounts: deleting an account should clean up
    # its ownership rows automatically (orphans serve no purpose).
    # ON DELETE RESTRICT on people: deleting a person while ownership
    # rows reference them should fail loudly — the user must explicitly
    # transfer or delete those rows first.
    op.create_table(
        'account_ownerships',
        sa.Column('account_id', sa.Integer(),
                  sa.ForeignKey('accounts.id', ondelete='CASCADE'),
                  primary_key=True),
        sa.Column('person_id', sa.Integer(),
                  sa.ForeignKey('people.id', ondelete='RESTRICT'),
                  primary_key=True),
        sa.Column('share_pct', sa.Integer(), nullable=False),
    )
    op.create_check_constraint(
        'ck_account_ownerships_share_range', 'account_ownerships',
        'share_pct > 0 AND share_pct <= 100',
    )

    # ------------------------------------------------------------------
    # 3. Data backfill from legacy pct columns
    # ------------------------------------------------------------------
    # One INSERT per non-zero pct column. share_pct=0 produces no row
    # because the row-level CHECK above rejects share_pct=0 anyway and
    # the v1 model used 0 to mean "this person doesn't own a share".
    # System COA accounts (alex_pct=alexa_pct=kids_pct=0) get no rows.
    op.execute("""
        INSERT INTO account_ownerships (account_id, person_id, share_pct)
        SELECT id, 1, alex_pct FROM accounts WHERE alex_pct > 0
        UNION ALL
        SELECT id, 2, alexa_pct FROM accounts WHERE alexa_pct > 0
        UNION ALL
        SELECT id, 3, kids_pct FROM accounts WHERE kids_pct > 0
    """)

    # ------------------------------------------------------------------
    # 4. Sum-to-100 deferrable constraint trigger
    # ------------------------------------------------------------------
    # Per-row trigger fires AFTER each INSERT/UPDATE/DELETE but with
    # DEFERRABLE INITIALLY DEFERRED, the actual SUM check happens at
    # COMMIT. This means a transaction can DELETE all rows for an
    # account and INSERT new ones (the typical "replace ownerships"
    # path from the UI) without a transient bad-sum error mid-tx.
    #
    # Total of 0 is allowed (no rows for an account = system COA,
    # not personally owned). Total in (0, 100) range exclusive is
    # rejected with a message that names the account and the bad sum
    # for debugging.
    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_account_ownership_sum()
        RETURNS trigger AS $$
        DECLARE
            total INT;
            aid INT;
        BEGIN
            aid := COALESCE(NEW.account_id, OLD.account_id);
            SELECT COALESCE(SUM(share_pct), 0) INTO total
            FROM account_ownerships
            WHERE account_id = aid;
            IF total <> 0 AND total <> 100 THEN
                RAISE EXCEPTION
                    'Account % ownership shares must sum to 100, got %',
                    aid, total;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE CONSTRAINT TRIGGER trg_account_ownerships_sum
        AFTER INSERT OR UPDATE OR DELETE ON account_ownerships
        DEFERRABLE INITIALLY DEFERRED
        FOR EACH ROW
        EXECUTE FUNCTION enforce_account_ownership_sum();
    """)


def downgrade() -> None:
    # Order: trigger → function → join table → people. (FK from
    # account_ownerships.person_id → people.id requires the join to
    # drop first.)
    op.execute("DROP TRIGGER IF EXISTS trg_account_ownerships_sum ON account_ownerships")
    op.execute("DROP FUNCTION IF EXISTS enforce_account_ownership_sum()")
    op.drop_table('account_ownerships')
    op.drop_table('people')
