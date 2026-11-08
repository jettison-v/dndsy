"""When a character's copy was last read from the sheet itself (characters.PUBLIC_TRAILS)

Revision ID: c3e5a7b9d1f2
Revises: b2d4f6a8c0e1
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from alembic import op

revision = "c3e5a7b9d1f2"
down_revision = "b2d4f6a8c0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("character_snapshots", sa.Column("sheet_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("character_snapshots", "sheet_at")
