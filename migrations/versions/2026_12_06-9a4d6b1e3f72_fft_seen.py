"""Found, Fixed, Tried: when each person last opened an issue, so its new lines are marked (Brett's round, Nov 18)

Revision ID: 9a4d6b1e3f72
Revises: 7c1e4f2a9d30
Create Date: 2026-12-06
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9a4d6b1e3f72"
down_revision: str | Sequence[str] | None = "7c1e4f2a9d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fft_seen",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("workspace_id", sa.Integer, nullable=False, server_default="1"),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("issue_id", sa.Integer, sa.ForeignKey("fft_issues.id", ondelete="CASCADE"), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "issue_id"),
    )
    op.create_index("ix_fft_seen_issue_id", "fft_seen", ["issue_id"])


def downgrade() -> None:
    op.drop_index("ix_fft_seen_issue_id", table_name="fft_seen")
    op.drop_table("fft_seen")
