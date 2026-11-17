"""checks.as_character: the character whose player a check is seen through (Go turns on View as for them; Testing,
slice 2). No email is kept: their player is looked up when Go is pressed.

Revision ID: c9e1a3b5d7f0
Revises: b8d0f2a4c6e9
"""

import sqlalchemy as sa
from alembic import op

revision = "c9e1a3b5d7f0"
down_revision = "b8d0f2a4c6e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("checks", sa.Column("as_character", sa.Integer, sa.ForeignKey("characters.id", ondelete="SET NULL"), nullable=True))


def downgrade() -> None:
    op.drop_column("checks", "as_character")
