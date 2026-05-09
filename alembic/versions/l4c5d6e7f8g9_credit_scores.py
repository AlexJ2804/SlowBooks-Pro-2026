"""credit_scores table — phase 1.5 task 3

Revision ID: l4c5d6e7f8g9
Revises: k3b4c5d6e7f8
Create Date: 2026-05-09 00:00:00.000000

One row per (person, bureau, score_model, as_of_date) reading. The
unique tuple includes score_model so a parent can record both their
FICO 8 and their VantageScore on the same day from the same bureau
without colliding — useful when comparing how the two models view
the same credit file.

Bureau and score range are guarded at the DB level so raw-SQL inserts
that bypass the API can't introduce typos like 'TransUion' or scores
of 8500 from a misplaced decimal.

Role-gating (parents only) lives in the route handler rather than the
DB or the schema, because the rule needs a join into people.role and
because the validation message wants to be explicit about *why* the
insert was rejected.

ON DELETE RESTRICT on person_id matches the airline-miles convention:
deleting a person while their credit history is still on file should
fail loudly so the user has to confirm they really want the data gone.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'l4c5d6e7f8g9'
down_revision: Union[str, None] = 'k3b4c5d6e7f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'credit_scores',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('person_id', sa.Integer(),
                  sa.ForeignKey('people.id', ondelete='RESTRICT'),
                  nullable=False, index=True),
        # bureau values: 'Equifax' / 'Experian' / 'TransUnion'. Stored
        # capitalized to match how the bureaus brand themselves; the
        # CHECK constraint and the schema enum are kept in sync.
        sa.Column('bureau', sa.Text(), nullable=False),
        sa.Column('score', sa.Integer(), nullable=False),
        # score_model is freeform but defaults to FICO 8, the most-
        # commonly-quoted model. Common values surfaced as datalist
        # suggestions in the UI: 'FICO 8', 'FICO 9', 'VantageScore 3.0'.
        sa.Column('score_model', sa.Text(), nullable=False,
                  server_default='FICO 8'),
        sa.Column('as_of_date', sa.Date(), nullable=False),
        sa.Column('source', sa.Text(), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_check_constraint(
        'ck_credit_scores_bureau_values', 'credit_scores',
        "bureau IN ('Equifax', 'Experian', 'TransUnion')",
    )
    op.create_check_constraint(
        'ck_credit_scores_score_range', 'credit_scores',
        'score >= 300 AND score <= 850',
    )
    op.create_unique_constraint(
        'uq_credit_scores_person_bureau_model_date', 'credit_scores',
        ['person_id', 'bureau', 'score_model', 'as_of_date'],
    )


def downgrade() -> None:
    op.drop_table('credit_scores')
