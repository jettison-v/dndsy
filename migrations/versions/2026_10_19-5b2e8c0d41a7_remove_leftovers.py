"""remove leftovers: the old character_notes table and users.is_admin

Any rows left in character_notes become General notes (player_notes) first, so
nothing is lost. users.is_admin was already ignored (access decides, app/access.py).

Revision ID: 5b2e8c0d41a7
Revises: 87215aee219d
Create Date: 2026-10-19 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '5b2e8c0d41a7'
down_revision: Union[str, Sequence[str], None] = '87215aee219d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        insert into player_notes (character_id, author_id, kind, title, status, data, position, created_at, updated_at)
        select character_id, author_id, 'general', 'Earlier note', '', jsonb_build_object('body', body), 0, created_at, updated_at
        from character_notes
    """)
    op.drop_index(op.f('ix_character_notes_character_id'), table_name='character_notes')
    op.drop_table('character_notes')
    op.drop_column('users', 'is_admin')


def downgrade() -> None:
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table('character_notes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('character_id', sa.Integer(), nullable=False),
    sa.Column('author_id', sa.Integer(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['character_id'], ['characters.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_character_notes_character_id'), 'character_notes', ['character_id'], unique=False)
