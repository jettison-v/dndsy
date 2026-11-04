"""Pictures in askdnd (app/pictures.py; Brett, 2026-11-04, docs/mockups/pictures/): one kind of picture for a World entry
or one of a character's creatures, with where it came from (uploaded, drawn from a description, D&D Beyond's art), and
the campaign's art style for drawn pictures

Revision ID: d7a2c9e41b5f
Revises: c41f7d2e9a10
Create Date: 2026-11-04 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd7a2c9e41b5f'
down_revision: Union[str, Sequence[str], None] = 'c41f7d2e9a10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from sqlalchemy.dialects import postgresql

    op.alter_column("entity_pictures", "entity_id", nullable=True)
    op.alter_column("entity_pictures", "file_key", nullable=True)
    op.alter_column("entity_pictures", "thumb_key", nullable=True)
    op.add_column("entity_pictures", sa.Column("character_id", sa.Integer(), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=True))
    op.add_column("entity_pictures", sa.Column("creature", sa.String(40), nullable=True))
    op.add_column("entity_pictures", sa.Column("source", sa.String(20), server_default="upload", nullable=False))
    op.add_column("entity_pictures", sa.Column("words", sa.Text(), server_default="", nullable=False))
    op.add_column("entity_pictures", sa.Column("style", sa.Text(), server_default="", nullable=False))
    op.add_column("entity_pictures", sa.Column("link", sa.String(500), server_default="", nullable=False))
    op.create_index("ix_entity_pictures_character_id", "entity_pictures", ["character_id"])
    op.create_unique_constraint("uq_entity_pictures_creature", "entity_pictures", ["character_id", "creature"])
    op.add_column("campaigns", sa.Column("art_style", postgresql.JSONB(), server_default="{}", nullable=False))


def downgrade() -> None:
    op.drop_column("campaigns", "art_style")
    op.drop_constraint("uq_entity_pictures_creature", "entity_pictures")
    op.drop_index("ix_entity_pictures_character_id", "entity_pictures")
    for c in ("link", "style", "words", "source", "creature", "character_id"):
        op.drop_column("entity_pictures", c)
