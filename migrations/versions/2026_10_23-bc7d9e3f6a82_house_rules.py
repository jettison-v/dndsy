"""tool corrections and house rules (data organization step 3)

sheet_overrides becomes tool_corrections (same meaning: how askdnd reads D&D Beyond, for everyone) and gains a
reason. house_rules holds a campaign's own rulings, each pointing at the tool knowledge it changes.

Revision ID: bc7d9e3f6a82
Revises: ab6c8d2e5f71
Create Date: 2026-10-23 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'bc7d9e3f6a82'
down_revision: Union[str, Sequence[str], None] = 'ab6c8d2e5f71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.rename_table('sheet_overrides', 'tool_corrections')
    op.execute('ALTER SEQUENCE sheet_overrides_id_seq RENAME TO tool_corrections_id_seq')
    op.execute('ALTER TABLE tool_corrections RENAME CONSTRAINT sheet_overrides_pkey TO tool_corrections_pkey')
    op.execute('ALTER TABLE tool_corrections RENAME CONSTRAINT sheet_overrides_ref_field_key TO tool_corrections_ref_field_key')
    op.add_column('tool_corrections', sa.Column('reason', sa.String(length=300), server_default='', nullable=False))
    op.create_table(
        'house_rules',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_kind', sa.String(length=20), nullable=False),
        sa.Column('target_key', sa.String(length=200), nullable=False),
        sa.Column('field', sa.String(length=30), nullable=False),
        sa.Column('value', sa.Text(), server_default='', nullable=False),
        sa.Column('reason', sa.Text(), server_default='', nullable=False),
        sa.Column('set_by', sa.String(length=200), server_default='', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint('campaign_id', 'target_kind', 'target_key', 'field'),
    )
    op.create_index('ix_house_rules_campaign_id', 'house_rules', ['campaign_id'])


def downgrade() -> None:
    op.drop_table('house_rules')
    op.drop_column('tool_corrections', 'reason')
    op.execute('ALTER TABLE tool_corrections RENAME CONSTRAINT tool_corrections_ref_field_key TO sheet_overrides_ref_field_key')
    op.execute('ALTER TABLE tool_corrections RENAME CONSTRAINT tool_corrections_pkey TO sheet_overrides_pkey')
    op.execute('ALTER SEQUENCE tool_corrections_id_seq RENAME TO sheet_overrides_id_seq')
    op.rename_table('tool_corrections', 'sheet_overrides')
