"""What Brett says in chat, saved as it arrives (fft_chats; Roadmap item 42, his pick 2A on Talking both ways). Only adds.

Revision ID: c28a4e6f7b10
Revises: b17f3d5e6a09
"""

import sqlalchemy as sa
from alembic import op

revision = "c28a4e6f7b10"
down_revision = "b17f3d5e6a09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fft_chats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("words", sa.Text(), nullable=False),
        sa.Column("session", sa.String(64), nullable=False, server_default=""),
        sa.Column("said_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("filed_as", sa.String(10), nullable=False, server_default=""),
        sa.Column("filed_id", sa.Integer(), nullable=True),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fft_chats")
