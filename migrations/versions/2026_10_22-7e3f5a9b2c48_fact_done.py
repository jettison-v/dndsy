"""facts Claude worked into a draft description (entities.draft_fact_ids); facts can be "done"

Revision ID: 7e3f5a9b2c48
Revises: 6d2e4f8a1b37
Create Date: 2026-10-22 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '7e3f5a9b2c48'
down_revision: Union[str, Sequence[str], None] = '6d2e4f8a1b37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('entities', sa.Column('draft_fact_ids', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.execute("UPDATE facts SET status = 'merged' WHERE status = 'done'")
    op.drop_column('entities', 'draft_fact_ids')
