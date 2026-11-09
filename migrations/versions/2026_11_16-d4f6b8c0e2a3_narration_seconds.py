"""How long each narration plays (Listen's length, Brett Nov 9)

Revision ID: d4f6b8c0e2a3
Revises: c3e5a7b9d1f2
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op

revision = "d4f6b8c0e2a3"
down_revision = "c3e5a7b9d1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("recaps", sa.Column("narration_seconds", sa.Integer(), nullable=True))
    op.add_column("recaps", sa.Column("tale_narration_seconds", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("recaps", "tale_narration_seconds")
    op.drop_column("recaps", "narration_seconds")
