"""A person's race and class (Nov 7, Brett: "very helpful for generating images"), kept on their World entry

Revision ID: b2d4f6a8c0e1
Revises: a1c3e5f7b9d2
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "b2d4f6a8c0e1"
down_revision = "a1c3e5f7b9d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("entities", sa.Column("traits", JSONB(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("entities", "traits")
