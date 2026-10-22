"""conditions on characters (Invisible from a magic item…)

Revision ID: 3f7a9c1d5e20
Revises: 8b2e5d7c4a19
Create Date: 2026-10-22 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3f7a9c1d5e20'
down_revision: Union[str, Sequence[str], None] = '8b2e5d7c4a19'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('conditions', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('characters', 'conditions')
