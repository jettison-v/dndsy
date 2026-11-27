"""A job asked for again while it runs keeps the newer request (jobs.rerun; issue 153). Only adds.

Revision ID: b8d4f0a2c635
Revises: a7c3e9f1b524
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "b8d4f0a2c635"
down_revision = "a7c3e9f1b524"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("rerun", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("jobs", "rerun")
