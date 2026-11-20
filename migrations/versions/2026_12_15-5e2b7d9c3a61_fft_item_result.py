"""A Roadmap item's result (Brett, Nov 20: "do you write a result after each item is completed? It should include
results, such as how much performance improved"): what it changed, with its numbers, written when it ships. Only adds.

Revision ID: 5e2b7d9c3a61
Revises: 2c6e8a1f4b57
"""

import sqlalchemy as sa
from alembic import op

revision = "5e2b7d9c3a61"
down_revision = "2c6e8a1f4b57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fft_items", sa.Column("result", sa.Text(), nullable=False, server_default=""))


def downgrade() -> None:
    op.drop_column("fft_items", "result")
