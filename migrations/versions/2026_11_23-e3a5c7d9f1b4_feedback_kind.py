"""feedback.kind: what a note is, picked when it's sent (Brett, Nov 16): broken, idea or question. Notes sent before
this have none ("") until they're sorted once (scripts/feedback.py kind).

Revision ID: e3a5c7d9f1b4
Revises: d1f3a5b7c9e2
"""

import sqlalchemy as sa
from alembic import op

revision = "e3a5c7d9f1b4"
down_revision = "d1f3a5b7c9e2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("feedback", sa.Column("kind", sa.String(20), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("feedback", "kind")
