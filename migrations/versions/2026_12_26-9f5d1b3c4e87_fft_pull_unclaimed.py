"""A pull request opened for work nobody claimed (FftPull.unclaimed; item 39, claims). Only adds.

Revision ID: 9f5d1b3c4e87
Revises: 8e4c0a2b3d76
"""

import sqlalchemy as sa
from alembic import op

revision = "9f5d1b3c4e87"
down_revision = "8e4c0a2b3d76"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_pulls", sa.Column("unclaimed", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("fft_pulls", "unclaimed")
