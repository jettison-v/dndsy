"""file storage (VTT 0.5): stored_files, and storage keys beside the pictures kept in the database

Step 1 of moving pictures out of the database ("add before remove"): stored_files lists every file in file storage
(app/files.py); entity_pictures.file_key/thumb_key and note_images.file_key point at it. The old data/thumb columns
stay, still written, until scripts/backfill_files.py has copied every one and that's been checked on beta; removing
them is a later migration.

Revision ID: f1b3c7d9e2a4
Revises: ef0a2b6c9d15
Create Date: 2026-10-24 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1b3c7d9e2a4'
down_revision: Union[str, Sequence[str], None] = 'ef0a2b6c9d15'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stored_files',
        sa.Column('key', sa.String(length=200), primary_key=True),
        sa.Column('campaign_id', sa.Integer(), sa.ForeignKey('campaigns.id', ondelete='SET NULL'), nullable=True),
        sa.Column('content_type', sa.String(length=100), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('unused_since', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('ix_stored_files_campaign_id', 'stored_files', ['campaign_id'])
    for table, column in (('entity_pictures', 'file_key'), ('entity_pictures', 'thumb_key'), ('note_images', 'file_key')):
        op.add_column(table, sa.Column(column, sa.String(length=200), sa.ForeignKey('stored_files.key'), nullable=True))
        op.create_index(f'ix_{table}_{column}', table, [column])


def downgrade() -> None:
    for table, column in (('note_images', 'file_key'), ('entity_pictures', 'thumb_key'), ('entity_pictures', 'file_key')):
        op.drop_index(f'ix_{table}_{column}', table_name=table)
        op.drop_column(table, column)
    op.drop_index('ix_stored_files_campaign_id', table_name='stored_files')
    op.drop_table('stored_files')
