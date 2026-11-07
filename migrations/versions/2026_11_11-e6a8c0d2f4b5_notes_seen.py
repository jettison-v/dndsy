"""Your notes: what each author last saw (the badge) and was told (the card), for suggestions and feedback (Nov 7)

Existing notes start as seen and told, so only changes from now on count; feedback keeps what it was already told
(a note fixed today still gets its one card).

Revision ID: e6a8c0d2f4b5
Revises: d5f7b9c1e3a4
"""

import sqlalchemy as sa
from alembic import op

revision = "e6a8c0d2f4b5"
down_revision = "d5f7b9c1e3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in ("facts", "suggestions"):
        op.add_column(table, sa.Column("seen", sa.String(40), nullable=False, server_default=""))
        op.add_column(table, sa.Column("told", sa.String(40), nullable=False, server_default=""))
        op.execute(f"UPDATE {table} SET seen = status, told = status")
    op.add_column("feedback", sa.Column("seen", sa.String(40), nullable=False, server_default=""))
    op.execute("UPDATE feedback SET seen = (CASE status WHEN 'question' THEN 'new' ELSE status END) || ':' || "
               "(SELECT count(*) FROM jsonb_array_elements(thread) m WHERE m->>'to' = 'sender')")


def downgrade() -> None:
    op.drop_column("feedback", "seen")
    for table in ("facts", "suggestions"):
        op.drop_column(table, "told")
        op.drop_column(table, "seen")
