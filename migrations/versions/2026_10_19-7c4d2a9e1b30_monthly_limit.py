"""monthly Claude spending limit on the campaign

Revision ID: 7c4d2a9e1b30
Revises: 5b2e8c0d41a7
Create Date: 2026-10-19 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7c4d2a9e1b30'
down_revision: Union[str, Sequence[str], None] = '5b2e8c0d41a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column('monthly_limit_usd', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('campaigns', 'monthly_limit_usd')
