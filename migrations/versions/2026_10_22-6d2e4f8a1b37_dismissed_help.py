"""help lines a person has dismissed ("Got it")

Revision ID: 6d2e4f8a1b37
Revises: 3f7a9c1d5e20
Create Date: 2026-10-22 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '6d2e4f8a1b37'
down_revision: Union[str, Sequence[str], None] = '3f7a9c1d5e20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('dismissed_help', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'dismissed_help')
