"""Found, Fixed, Tried: picks made on a mockup inside askdnd, kept with its question (Brett's round, Nov 18)

Revision ID: 7c1e4f2a9d30
Revises: 5b7d2e9a1c44
Create Date: 2026-12-05
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "7c1e4f2a9d30"
down_revision: str | Sequence[str] | None = "5b7d2e9a1c44"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("fft_questions", sa.Column("picks", JSONB, nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("fft_questions", "picks")
