"""Background jobs in Postgres, taken by a worker one at a time (Roadmap item 43, Brett's pick LB1 on
docs/mockups/backend-look-back/, Nov 25; docs/plans/2026-11-25-jobs-and-worker.md). Only adds.

Revision ID: d39b5f7a8c21
Revises: c28a4e6f7b10
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "d39b5f7a8c21"
down_revision = "c28a4e6f7b10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("queue", sa.String(20), nullable=False),
        sa.Column("state", sa.String(12), nullable=False, server_default="queued"),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        sa.Column("dedup_key", sa.String(120), nullable=True),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="SET NULL"), nullable=True),
        sa.Column("label", sa.String(200), nullable=False, server_default=""),
        sa.Column("requested_by", sa.String(200), nullable=False, server_default=""),
        sa.Column("priority", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("run_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_by", sa.String(80), nullable=False, server_default=""),
        sa.Column("version", sa.String(40), nullable=False, server_default=""),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("result", JSONB(), nullable=True),
    )
    op.create_index("ix_jobs_claim", "jobs", ["queue", sa.text("priority DESC"), "run_at", "id"], postgresql_where=sa.text("state = 'queued'"))
    op.create_index("ix_jobs_dedup", "jobs", ["dedup_key"], unique=True, postgresql_where=sa.text("state IN ('queued', 'running')"))
    op.create_index("ix_jobs_running", "jobs", ["heartbeat_at"], postgresql_where=sa.text("state = 'running'"))
    op.create_index("ix_jobs_campaign", "jobs", ["campaign_id", sa.text("created_at DESC")])


def downgrade() -> None:
    op.drop_table("jobs")
