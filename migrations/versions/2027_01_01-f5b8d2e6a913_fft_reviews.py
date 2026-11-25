"""Workshop's reviews as this workspace runs them, and each run (fft_reviews, fft_review_runs; Roadmap item 46, Brett's
picks on docs/mockups/review-catalog/). Only adds.

Revision ID: f5b8d2e6a913
Revises: e4a7c9d1b352
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "f5b8d2e6a913"
down_revision = "e4a7c9d1b352"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fft_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("key", sa.String(40), nullable=False),
        sa.Column("cadence", sa.String(12), nullable=False, server_default=""),
        sa.Column("scheduled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.UniqueConstraint("workspace_id", "key"),
    )
    op.create_table(
        "fft_review_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("review", sa.String(40), nullable=False, index=True),
        sa.Column("how", sa.String(10), nullable=False, server_default="asked"),
        sa.Column("asked_by", sa.String(40), nullable=False, server_default=""),
        sa.Column("state", sa.String(10), nullable=False, server_default="asked", index=True),
        sa.Column("inputs", JSONB(), nullable=False, server_default="{}"),
        sa.Column("doing", sa.String(200), nullable=False, server_default=""),
        sa.Column("question_id", sa.Integer(), nullable=True),
        sa.Column("result", JSONB(), nullable=False, server_default="{}"),
        sa.Column("why", sa.String(300), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("fft_review_runs")
    op.drop_table("fft_reviews")
