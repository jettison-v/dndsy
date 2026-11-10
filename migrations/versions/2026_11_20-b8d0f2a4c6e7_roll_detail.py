"""table_rolls.detail: what else a roll's card or window knew (the level cast, Advantage's reasons, riders, Hidden,
hit or miss), kept with the roll (Brett's round 2 note: every roll keeps its flavor as data; Nov 10)

Revision ID: b8d0f2a4c6e7
Revises: a7c9e1f3b5d6
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "b8d0f2a4c6e7"
down_revision = "a7c9e1f3b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("table_rolls", sa.Column("detail", postgresql.JSONB(), server_default="{}", nullable=False))


def downgrade() -> None:
    op.drop_column("table_rolls", "detail")
