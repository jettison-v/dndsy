"""Where an issue came from (fft_issues.source; Roadmap item 10, slice 5, Brett's OK on its scope, Nov 27). Only adds:
issues made before it keep "", and rules.source_of works theirs out from what they hold.

Revision ID: a7c3e9f1b524
Revises: f5b8d2e6a913
"""

import sqlalchemy as sa
from alembic import op

revision = "a7c3e9f1b524"
down_revision = "f5b8d2e6a913"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_issues", sa.Column("source", sa.String(16), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("fft_issues", "source")
