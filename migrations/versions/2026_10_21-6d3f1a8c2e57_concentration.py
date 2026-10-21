"""concentration tracking on characters

Revision ID: 6d3f1a8c2e57
Revises: 4c9e2a7b1f03
Create Date: 2026-10-21 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6d3f1a8c2e57'
down_revision: Union[str, Sequence[str], None] = '4c9e2a7b1f03'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('characters', sa.Column('concentration', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('characters', 'concentration')
