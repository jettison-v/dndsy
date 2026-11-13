"""characters.sheet_seen_at: when its player's extension last heard its D&D Beyond sheet, kept after the sheet closes
(sheet_heard_at is cleared then), so askdnd can tell a connection that just got worse from one never made tonight
(Brett, Nov 13, docs/mockups/connection-drops/: a player closed their sheet mid-session and nothing told them)

Revision ID: c9e1a3b5d7f8
Revises: b8d0f2a4c6e7
"""

import sqlalchemy as sa
from alembic import op

revision = "c9e1a3b5d7f8"
down_revision = "b8d0f2a4c6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("characters", sa.Column("sheet_seen_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("characters", "sheet_seen_at")
