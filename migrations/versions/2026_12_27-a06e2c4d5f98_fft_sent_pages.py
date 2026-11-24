"""Pages Claude sends to askdnd before their repo copy lands (fft_sent_docs, fft_sent_files; item 39, scope v7). Only adds.

Revision ID: a06e2c4d5f98
Revises: 9f5d1b3c4e87
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "a06e2c4d5f98"
down_revision = "9f5d1b3c4e87"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fft_sent_docs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("source", sa.String(300), nullable=False, unique=True),
        sa.Column("entry", postgresql.JSONB(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "fft_sent_files",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1", index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("path", sa.String(300), nullable=False, unique=True),
        sa.Column("body", sa.LargeBinary(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fft_sent_files")
    op.drop_table("fft_sent_docs")
