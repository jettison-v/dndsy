"""character_downs: a character dropping to 0 Hit Points or reaching three failed death saves, from Nov 10 on
(app/downs.py; Brett: record them for Trophy Case)

Revision ID: a7c9e1f3b5d6
Revises: f6b8d0e2a4c5
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c9e1f3b5d6"
down_revision = "f6b8d0e2a4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "character_downs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_character_downs_character_id", "character_downs", ["character_id"])
    op.create_index("ix_character_downs_at", "character_downs", ["at"])


def downgrade() -> None:
    op.drop_index("ix_character_downs_at", "character_downs")
    op.drop_index("ix_character_downs_character_id", "character_downs")
    op.drop_table("character_downs")
