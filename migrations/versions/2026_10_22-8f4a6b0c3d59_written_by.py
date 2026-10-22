"""who wrote each description and recap last (content workflows step 3: protect the DM's words)

Revision ID: 8f4a6b0c3d59
Revises: 7e3f5a9b2c48
Create Date: 2026-10-22 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8f4a6b0c3d59'
down_revision: Union[str, Sequence[str], None] = '7e3f5a9b2c48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('entities', sa.Column('summary_by', sa.String(length=200), server_default='', nullable=False))
    op.add_column('recaps', sa.Column('author_name', sa.String(length=200), server_default='', nullable=False))
    # Descriptions someone has already written by hand: the last description change in version history was an edit
    # by a signed-in person (not an import, Claude rewrite or recap suggestion).
    op.execute("""
        UPDATE entities e SET summary_by = COALESCE(NULLIF(u.name, ''), r.actor)
        FROM (SELECT DISTINCT ON (row_id) row_id, actor, source FROM revisions
              WHERE "table" = 'entities' AND field = 'summary' ORDER BY row_id, id DESC) r
        LEFT JOIN users u ON lower(u.email) = lower(r.actor)
        WHERE e.id = r.row_id AND r.source = 'edit' AND r.actor <> ''
    """)
    op.execute("UPDATE entities SET summary_by = 'claude' WHERE summary_by = '' AND summary <> ''")


def downgrade() -> None:
    op.drop_column('recaps', 'author_name')
    op.drop_column('entities', 'summary_by')
