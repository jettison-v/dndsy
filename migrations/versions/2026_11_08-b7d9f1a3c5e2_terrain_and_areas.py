"""askdnd's table: a place's Difficult Terrain and its spell areas

Revision ID: b7d9f1a3c5e2
Revises: a3c5e7f9b1d2
Create Date: 2026-11-08
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "b7d9f1a3c5e2"
down_revision: Union[str, Sequence[str], None] = "a3c5e7f9b1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("places", sa.Column("terrain", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False))
    op.add_column("places", sa.Column("areas", postgresql.JSONB(astext_type=sa.Text()), server_default="[]", nullable=False))


def downgrade() -> None:
    op.drop_column("places", "areas")
    op.drop_column("places", "terrain")
