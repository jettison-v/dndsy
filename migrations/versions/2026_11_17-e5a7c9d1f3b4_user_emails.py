"""users.emails: each person's email choices and when the last went out (app/digest.py: the Inbox digest)

Revision ID: e5a7c9d1f3b4
Revises: d4f6b8c0e2a3
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "e5a7c9d1f3b4"
down_revision = "d4f6b8c0e2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("emails", postgresql.JSONB(), server_default="{}", nullable=False))


def downgrade() -> None:
    op.drop_column("users", "emails")
