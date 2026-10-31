"""What's new since a character last leveled: characters.level_up (roadmap 1.9, 2026-10-30)

Set when a read of the sheet finds a higher level, cleared when its player says they've read it.

Revision ID: e5a1c7d2f4b8
Revises: d4e9f2a6c1b3
Create Date: 2026-10-30 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e5a1c7d2f4b8'
down_revision: Union[str, Sequence[str], None] = 'd4e9f2a6c1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('level_up', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('characters', 'level_up')
