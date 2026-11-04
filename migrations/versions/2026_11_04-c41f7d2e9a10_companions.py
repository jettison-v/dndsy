"""Your creatures, round 2 (app/creatures.py; Brett, 2026-11-04, docs/mockups/creatures-as-characters/): where each of a
character's familiars is (here, in the pocket dimension, gone) and what it is (Celestial, Fey or Fiend), kept by askdnd

Revision ID: c41f7d2e9a10
Revises: aab97b66e060
Create Date: 2026-11-04 18:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c41f7d2e9a10'
down_revision: Union[str, Sequence[str], None] = 'aab97b66e060'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy.dialects import postgresql

    op.add_column("characters", sa.Column("companions", postgresql.JSONB(), server_default="{}", nullable=False))


def downgrade() -> None:
    op.drop_column("characters", "companions")
