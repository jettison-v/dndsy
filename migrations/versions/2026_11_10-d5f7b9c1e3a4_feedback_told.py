"""A feedback note remembers what its sender was last told about it (Your feedback, Nov 7)

Revision ID: d5f7b9c1e3a4
Revises: c4e6a8b0d2f1
"""

import sqlalchemy as sa
from alembic import op

revision = "d5f7b9c1e3a4"
down_revision = "c4e6a8b0d2f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("told", sa.String(40), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("feedback", "told")
