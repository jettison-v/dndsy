"""The Roadmap in askdnd (Brett's picks, Nov 20, docs/mockups/roadmap-in-askdnd/): a Roadmap item's why, size, status
line and when it shipped; its scope, kept as versions; Brett's additions to it, each with Claude's answer; its steps,
each Brett's or Claude's. Only adds.

Revision ID: 7a1c3e5b9d24
Revises: 4b7e2a9c1d30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "7a1c3e5b9d24"
down_revision = "4b7e2a9c1d30"
branch_labels = None
depends_on = None


def _common() -> list:
    return [sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("item_id", sa.Integer(), sa.ForeignKey("fft_items.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("workspace_id", sa.Integer(), nullable=False, server_default="1", index=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())]


def upgrade() -> None:
    op.add_column("fft_items", sa.Column("why", sa.Text(), nullable=False, server_default=""))
    op.add_column("fft_items", sa.Column("size", sa.String(2), nullable=False, server_default=""))
    op.add_column("fft_items", sa.Column("status", sa.String(200), nullable=False, server_default=""))
    op.add_column("fft_items", sa.Column("shipped_at", sa.DateTime(timezone=True), nullable=True, server_default=sa.text("NULL")))
    op.create_table("fft_scopes", *_common(),
                    sa.Column("version", sa.Integer(), nullable=False),
                    sa.Column("what", sa.Text(), nullable=False, server_default=""),
                    sa.Column("inside", JSONB(), nullable=False, server_default="[]"),
                    sa.Column("not_now", JSONB(), nullable=False, server_default="[]"),
                    sa.Column("questions", JSONB(), nullable=False, server_default="[]"),
                    sa.Column("changed", sa.Text(), nullable=False, server_default=""),
                    sa.Column("actor", sa.String(40), nullable=False, server_default=""),
                    sa.Column("agreed_at", sa.DateTime(timezone=True), nullable=True),
                    sa.Column("agreed_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.create_table("fft_additions", *_common(),
                    sa.Column("words", sa.Text(), nullable=False),
                    sa.Column("where", sa.String(10), nullable=False, server_default="askdnd"),
                    sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
                    sa.Column("answer", sa.String(10), nullable=False, server_default=""),
                    sa.Column("answer_words", sa.Text(), nullable=False, server_default=""),
                    sa.Column("scope_version", sa.Integer(), nullable=True))
    op.create_table("fft_steps", *_common(),
                    sa.Column("place", sa.Integer(), nullable=False, server_default="0"),
                    sa.Column("whose", sa.String(10), nullable=False, server_default="claude"),
                    sa.Column("text", sa.String(200), nullable=False),
                    sa.Column("done_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_table("fft_steps")
    op.drop_table("fft_additions")
    op.drop_table("fft_scopes")
    for c in ("shipped_at", "status", "size", "why"):
        op.drop_column("fft_items", c)
