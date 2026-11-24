"""Pull requests as GitHub reports them (app/fft/models.py FftPull; item 39, A sturdier loop, Nov 23). Only adds.

Revision ID: 7d3b9f1a2c65
Revises: 5c1e8a3d7b42
"""

import sqlalchemy as sa
from alembic import op

revision = "7d3b9f1a2c65"
down_revision = "5c1e8a3d7b42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fft_pulls",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False, unique=True),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("branch", sa.String(200), nullable=False, server_default=""),
        sa.Column("by_bot", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("state", sa.String(10), nullable=False, server_default="open"),
        sa.Column("tests", sa.String(10), nullable=False, server_default=""),
        sa.Column("merge_state", sa.String(12), nullable=False, server_default=""),
        sa.Column("auto_merge", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("head", sa.String(40), nullable=False, server_default=""),
        sa.Column("updated_by_askdnd_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("issue_id", sa.Integer(), sa.ForeignKey("fft_issues.id", ondelete="SET NULL"), nullable=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("fft_areas.id", ondelete="SET NULL"), nullable=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("fft_items.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_fft_pulls_workspace_id", "fft_pulls", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("fft_pulls")
