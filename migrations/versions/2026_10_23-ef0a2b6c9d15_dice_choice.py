"""each person's dice (thrown 3D dice; app/dice.py)

users.dice: {"set": a dice set, "material": glass | plastic | metal | wood, "by_type": damage dice take their damage
type's look}. Empty means askdnd's default for them.

Revision ID: ef0a2b6c9d15
Revises: de9f1a5b8c04
Create Date: 2026-10-23 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'ef0a2b6c9d15'
down_revision: Union[str, Sequence[str], None] = 'de9f1a5b8c04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('dice', postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'dice')
