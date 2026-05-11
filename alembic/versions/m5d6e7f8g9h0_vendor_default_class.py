"""vendors.default_class_id — per-vendor class fallback

Revision ID: m5d6e7f8g9h0
Revises: l4c5d6e7f8g9
Create Date: 2026-05-09 00:00:00.000000

Adds a nullable default_class_id FK from vendors → classes. The IIF
importer falls back to this value when an incoming TRNS/SPL block has
no CLASS column, so vendors that should always tag against a single
class (TJX/Menards/Home Depot/etc. → "Airbnb income from US Home")
auto-tag without needing every IIF row to carry the CLASS explicitly.

Nullable + ON DELETE SET NULL: a class deletion shouldn't fail because
a vendor is pointing at it; the vendor just loses its default and falls
back to Uncategorized like any other untagged bill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'm5d6e7f8g9h0'
down_revision: Union[str, None] = 'l4c5d6e7f8g9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'vendors',
        sa.Column('default_class_id', sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        'fk_vendors_default_class_id_classes',
        'vendors', 'classes',
        ['default_class_id'], ['id'],
        ondelete='SET NULL',
    )
    op.create_index(
        'ix_vendors_default_class_id', 'vendors', ['default_class_id'],
    )


def downgrade() -> None:
    op.drop_index('ix_vendors_default_class_id', table_name='vendors')
    op.drop_constraint(
        'fk_vendors_default_class_id_classes', 'vendors', type_='foreignkey',
    )
    op.drop_column('vendors', 'default_class_id')
