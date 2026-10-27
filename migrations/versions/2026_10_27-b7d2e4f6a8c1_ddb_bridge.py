"""the D&D Beyond bridge proof: bridge_intents, bridge_batches, bridge_log, bridge_keys (app/ddb_bridge.py)

Revision ID: b7d2e4f6a8c1
Revises: f1b3c7d9e2a4
Create Date: 2026-10-27 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'b7d2e4f6a8c1'
down_revision: Union[str, Sequence[str], None] = 'f1b3c7d9e2a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _stamps():
    return [sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False)]


def _character():
    return sa.Column('character_id', sa.Integer(), sa.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False)


def upgrade() -> None:
    op.create_table(
        'bridge_intents',
        sa.Column('id', sa.Integer(), primary_key=True),
        _character(),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('data', JSONB(), server_default='{}', nullable=False),
        sa.Column('label', sa.String(length=300), nullable=False),
        sa.Column('state', sa.String(length=20), server_default='waiting', nullable=False),
        sa.Column('error', sa.String(length=400), server_default='', nullable=False),
        *_stamps(),
    )
    op.create_index('ix_bridge_intents_character_id', 'bridge_intents', ['character_id'])
    op.create_index('ix_bridge_intents_state', 'bridge_intents', ['state'])
    op.create_table(
        'bridge_batches',
        sa.Column('id', sa.Integer(), primary_key=True),
        _character(),
        sa.Column('intents', JSONB(), server_default='[]', nullable=False),
        sa.Column('ops', JSONB(), server_default='[]', nullable=False),
        sa.Column('before', JSONB(), server_default='{}', nullable=False),
        sa.Column('target', JSONB(), server_default='{}', nullable=False),
        sa.Column('names', JSONB(), server_default='{}', nullable=False),
        sa.Column('state', sa.String(length=20), server_default='sending', nullable=False),
        sa.Column('attempts', sa.Integer(), server_default='1', nullable=False),
        sa.Column('sent_at', sa.Float(), server_default='0', nullable=False),
        sa.Column('next_at', sa.Float(), server_default='0', nullable=False),
        sa.Column('check', sa.String(length=10), server_default='', nullable=False),
        sa.Column('error', sa.String(length=400), server_default='', nullable=False),
        *_stamps(),
    )
    op.create_index('ix_bridge_batches_character_id', 'bridge_batches', ['character_id'])
    op.create_index('ix_bridge_batches_state', 'bridge_batches', ['state'])
    op.create_table(
        'bridge_log',
        sa.Column('id', sa.Integer(), primary_key=True),
        _character(),
        sa.Column('text', sa.String(length=400), nullable=False),
        sa.Column('state', sa.String(length=10), nullable=False),
        sa.Column('at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index('ix_bridge_log_character_id', 'bridge_log', ['character_id'])
    op.create_table(
        'bridge_keys',
        sa.Column('key_hash', sa.String(length=64), primary_key=True),
        sa.Column('email', sa.String(length=320), nullable=False),
        *_stamps(),
    )
    op.create_index('ix_bridge_keys_email', 'bridge_keys', ['email'])


def downgrade() -> None:
    for table in ('bridge_keys', 'bridge_log', 'bridge_batches', 'bridge_intents'):
        op.drop_table(table)
