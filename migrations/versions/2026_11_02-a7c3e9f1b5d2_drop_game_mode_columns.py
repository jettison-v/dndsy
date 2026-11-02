"""Drop campaigns.game_until and game_by_id, unused since Game Mode was removed (Brett approved, 2026-11-02)

Revision ID: a7c3e9f1b5d2
Revises: f6b2d8e3a9c4
Create Date: 2026-11-02 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a7c3e9f1b5d2'
down_revision: Union[str, Sequence[str], None] = 'f6b2d8e3a9c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint('campaigns_game_by_id_fkey', 'campaigns', type_='foreignkey')
    op.drop_column('campaigns', 'game_by_id')
    op.drop_column('campaigns', 'game_until')


def downgrade() -> None:
    op.add_column('campaigns', sa.Column('game_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('campaigns', sa.Column('game_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key('campaigns_game_by_id_fkey', 'campaigns', 'users', ['game_by_id'], ['id'], ondelete='SET NULL')
