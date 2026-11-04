"""Initiative from askdnd (app/initiative.py; Brett, 2026-11-04, docs/mockups/initiative/): when the DM's open D&D Beyond
VTT page last asked for numbers to set, kept apart from the fight so asking doesn't redraw every page

Revision ID: e3b81c6d2f47
Revises: d7a2c9e41b5f
Create Date: 2026-11-04 22:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e3b81c6d2f47'
down_revision: Union[str, Sequence[str], None] = 'd7a2c9e41b5f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("vtt_heard_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("campaigns", "vtt_heard_at")
