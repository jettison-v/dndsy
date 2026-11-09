"""usage_events: what people at the table do, by feature and the page it happened on (app/usage.py; Brett, Nov 9),
with Table rolls' history loaded in so rolls have a past from the first day

Revision ID: f6b8d0e2a4c5
Revises: e5a7c9d1f3b4
"""

import sqlalchemy as sa
from alembic import op

revision = "f6b8d0e2a4c5"
down_revision = "e5a7c9d1f3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "usage_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("campaign_id", sa.Integer(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("feature", sa.String(60), nullable=False),
        sa.Column("page", sa.String(30), server_default="", nullable=False),
        sa.Column("version", sa.String(12), server_default="", nullable=False),
    )
    op.create_index("ix_usage_events_at", "usage_events", ["at"])
    op.create_index("ix_usage_events_campaign_at", "usage_events", ["campaign_id", "at"])
    # Table rolls' history (first rolls only, not their follow-ups): a roll made on D&D Beyond's own sheet says so
    op.execute("""
        INSERT INTO usage_events (at, campaign_id, user_id, feature, page, version)
        SELECT created_at, campaign_id, user_id,
               CASE kind WHEN 'attack' THEN 'Rolls: attacks' WHEN 'save' THEN 'Rolls: saves' WHEN 'check' THEN 'Rolls: checks'
                         WHEN 'damage' THEN 'Rolls: damage' WHEN 'heal' THEN 'Rolls: healing' WHEN 'death' THEN 'Rolls: death saves'
                         ELSE 'Rolls: other' END,
               CASE WHEN ddb_roll_id IS NOT NULL THEN 'D&D Beyond' ELSE '' END, ''
        FROM table_rolls WHERE parent_id IS NULL AND user_id IS NOT NULL
    """)


def downgrade() -> None:
    op.drop_index("ix_usage_events_campaign_at", "usage_events")
    op.drop_index("ix_usage_events_at", "usage_events")
    op.drop_table("usage_events")
