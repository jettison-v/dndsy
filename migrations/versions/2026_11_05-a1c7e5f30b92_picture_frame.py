"""Framing a picture (feedback 12, Brett, 2026-11-05, docs/mockups/picture-framing.html option A): where its middle is
and how far in, picked once in the Picture window's Frame it step; every place shows the part around it.

Revision ID: a1c7e5f30b92
Revises: f4a9c2d81e30
Create Date: 2026-11-05 14:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'a1c7e5f30b92'
down_revision: Union[str, Sequence[str], None] = 'f4a9c2d81e30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entity_pictures", sa.Column("frame", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("entity_pictures", "frame")
