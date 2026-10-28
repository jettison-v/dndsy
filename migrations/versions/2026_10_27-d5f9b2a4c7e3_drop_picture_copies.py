"""pictures only in file storage, last step: drop the database copies (VTT 0.5)

entity_pictures.data/thumb and note_images.data were last written before c4e8a1f3b6d2, and every one was checked
against its S3 copy first (scripts/check_files.py, 2026-10-27; docs/DECISIONS.md). Refuses to run if any row has no
storage key, so nothing here can drop a picture's only copy. The nightly backups made before this ran (S3
v2/backups/, kept 30 days) still hold the old copies; scripts/restore_db.py brings one back into an empty database.

Revision ID: d5f9b2a4c7e3
Revises: c4e8a1f3b6d2
Create Date: 2026-10-27 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd5f9b2a4c7e3'
down_revision: Union[str, Sequence[str], None] = 'c4e8a1f3b6d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    unkeyed = op.get_bind().execute(sa.text(
        "SELECT (SELECT count(*) FROM entity_pictures WHERE file_key IS NULL OR thumb_key IS NULL)"
        " + (SELECT count(*) FROM note_images WHERE file_key IS NULL)")).scalar()
    if unkeyed:
        raise RuntimeError(f"{unkeyed} picture(s) have no copy in file storage; not dropping their database copies")
    op.drop_column('entity_pictures', 'data')
    op.drop_column('entity_pictures', 'thumb')
    op.drop_column('note_images', 'data')
    op.alter_column('entity_pictures', 'file_key', nullable=False)
    op.alter_column('entity_pictures', 'thumb_key', nullable=False)
    op.alter_column('note_images', 'file_key', nullable=False)


def downgrade() -> None:
    # The columns come back empty: the old copies are only in backups made before the upgrade
    op.alter_column('entity_pictures', 'file_key', nullable=True)
    op.alter_column('entity_pictures', 'thumb_key', nullable=True)
    op.alter_column('note_images', 'file_key', nullable=True)
    op.add_column('entity_pictures', sa.Column('data', sa.LargeBinary(), nullable=True))
    op.add_column('entity_pictures', sa.Column('thumb', sa.LargeBinary(), nullable=True))
    op.add_column('note_images', sa.Column('data', sa.LargeBinary(), nullable=True))
