"""Areas and Claude's inbox (Working with Claude, Brett's picks Nov 17, docs/mockups/working-together/).

areas: the notes and checks that are fixed and tried together, in the order Brett sets; one at a time in Claude's
hands (`fixing`). feedback.area_id and checks.area_id put a note or a check in one. claude_inbox: what happened in
askdnd that Claude hasn't read yet (a note sent, a check marked, an answer), read through /api/claude/inbox.

Revision ID: e1b3d5f7a9c2
Revises: d0f2b4c6e8a1
"""

import sqlalchemy as sa
from alembic import op

revision = "e1b3d5f7a9c2"
down_revision = "d0f2b4c6e8a1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "areas",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(80), nullable=False),
        sa.Column("place", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fixing", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.add_column("feedback", sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_feedback_area_id", "feedback", ["area_id"])
    op.add_column("checks", sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_checks_area_id", "checks", ["area_id"])
    op.create_table(
        "claude_inbox",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("what", sa.String(30), nullable=False),
        sa.Column("text", sa.String(400), nullable=False, server_default=""),
        sa.Column("feedback_id", sa.Integer(), sa.ForeignKey("feedback.id", ondelete="SET NULL"), nullable=True),
        sa.Column("check_id", sa.Integer(), sa.ForeignKey("checks.id", ondelete="SET NULL"), nullable=True),
        sa.Column("area_id", sa.Integer(), sa.ForeignKey("areas.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("claude_inbox")
    op.drop_index("ix_checks_area_id", "checks")
    op.drop_column("checks", "area_id")
    op.drop_index("ix_feedback_area_id", "feedback")
    op.drop_column("feedback", "area_id")
    op.drop_table("areas")
