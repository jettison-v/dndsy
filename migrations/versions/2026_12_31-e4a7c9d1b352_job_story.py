"""Each job's story: every try, how it ended and how long it took, and who pressed Retry or Cancel (the Sync page,
Roadmap item 44, Brett's picks on docs/mockups/sync-queue/, Nov 25). Only adds.

Revision ID: e4a7c9d1b352
Revises: d39b5f7a8c21
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "e4a7c9d1b352"
down_revision = "d39b5f7a8c21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("jobs", sa.Column("story", JSONB(), nullable=False, server_default="[]"))


def downgrade() -> None:
    op.drop_column("jobs", "story")
