"""Development's one queue (issue 62, Brett's picks on docs/mockups/one-development-queue/, Nov 20): Roadmap builds and
Product Area batches in one order he drags, and a build held below the line. Only adds.

Revision ID: 3d7f9a2c5e18
Revises: 8c4a1e6f2b93
"""

import sqlalchemy as sa
from alembic import op

revision = "3d7f9a2c5e18"
down_revision = "8c4a1e6f2b93"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_items", sa.Column("queue_place", sa.Integer(), nullable=True))
    op.add_column("fft_items", sa.Column("held", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("fft_areas", sa.Column("queue_place", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("fft_areas", "queue_place")
    op.drop_column("fft_items", "held")
    op.drop_column("fft_items", "queue_place")
