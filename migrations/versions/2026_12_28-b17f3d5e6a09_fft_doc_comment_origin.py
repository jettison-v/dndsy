"""Comments made on claude.ai, brought into askdnd (FftDocComment.origin, ext_id, made_at; item 39, 6 of 6). Only adds.

Revision ID: b17f3d5e6a09
Revises: a06e2c4d5f98
"""

import sqlalchemy as sa
from alembic import op

revision = "b17f3d5e6a09"
down_revision = "a06e2c4d5f98"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_doc_comments", sa.Column("origin", sa.String(10), nullable=False, server_default="askdnd"))
    op.add_column("fft_doc_comments", sa.Column("ext_id", sa.String(64), nullable=False, server_default=""))
    op.add_column("fft_doc_comments", sa.Column("made_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("fft_doc_comments", "made_at")
    op.drop_column("fft_doc_comments", "ext_id")
    op.drop_column("fft_doc_comments", "origin")
