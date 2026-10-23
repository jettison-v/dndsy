"""more than one campaign (data organization step 4)

Each person's current campaign (the switcher in the menu bar); a character can rejoin a campaign with the same
story page, so campaign_characters.entity_id is no longer unique.

Revision ID: cd8e0f4a7b93
Revises: bc7d9e3f6a82
Create Date: 2026-10-23 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'cd8e0f4a7b93'
down_revision: Union[str, Sequence[str], None] = 'bc7d9e3f6a82'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('current_campaign_id', sa.Integer(),
                                     sa.ForeignKey('campaigns.id', ondelete='SET NULL'), nullable=True))
    op.drop_constraint('campaign_characters_entity_id_key', 'campaign_characters', type_='unique')
    op.create_index('ix_campaign_characters_entity_id', 'campaign_characters', ['entity_id'])
    # One spending limit for the whole tool (decision 7): taken from the first campaign
    op.create_table('tool_settings', sa.Column('key', sa.String(length=50), primary_key=True),
                    sa.Column('value', sa.Text(), server_default='', nullable=False))
    op.execute("""INSERT INTO tool_settings (key, value)
                  SELECT 'monthly_limit_usd', monthly_limit_usd::text FROM campaigns
                  WHERE monthly_limit_usd IS NOT NULL ORDER BY id LIMIT 1""")
    op.drop_column('campaigns', 'monthly_limit_usd')


def downgrade() -> None:
    op.add_column('campaigns', sa.Column('monthly_limit_usd', sa.Float(), nullable=True))
    op.execute("""UPDATE campaigns SET monthly_limit_usd = (SELECT value::float FROM tool_settings WHERE key = 'monthly_limit_usd')
                  WHERE id = (SELECT min(id) FROM campaigns)""")
    op.drop_table('tool_settings')
    op.drop_index('ix_campaign_characters_entity_id', 'campaign_characters')
    op.execute("""DELETE FROM campaign_characters a USING campaign_characters b
                  WHERE a.entity_id = b.entity_id AND a.id < b.id""")  # keep each story page's latest membership
    op.create_unique_constraint('campaign_characters_entity_id_key', 'campaign_characters', ['entity_id'])
    op.drop_column('users', 'current_campaign_id')
