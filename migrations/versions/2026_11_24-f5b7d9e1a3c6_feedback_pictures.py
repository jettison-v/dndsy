"""feedback_pictures: screenshots added to a note after it was sent (Add to it; feedback 64, Nov 16).

Revision ID: f5b7d9e1a3c6
Revises: e3a5c7d9f1b4
"""

import sqlalchemy as sa
from alembic import op

revision = "f5b7d9e1a3c6"
down_revision = "e3a5c7d9f1b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback_pictures",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("feedback_id", sa.Integer(), sa.ForeignKey("feedback.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(200), sa.ForeignKey("stored_files.key"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_feedback_pictures_feedback_id", "feedback_pictures", ["feedback_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_pictures_feedback_id", "feedback_pictures")
    op.drop_table("feedback_pictures")
