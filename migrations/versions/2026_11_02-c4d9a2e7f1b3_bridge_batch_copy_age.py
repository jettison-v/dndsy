"""bridge_batches.copy_age: how old askdnd's copy of the sheet was when a batch was built (Brett, 2026-11-02: a longer
log for the live test's analysis)

Revision ID: c4d9a2e7f1b3
Revises: a7c3e9f1b5d2
Create Date: 2026-11-02 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4d9a2e7f1b3'
down_revision: Union[str, Sequence[str], None] = 'a7c3e9f1b5d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('bridge_batches', sa.Column('copy_age', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('bridge_batches', 'copy_age')
