"""Available: a change waiting for Brett's try on his Mac (fft_local_tries)

Revision ID: 7b5e3c1d9a42
Revises: 4e2b7d9c1a63
Create Date: 2026-12-09

Only adds a table (database changes only add).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "7b5e3c1d9a42"
down_revision: str | Sequence[str] | None = "4e2b7d9c1a63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fft_local_tries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, nullable=False, server_default="1", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("area_id", sa.Integer, sa.ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("pr", sa.String(300), nullable=False, server_default=""),
        sa.Column("changed", JSONB, nullable=False, server_default="[]"),
        sa.Column("look_at", sa.Text, nullable=False, server_default=""),
        sa.Column("path", sa.String(300), nullable=False, server_default="/"),
        sa.Column("answer", sa.String(8), nullable=False, server_default=""),
        sa.Column("words", sa.Text, nullable=False, server_default=""),
        sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fft_local_tries")
