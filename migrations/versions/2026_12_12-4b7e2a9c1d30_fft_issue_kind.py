"""An issue's kind: a fix (something that exists is broken) or an improvement (something that exists, made better).
Brett, Nov 20: two types of work, a change to a Product Area (these) or an idea that needs discussion (the Roadmap).
Add-only: every issue so far is a fix until sorted again.

Revision ID: 4b7e2a9c1d30
Revises: 9d3f6a2c8e15
"""

import sqlalchemy as sa
from alembic import op

revision = "4b7e2a9c1d30"
down_revision = "9d3f6a2c8e15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_issues", sa.Column("kind", sa.String(12), nullable=False, server_default="fix"))


def downgrade() -> None:
    op.drop_column("fft_issues", "kind")
