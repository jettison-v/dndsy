"""The fight heard from D&D Beyond's VTT: campaigns.fight and fight_at (Brett, 2026-10-29)

askdnd listens to the initiative order, the round and whose turn it is in D&D Beyond's VTT (app/fight.py), for the
fight band and conditions that end on a turn.

Revision ID: c3d8e1f5a7b2
Revises: a1f4c7e2b9d6
Create Date: 2026-10-29 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'c3d8e1f5a7b2'
down_revision: Union[str, Sequence[str], None] = 'a1f4c7e2b9d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column('fight', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('campaigns', sa.Column('fight_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('campaigns', 'fight_at')
    op.drop_column('campaigns', 'fight')
