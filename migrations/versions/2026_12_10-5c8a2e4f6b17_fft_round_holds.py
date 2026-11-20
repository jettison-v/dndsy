"""A lighter round (Brett's pick, Nov 19, docs/plans/2026-11-19-lighter-rounds.md): whether a round holds merges

Revision ID: 5c8a2e4f6b17
Revises: 7b5e3c1d9a42
Create Date: 2026-12-10

A column only added. A sitting (▶ Start round) holds Claude's merges in its own Product Area(s); ▶ Try it on one check
holds nothing. Rounds already open keep holding, as they did.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5c8a2e4f6b17"
down_revision: str | Sequence[str] | None = "7b5e3c1d9a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("fft_rounds", sa.Column("holds", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    op.drop_column("fft_rounds", "holds")
