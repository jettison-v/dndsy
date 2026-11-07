"""A key moment can be major: the ones Story shows first (feedback 40, Nov 7)

Revision ID: c4e6a8b0d2f1
Revises: b7d9f1a3c5e2
"""

import sqlalchemy as sa
from alembic import op

revision = "c4e6a8b0d2f1"
down_revision = "b7d9f1a3c5e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("story_events", sa.Column("major", sa.Boolean, nullable=True))


def downgrade() -> None:
    op.drop_column("story_events", "major")
