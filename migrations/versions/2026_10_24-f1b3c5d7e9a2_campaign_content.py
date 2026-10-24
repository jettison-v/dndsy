"""a campaign's own monsters, spells and magic items (VTT 0.6, rules content as data)

campaign_content holds the DM's creations and entries copied in from books the DM owns, per campaign; the SRD itself
is in app/data/srd/. app/rules_data.py reads both as one.

Revision ID: f1b3c5d7e9a2
Revises: ef0a2b6c9d15
Create Date: 2026-10-24 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f1b3c5d7e9a2'
down_revision: Union[str, Sequence[str], None] = 'ef0a2b6c9d15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'campaign_content',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('key', sa.String(length=120), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('source', sa.String(length=200), server_default='Homebrew', nullable=False),
        sa.Column('data', postgresql.JSONB(), server_default='{}', nullable=False),
        sa.Column('created_by_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('campaign_id', 'kind', 'key'),
    )
    op.create_index('ix_campaign_content_campaign_id', 'campaign_content', ['campaign_id'])


def downgrade() -> None:
    op.drop_table('campaign_content')
