"""Claude's usage readings (fft_usage_readings; Roadmap item 34, Usage Limit Awareness). Only adds.

Revision ID: c9e5f1b3d746
Revises: b8d4f0a2c635
"""

import sqlalchemy as sa
from alembic import op

revision = "c9e5f1b3d746"
down_revision = "b8d4f0a2c635"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fft_usage_readings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("five_hour", sa.Integer(), nullable=False),
        sa.Column("week", sa.Integer(), nullable=False),
        sa.Column("extra_spent", sa.Float(), nullable=False, server_default="0"),
        sa.Column("extra_limit", sa.Float(), nullable=True),
        sa.Column("five_resets_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("week_resets_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner", sa.String(60), nullable=False, server_default=""),
        sa.Column("area_id", sa.Integer(), nullable=True),
        sa.Column("item_id", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(8), nullable=False, server_default="go"),
        sa.Column("why", sa.String(300), nullable=False, server_default=""),
    )
    op.create_index("ix_fft_usage_readings_workspace_id", "fft_usage_readings", ["workspace_id"])
    op.create_index("ix_fft_usage_readings_area_id", "fft_usage_readings", ["area_id"])
    op.create_index("ix_fft_usage_readings_item_id", "fft_usage_readings", ["item_id"])


def downgrade() -> None:
    op.drop_table("fft_usage_readings")
