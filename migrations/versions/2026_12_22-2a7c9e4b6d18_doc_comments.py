"""Comments pinned to a mockup (issue 24, Brett's picks Nov 21). Only adds.

Revision ID: 2a7c9e4b6d18
Revises: 9d3b6e1f4a72
"""

import sqlalchemy as sa
from alembic import op

revision = "2a7c9e4b6d18"
down_revision = "9d3b6e1f4a72"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("fft_doc_comments",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1", index=True),
                    sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
                    sa.Column("doc", sa.String(300), nullable=False, index=True),
                    sa.Column("page", sa.String(300), nullable=False, server_default=""),
                    sa.Column("n", sa.Integer(), nullable=False),
                    sa.Column("x", sa.Float(), nullable=False),
                    sa.Column("y", sa.Float(), nullable=False),
                    sa.Column("near", sa.String(200), nullable=False, server_default=""),
                    sa.Column("words", sa.Text(), nullable=False),
                    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
                    sa.Column("question_id", sa.Integer(), sa.ForeignKey("fft_questions.id", ondelete="SET NULL"), nullable=True),
                    sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_table("fft_doc_comments")
