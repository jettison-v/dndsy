"""The work flow's slice 3: a lane on every plan, an incident's Careful floor, and R17 retired

Revision ID: 4e2b7d9c1a63
Revises: 0c3e5a7b9d14
Create Date: 2026-12-08

Columns only added (database changes only add; removals come later). R17 retired (Brett's pick 5, Nov 19: approving a
player's note is the OK for its fix): an issue still waiting for his OK to merge goes back to fixing, with an event
saying why, so its pull request may merge.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4e2b7d9c1a63"
down_revision: str | Sequence[str] | None = "0c3e5a7b9d14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("fft_areas", sa.Column("lane", sa.String(10), nullable=False, server_default=""))
    op.add_column("fft_areas", sa.Column("lane_by", sa.String(80), nullable=False, server_default=""))
    op.add_column("fft_areas", sa.Column("lane_why", sa.String(300), nullable=False, server_default=""))
    op.add_column("fft_areas", sa.Column("careful_until", sa.DateTime(timezone=True), nullable=True))
    bind = op.get_bind()
    held = [r[0] for r in bind.execute(sa.text("SELECT id FROM fft_issues WHERE state = 'merge_ok'"))]
    for issue_id in held:
        bind.execute(sa.text("UPDATE fft_issues SET state = 'fixing' WHERE id = :i"), {"i": issue_id})
        bind.execute(sa.text("INSERT INTO fft_events (workspace_id, at, actor, kind, thing, thing_id, data) "
                             "VALUES (1, now(), 'askdnd', 'issue_merge_okd', 'issue', :i, CAST(:d AS jsonb))"),
                     {"i": issue_id, "d": '{"why": "R17 retired: approving a player\\u0027s note is the OK for its fix"}'})


def downgrade() -> None:
    for col in ("careful_until", "lane_why", "lane_by", "lane"):
        op.drop_column("fft_areas", col)
