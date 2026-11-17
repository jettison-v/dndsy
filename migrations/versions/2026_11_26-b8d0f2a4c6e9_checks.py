"""checks: Testing in askdnd (Brett's picks, Nov 16, docs/mockups/testing/): a check for an admin to try, why it
exists and where it stands.

Revision ID: b8d0f2a4c6e9
Revises: a7c9e1f3b5d8
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "b8d0f2a4c6e9"
down_revision = "a7c9e1f3b5d8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checks",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("area", sa.String(80), nullable=False, server_default=""),
        sa.Column("setup", sa.String(20), nullable=False, server_default="laptop"),
        sa.Column("as_who", sa.String(120), nullable=False, server_default=""),
        sa.Column("path", sa.String(500), nullable=False, server_default=""),
        sa.Column("do", sa.Text, nullable=False, server_default=""),
        sa.Column("expect", sa.Text, nullable=False, server_default=""),
        sa.Column("minutes", sa.Integer, nullable=False, server_default="1"),
        sa.Column("place", sa.Integer, nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ready"),
        sa.Column("feedback_id", sa.Integer, sa.ForeignKey("feedback.id", ondelete="SET NULL"), nullable=True),
        sa.Column("failed_id", sa.Integer, sa.ForeignKey("feedback.id", ondelete="SET NULL"), nullable=True),
        sa.Column("pr", sa.String(300), nullable=False, server_default=""),
        sa.Column("said", sa.Text, nullable=False, server_default=""),
        sa.Column("history", JSONB, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_checks_status", "checks", ["status"])


def downgrade() -> None:
    op.drop_index("ix_checks_status", "checks")
    op.drop_table("checks")
