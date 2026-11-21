"""How long each route takes on askdnd.ai, per day (Performance: the whole tool, its weekly look, Nov 20). Only adds.

Revision ID: 6a2e4c8f1b37
Revises: 3d7f9a2c5e18
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "6a2e4c8f1b37"
down_revision = "3d7f9a2c5e18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("request_times",
                    sa.Column("id", sa.Integer(), primary_key=True),
                    sa.Column("day", sa.Date(), nullable=False, index=True),
                    sa.Column("method", sa.String(10), nullable=False),
                    sa.Column("route", sa.String(200), nullable=False),
                    sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("total_ms", sa.BigInteger(), nullable=False, server_default="0"),
                    sa.Column("max_ms", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("bands", postgresql.JSONB(), nullable=False, server_default="[]"),
                    sa.UniqueConstraint("day", "method", "route"))


def downgrade() -> None:
    op.drop_table("request_times")
