"""checks.asked_at: when a check came back to be tried (Try again: fixed and live). A player's three days and the
fix-to-try email count from it, not from any later edit (the code review, Nov 16).

Revision ID: d0f2b4c6e8a1
Revises: c9e1a3b5d7f0
"""

import sqlalchemy as sa
from alembic import op

revision = "d0f2b4c6e8a1"
down_revision = "c9e1a3b5d7f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("checks", sa.Column("asked_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE checks SET asked_at = updated_at WHERE status = 'again'")


def downgrade() -> None:
    op.drop_column("checks", "asked_at")
