"""Session Story (Nov 7, docs/mockups/session-story/): the cleaned transcript kept in file storage, who talked, the
speaker names matched to people, and a recap version's full tale, awards and the tale's narration

Revision ID: a1c3e5f7b9d2
Revises: f7b9d1e3a5c6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a1c3e5f7b9d2"
down_revision = "f7b9d1e3a5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("game_sessions", sa.Column("transcript_key", sa.String(200), sa.ForeignKey("stored_files.key"), nullable=True))
    op.add_column("game_sessions", sa.Column("talk", JSONB(), nullable=False, server_default="{}"))
    op.add_column("campaigns", sa.Column("speakers", JSONB(), nullable=False, server_default="{}"))
    op.add_column("recaps", sa.Column("tale", JSONB(), nullable=False, server_default="[]"))
    op.add_column("recaps", sa.Column("awards", JSONB(), nullable=False, server_default="[]"))
    op.add_column("recaps", sa.Column("tale_narration_key", sa.String(200), sa.ForeignKey("stored_files.key"), nullable=True))


def downgrade() -> None:
    op.drop_column("recaps", "tale_narration_key")
    op.drop_column("recaps", "awards")
    op.drop_column("recaps", "tale")
    op.drop_column("campaigns", "speakers")
    op.drop_column("game_sessions", "talk")
    op.drop_column("game_sessions", "transcript_key")
