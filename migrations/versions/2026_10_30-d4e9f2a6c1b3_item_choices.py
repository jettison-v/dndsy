"""What a character's copy of an item is: campaign_characters.item_choices (Brett, 2026-10-30)

Some items come in kinds the rules list (a Dragon-Touched Focus's dragon family). The player marks which on the item, so
askdnd can place it and no note has to say so. It moves into askdnd's own inventory when that exists.

Revision ID: d4e9f2a6c1b3
Revises: c3d8e1f5a7b2
Create Date: 2026-10-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'd4e9f2a6c1b3'
down_revision: Union[str, Sequence[str], None] = 'c3d8e1f5a7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaign_characters', sa.Column('item_choices', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('campaign_characters', 'item_choices')
