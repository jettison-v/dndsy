"""Your notes, round 2 (Nov 7, feedback 54): the DM's optional word to a story note's author when deciding it

Revision ID: f7b9d1e3a5c6
Revises: e6a8c0d2f4b5
"""

import sqlalchemy as sa
from alembic import op

revision = "f7b9d1e3a5c6"
down_revision = "e6a8c0d2f4b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("facts", "suggestions"):
        op.add_column(table, sa.Column("reply", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    for table in ("facts", "suggestions"):
        op.drop_column(table, "reply")
