"""Ready kept on Battle (feedback 14, Brett, 2026-11-05, docs/mockups/hide-ready.html): what a character readied and
the trigger, until it's used or its next turn starts.

Revision ID: b6d2f8a41c07
Revises: a1c7e5f30b92
Create Date: 2026-11-05 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'b6d2f8a41c07'
down_revision: Union[str, Sequence[str], None] = 'a1c7e5f30b92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("characters", sa.Column("readied", postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column("characters", "readied")
