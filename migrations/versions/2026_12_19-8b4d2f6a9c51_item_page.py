"""A Roadmap item's page (issues 60, 61, Brett's picks Nov 21): the decisions behind its why, and Scope it. Only adds.

Revision ID: 8b4d2f6a9c51
Revises: 6a2e4c8f1b37
"""

import sqlalchemy as sa
from alembic import op

revision = "8b4d2f6a9c51"
down_revision = "6a2e4c8f1b37"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_items", sa.Column("why_from", sa.Text(), nullable=False, server_default=""))
    op.add_column("fft_items", sa.Column("scope_asked_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("fft_items", "scope_asked_at")
    op.drop_column("fft_items", "why_from")
