"""Found, Fixed, Tried: the Product Taxonomy (Brett, Nov 18, docs/mockups/product-taxonomy/)

Revision ID: 5b7d2e9a1c44
Revises: 3f9c1a7e5b20
Create Date: 2026-12-04

Every issue gets a Feature (`fft_issues.feature`) and each Product Area its own batch of fixes (`fft_areas.key`). The
batches made by hand under Fixes and polish go: one named like a Product Area becomes that Product Area's batch (its
place, rounds and lock kept); the others are archived, and each of their open issues says on its conversation where it
was, so Claude can sort it (Testing's Claude missed lists an open issue with no Feature until it has one).
"""
import json
from collections.abc import Sequence
from pathlib import Path

import sqlalchemy as sa
from alembic import op

revision: str = "5b7d2e9a1c44"
down_revision: str | Sequence[str] | None = "3f9c1a7e5b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TAXONOMY = Path(__file__).resolve().parents[2] / "app" / "data" / "taxonomy.json"


def upgrade() -> None:
    op.add_column("fft_areas", sa.Column("key", sa.String(20), nullable=False, server_default=""))
    op.create_index("ix_fft_areas_key", "fft_areas", ["key"])
    op.add_column("fft_issues", sa.Column("feature", sa.String(20), nullable=False, server_default=""))
    op.create_index("ix_fft_issues_feature", "fft_issues", ["feature"])

    bind = op.get_bind()
    by_title = {a["title"].lower(): a["key"] for a in json.loads(TAXONOMY.read_text())["areas"]}
    hand = bind.execute(sa.text(
        "SELECT a.id, a.title FROM fft_areas a JOIN fft_items i ON i.id = a.item_id "
        "WHERE i.standing AND a.key = '' AND NOT a.archived ORDER BY a.id")).all()
    taken = set()
    for area_id, title in hand:
        key = by_title.get(title.strip().lower())
        if key and key not in taken:
            taken.add(key)
            bind.execute(sa.text("UPDATE fft_areas SET key = :k WHERE id = :id"), {"k": key, "id": area_id})
            continue
        for (issue_id,) in bind.execute(sa.text("SELECT id FROM fft_issues WHERE area_id = :a AND state != 'closed' ORDER BY id"), {"a": area_id}).all():
            bind.execute(sa.text("INSERT INTO fft_lines (issue_id, who, \"to\", text, approved) VALUES (:i, 'askdnd', '', :t, true)"),
                         {"i": issue_id, "t": f"Was in the batch “{title}” until Product Areas (Nov 18)."})
            bind.execute(sa.text("INSERT INTO fft_events (actor, kind, thing, thing_id, data, area_id) "
                                 "VALUES ('askdnd', 'issue_moved', 'issue', :i, CAST(:d AS jsonb), NULL)"),
                         {"i": issue_id, "d": json.dumps({"was": area_id, "why": "product areas"})})
            bind.execute(sa.text("UPDATE fft_issues SET area_id = NULL WHERE id = :i"), {"i": issue_id})
        bind.execute(sa.text("UPDATE fft_checks SET area_id = NULL WHERE area_id = :a AND NOT retired"), {"a": area_id})
        bind.execute(sa.text("UPDATE fft_areas SET archived = true, lock_owner = '', lock_until = NULL WHERE id = :a"), {"a": area_id})
        bind.execute(sa.text("INSERT INTO fft_events (actor, kind, thing, thing_id, data, area_id) "
                             "VALUES ('askdnd', 'area_archived', 'area', :a, CAST(:d AS jsonb), :a)"),
                     {"a": area_id, "d": json.dumps({"why": "product areas"})})


def downgrade() -> None:
    op.drop_index("ix_fft_issues_feature", "fft_issues")
    op.drop_column("fft_issues", "feature")
    op.drop_index("ix_fft_areas_key", "fft_areas")
    op.drop_column("fft_areas", "key")
