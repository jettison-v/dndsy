"""Table rolls heard on a D&D Beyond sheet (app/ddb_bridge.py): the roll's own id there, so it's recorded once

Revision ID: c4e8a1d3f5b7
Revises: c4e6a8b0d2f3
Create Date: 2026-10-27 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4e8a1d3f5b7'
down_revision: Union[str, Sequence[str], None] = 'c4e6a8b0d2f3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('table_rolls', sa.Column('ddb_roll_id', sa.String(length=60), nullable=True))
    op.create_index('ix_table_rolls_ddb_roll_id', 'table_rolls', ['ddb_roll_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_table_rolls_ddb_roll_id', table_name='table_rolls')
    op.drop_column('table_rolls', 'ddb_roll_id')
