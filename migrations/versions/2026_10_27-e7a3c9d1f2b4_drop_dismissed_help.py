"""drop users.dismissed_help: pages have no help lines to dismiss any more (Brett, 2026-10-27)

Revision ID: e7a3c9d1f2b4
Revises: c4e8a1d3f5b7
Create Date: 2026-10-27 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e7a3c9d1f2b4'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1d3f5b7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('users', 'dismissed_help')


def downgrade() -> None:
    op.add_column('users', sa.Column('dismissed_help', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
