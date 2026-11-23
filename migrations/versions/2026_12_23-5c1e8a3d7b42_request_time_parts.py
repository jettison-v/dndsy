"""Where a route's time goes on askdnd.ai: its database reads' time and count, and the time before the route started
(app/timing.py; Nov 23, the speed batch). Only adds.

Revision ID: 5c1e8a3d7b42
Revises: 2a7c9e4b6d18
"""

import sqlalchemy as sa
from alembic import op

revision = "5c1e8a3d7b42"
down_revision = "2a7c9e4b6d18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name in ("db_ms", "reads", "before_ms"):
        op.add_column("request_times", sa.Column(name, sa.BigInteger(), nullable=False, server_default="0"))


def downgrade() -> None:
    for name in ("db_ms", "reads", "before_ms"):
        op.drop_column("request_times", name)
