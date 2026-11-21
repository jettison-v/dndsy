"""Split… an issue into several (issue 22, Brett's pick 2A, Nov 21): a note's other issues. Only adds.

Revision ID: 5c1e7a3d9f24
Revises: 8b4d2f6a9c51
"""

import sqlalchemy as sa
from alembic import op

revision = "5c1e7a3d9f24"
down_revision = "8b4d2f6a9c51"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("fft_note_issues",
                    sa.Column("note_id", sa.Integer(), sa.ForeignKey("fft_notes.id", ondelete="CASCADE"), primary_key=True),
                    sa.Column("issue_id", sa.Integer(), sa.ForeignKey("fft_issues.id", ondelete="CASCADE"), primary_key=True, index=True))


def downgrade() -> None:
    op.drop_table("fft_note_issues")
