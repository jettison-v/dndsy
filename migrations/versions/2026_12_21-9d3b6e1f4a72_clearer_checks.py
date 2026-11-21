"""Clearer checks (Roadmap item 6, Brett's picks Nov 21): a check's goal (before, now) and whether it needs more than
one person. Only adds.

Revision ID: 9d3b6e1f4a72
Revises: 5c1e7a3d9f24
"""

import sqlalchemy as sa
from alembic import op

revision = "9d3b6e1f4a72"
down_revision = "5c1e7a3d9f24"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_check_versions", sa.Column("before", sa.Text(), nullable=False, server_default=""))
    op.add_column("fft_check_versions", sa.Column("now", sa.Text(), nullable=False, server_default=""))
    op.add_column("fft_checks", sa.Column("people", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("fft_checks", "people")
    op.drop_column("fft_check_versions", "now")
    op.drop_column("fft_check_versions", "before")
