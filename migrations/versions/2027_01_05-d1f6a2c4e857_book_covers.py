"""A rule book's cover (entity_pictures.book; issue 117). Only adds.

Revision ID: d1f6a2c4e857
Revises: c9e5f1b3d746
"""

import sqlalchemy as sa
from alembic import op

revision = "d1f6a2c4e857"
down_revision = "c9e5f1b3d746"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entity_pictures", sa.Column("book", sa.String(20), nullable=True))
    op.create_unique_constraint("uq_entity_pictures_book", "entity_pictures", ["book"])


def downgrade() -> None:
    op.drop_constraint("uq_entity_pictures_book", "entity_pictures", type_="unique")
    op.drop_column("entity_pictures", "book")
