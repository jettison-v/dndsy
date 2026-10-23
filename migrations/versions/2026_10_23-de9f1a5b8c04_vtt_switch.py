"""the VTT switch and test campaigns (VTT Phase 0, item 0.1)

A test campaign sees every VTT piece while it's being built; any campaign can switch on finished pieces one at a
time (campaigns.vtt_pieces). A test copy of a character shares its D&D Beyond sheet but has its own play state
(characters.copy_of_id).

Revision ID: de9f1a5b8c04
Revises: cd8e0f4a7b93
Create Date: 2026-10-23 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'de9f1a5b8c04'
down_revision: Union[str, Sequence[str], None] = 'cd8e0f4a7b93'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column('is_test', sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column('campaigns', sa.Column('vtt_pieces', postgresql.JSONB(), server_default='[]', nullable=False))
    op.add_column('characters', sa.Column('copy_of_id', sa.Integer(),
                                          sa.ForeignKey('characters.id', ondelete='SET NULL'), nullable=True))


def downgrade() -> None:
    op.drop_column('characters', 'copy_of_id')
    op.drop_column('campaigns', 'vtt_pieces')
    op.drop_column('campaigns', 'is_test')
