"""Game Mode for the table: campaigns.game_until and game_by_id; characters.sheet_heard_at (Brett, 2026-10-28)

Game Mode was a switch kept in each browser; it's now one switch for the campaign. sheet_heard_at is when the
bridge's extension last heard a character's D&D Beyond sheet, so the Live pill can say it's in step.

Revision ID: a1f4c7e2b9d6
Revises: e7a3c9d1f2b4
Create Date: 2026-10-28 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a1f4c7e2b9d6'
down_revision: Union[str, Sequence[str], None] = 'e7a3c9d1f2b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('campaigns', sa.Column('game_until', sa.DateTime(timezone=True), nullable=True))
    op.add_column('campaigns', sa.Column('game_by_id', sa.Integer(), nullable=True))
    op.create_foreign_key('campaigns_game_by_id_fkey', 'campaigns', 'users', ['game_by_id'], ['id'], ondelete='SET NULL')
    op.add_column('characters', sa.Column('sheet_heard_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('characters', 'sheet_heard_at')
    op.drop_constraint('campaigns_game_by_id_fkey', 'campaigns', type_='foreignkey')
    op.drop_column('campaigns', 'game_by_id')
    op.drop_column('campaigns', 'game_until')
