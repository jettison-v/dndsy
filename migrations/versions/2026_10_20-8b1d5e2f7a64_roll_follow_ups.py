"""table rolls: follow-ups (damage, reroll, added die), situational bonuses, who rolled

Revision ID: 8b1d5e2f7a64
Revises: 3e7a91c4d2b8
Create Date: 2026-10-20 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8b1d5e2f7a64'
down_revision: Union[str, Sequence[str], None] = '3e7a91c4d2b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('table_rolls', sa.Column('parent_id', sa.Integer(), nullable=True))
    op.add_column('table_rolls', sa.Column('who', sa.String(length=80), server_default='', nullable=False))
    op.add_column('table_rolls', sa.Column('extras', postgresql.JSONB(astext_type=sa.Text()), server_default='[]', nullable=False))
    op.create_foreign_key('table_rolls_parent_id_fkey', 'table_rolls', 'table_rolls', ['parent_id'], ['id'], ondelete='CASCADE')
    op.create_index(op.f('ix_table_rolls_parent_id'), 'table_rolls', ['parent_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_table_rolls_parent_id'), table_name='table_rolls')
    op.drop_constraint('table_rolls_parent_id_fkey', 'table_rolls', type_='foreignkey')
    op.drop_column('table_rolls', 'extras')
    op.drop_column('table_rolls', 'who')
    op.drop_column('table_rolls', 'parent_id')
