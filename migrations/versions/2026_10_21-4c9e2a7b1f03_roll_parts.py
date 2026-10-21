"""table rolls: each part and instance on its own line, and an attack's damage recipe

Revision ID: 4c9e2a7b1f03
Revises: 8b1d5e2f7a64
Create Date: 2026-10-21 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '4c9e2a7b1f03'
down_revision: Union[str, Sequence[str], None] = '8b1d5e2f7a64'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('table_rolls', sa.Column('parts', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.add_column('table_rolls', sa.Column('spec', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('table_rolls', 'spec')
    op.drop_column('table_rolls', 'parts')
