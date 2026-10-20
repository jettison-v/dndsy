"""table rolls: dice rolled on the server while Game Mode is on

Revision ID: 3e7a91c4d2b8
Revises: 7c4d2a9e1b30
Create Date: 2026-10-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3e7a91c4d2b8'
down_revision: Union[str, Sequence[str], None] = '7c4d2a9e1b30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'table_rolls',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('campaign_id', sa.Integer(), nullable=False),
        sa.Column('character_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.Integer(), nullable=True),
        sa.Column('label', sa.String(length=120), nullable=False),
        sa.Column('kind', sa.String(length=10), nullable=False),
        sa.Column('formula', sa.String(length=40), nullable=False),
        sa.Column('dice', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('kept', sa.Integer(), nullable=True),
        sa.Column('modifier', sa.Integer(), nullable=False),
        sa.Column('total', sa.Integer(), nullable=False),
        sa.Column('mode', sa.String(length=10), nullable=False),
        sa.Column('visibility', sa.String(length=10), nullable=False),
        sa.Column('damage', sa.String(length=40), server_default='', nullable=False),
        sa.Column('crit', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['campaign_id'], ['campaigns.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_table_rolls_campaign_id'), 'table_rolls', ['campaign_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_table_rolls_campaign_id'), table_name='table_rolls')
    op.drop_table('table_rolls')
