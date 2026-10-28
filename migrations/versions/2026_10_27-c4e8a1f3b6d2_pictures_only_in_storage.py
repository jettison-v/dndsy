"""pictures only in file storage: the database copies are no longer written, so they may be empty (VTT 0.5)

Nothing is removed here; a later migration drops the columns once Brett says so.

Revision ID: c4e8a1f3b6d2
Revises: b7d2e4f6a8c1
Create Date: 2026-10-27 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c4e8a1f3b6d2'
down_revision: Union[str, Sequence[str], None] = 'b7d2e4f6a8c1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column('entity_pictures', 'data', nullable=True)
    op.alter_column('entity_pictures', 'thumb', nullable=True)
    op.alter_column('note_images', 'data', nullable=True)


def downgrade() -> None:
    # Rows added since have no database copy; give them an empty one so the columns can be required again
    op.execute("UPDATE entity_pictures SET data = '' WHERE data IS NULL")
    op.execute("UPDATE entity_pictures SET thumb = '' WHERE thumb IS NULL")
    op.execute("UPDATE note_images SET data = '' WHERE data IS NULL")
    op.alter_column('entity_pictures', 'data', nullable=False)
    op.alter_column('entity_pictures', 'thumb', nullable=False)
    op.alter_column('note_images', 'data', nullable=False)
