"""Work's cut line (Brett's picks on The Work Pages, Nov 20; the work flow's slice 4): a plan held below the line

Revision ID: 9d3f6a2c8e15
Revises: 5c8a2e4f6b17
Create Date: 2026-12-11

A column only added. Claude takes the plans above the line; one held below it waits until Brett lets it go.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d3f6a2c8e15"
down_revision: str | Sequence[str] | None = "5c8a2e4f6b17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("fft_areas", sa.Column("held", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("fft_areas", "held")
