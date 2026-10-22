"""characters separate from campaigns (data organization step 1)

A character gets its own name and D&D Beyond campaign id; its link to a campaign (story page, joined, left,
Wild Shape keeps) moves to campaign_characters. Personal quests remember their campaign.

Revision ID: 9a5b7c1d4e60
Revises: 8f4a6b0c3d59
Create Date: 2026-10-22 23:59:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9a5b7c1d4e60'
down_revision: Union[str, Sequence[str], None] = '8f4a6b0c3d59'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'campaign_characters',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='CASCADE'), nullable=False),
        sa.Column('character_id', sa.Integer(), sa.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('entity_id', sa.Integer(), sa.ForeignKey('entities.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('joined_on', sa.Date(), server_default=sa.func.current_date(), nullable=False),
        sa.Column('left_on', sa.Date(), nullable=True),
        sa.Column('wild_shape_keep', postgresql.JSONB(), nullable=True),
    )
    op.create_index('ix_campaign_characters_campaign_id', 'campaign_characters', ['campaign_id'])
    op.create_index('ix_campaign_characters_character_id', 'campaign_characters', ['character_id'])
    op.create_index('campaign_characters_one_current', 'campaign_characters', ['character_id'], unique=True,
                    postgresql_where=sa.text('left_on IS NULL'))
    op.add_column('characters', sa.Column('name', sa.String(length=200), server_default='', nullable=False))
    op.add_column('characters', sa.Column('ddb_campaign_id', sa.String(length=40), nullable=True))
    op.add_column('campaigns', sa.Column('ddb_campaign_id', sa.String(length=40), nullable=True))
    op.add_column('player_notes', sa.Column('campaign_id', sa.Integer(),
                                            sa.ForeignKey('campaigns.id', ondelete='SET NULL'), nullable=True))

    # Every character is in its story page's campaign since it was created.
    op.execute("""
        INSERT INTO campaign_characters (campaign_id, character_id, entity_id, joined_on, wild_shape_keep)
        SELECT e.campaign_id, c.id, c.entity_id, c.created_at::date, c.wild_shape_keep
        FROM characters c JOIN entities e ON e.id = c.entity_id
    """)
    op.execute("UPDATE characters c SET name = e.name FROM entities e WHERE e.id = c.entity_id")
    op.execute("""
        UPDATE characters c SET ddb_campaign_id = s.raw->'campaign'->>'id'
        FROM character_snapshots s WHERE s.character_id = c.id AND s.raw->'campaign'->>'id' IS NOT NULL
    """)
    # A campaign's D&D Beyond campaign: the one all its characters agree on.
    op.execute("""
        UPDATE campaigns k SET ddb_campaign_id = x.ddb
        FROM (SELECT m.campaign_id, min(c.ddb_campaign_id) AS ddb FROM campaign_characters m
              JOIN characters c ON c.id = m.character_id WHERE c.ddb_campaign_id IS NOT NULL
              GROUP BY m.campaign_id HAVING count(DISTINCT c.ddb_campaign_id) = 1) x
        WHERE k.id = x.campaign_id
    """)
    op.execute("""
        UPDATE player_notes n SET campaign_id = m.campaign_id
        FROM campaign_characters m WHERE m.character_id = n.character_id AND n.kind = 'quest'
    """)
    # Version history of Wild Shape keeps now points at the membership.
    op.execute("""
        UPDATE revisions r SET "table" = 'campaign_characters', row_id = m.id
        FROM campaign_characters m WHERE r."table" = 'characters' AND r.field = 'wild_shape_keep' AND r.row_id = m.character_id
    """)
    op.drop_column('characters', 'wild_shape_keep')
    op.drop_constraint('characters_entity_id_key', 'characters', type_='unique')
    op.drop_column('characters', 'entity_id')


def downgrade() -> None:
    op.add_column('characters', sa.Column('entity_id', sa.Integer(), sa.ForeignKey('entities.id', ondelete='CASCADE'),
                                          nullable=True))
    op.add_column('characters', sa.Column('wild_shape_keep', postgresql.JSONB(), nullable=True))
    # Back to the story page and keeps of the campaign it's in now (else its latest one).
    op.execute("""
        UPDATE characters c SET entity_id = m.entity_id, wild_shape_keep = m.wild_shape_keep
        FROM (SELECT DISTINCT ON (character_id) * FROM campaign_characters
              ORDER BY character_id, (left_on IS NULL) DESC, id DESC) m
        WHERE m.character_id = c.id
    """)
    op.execute("""
        UPDATE revisions r SET "table" = 'characters', row_id = m.character_id
        FROM campaign_characters m WHERE r."table" = 'campaign_characters' AND r.field = 'wild_shape_keep' AND r.row_id = m.id
    """)
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM characters WHERE entity_id IS NULL")):
        raise RuntimeError("Some characters have no story page to go back to; give them one first.")
    op.alter_column('characters', 'entity_id', nullable=False)
    op.create_unique_constraint('characters_entity_id_key', 'characters', ['entity_id'])
    op.drop_column('player_notes', 'campaign_id')
    op.drop_column('campaigns', 'ddb_campaign_id')
    op.drop_column('characters', 'ddb_campaign_id')
    op.drop_column('characters', 'name')
    op.drop_table('campaign_characters')
