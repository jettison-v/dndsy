"""Reviewing a scope (issue 54, Brett's picks on docs/mockups/roadmap-scope-review/, Nov 20): Needs changes… on a
version, Claude's suggested answers to its open questions, and comments on one line of it, held until Brett answers the
scope. Only adds.

Revision ID: 8c4a1e6f2b93
Revises: 5e2b7d9c3a61
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "8c4a1e6f2b93"
down_revision = "5e2b7d9c3a61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_scopes", sa.Column("changes_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("fft_scopes", sa.Column("suggested", postgresql.JSONB(), nullable=False, server_default="[]"))
    op.add_column("fft_additions", sa.Column("on_line", sa.String(12), nullable=False, server_default=""))
    op.add_column("fft_additions", sa.Column("line_text", sa.Text(), nullable=False, server_default=""))
    op.add_column("fft_additions", sa.Column("on_version", sa.Integer(), nullable=True))
    op.add_column("fft_additions", sa.Column("held", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    for t, c in (("fft_additions", "held"), ("fft_additions", "on_version"), ("fft_additions", "line_text"), ("fft_additions", "on_line"),
                 ("fft_scopes", "suggested"), ("fft_scopes", "changes_at")):
        op.drop_column(t, c)
