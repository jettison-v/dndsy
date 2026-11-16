"""feedback.title: a short title Claude writes when it takes a note up (Brett, Nov 16); "" until then.

Revision ID: a7c9e1f3b5d8
Revises: f5b7d9e1a3c6
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c9e1f3b5d8"
down_revision = "f5b7d9e1a3c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("title", sa.String(120), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("feedback", "title")
