"""A pull request's merge commit and when askdnd.ai first ran it (FftPull; item 39, deploys mark themselves live).
Only adds.

Revision ID: 8e4c0a2b3d76
Revises: 7d3b9f1a2c65
"""

import sqlalchemy as sa
from alembic import op

revision = "8e4c0a2b3d76"
down_revision = "7d3b9f1a2c65"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_pulls", sa.Column("merge_commit", sa.String(40), nullable=False, server_default=""))
    op.add_column("fft_pulls", sa.Column("live_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("fft_pulls", "live_at")
    op.drop_column("fft_pulls", "merge_commit")
