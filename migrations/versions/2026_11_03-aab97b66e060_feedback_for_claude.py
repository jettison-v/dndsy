"""Feedback for Claude (app/feedback.py; Brett, 2026-11-03): notes from any page, waiting for Claude in a queue,
and which accounts that aren't admins can send one (Brett's test accounts)

Revision ID: aab97b66e060
Revises: d8e1f4a6b2c9
Create Date: 2026-11-03 13:32:13.746239

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aab97b66e060'
down_revision: Union[str, Sequence[str], None] = 'd8e1f4a6b2c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy.dialects import postgresql

    op.add_column("users", sa.Column("feedback", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.create_table(
        "feedback",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sender", sa.String(300), server_default="", nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), server_default="new", nullable=False),
        sa.Column("url", sa.String(1000), server_default="", nullable=False),
        sa.Column("context", postgresql.JSONB(), server_default="{}", nullable=False),
        sa.Column("html", sa.Text(), server_default="", nullable=False),
        sa.Column("shot_key", sa.String(200), sa.ForeignKey("stored_files.key"), nullable=True),
        sa.Column("pasted_key", sa.String(200), sa.ForeignKey("stored_files.key"), nullable=True),
        sa.Column("thread", postgresql.JSONB(), server_default="[]", nullable=False),
        sa.Column("pr", sa.String(300), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_feedback_status", "feedback", ["status"])


def downgrade() -> None:
    op.drop_index("ix_feedback_status", table_name="feedback")
    op.drop_table("feedback")
    op.drop_column("users", "feedback")
