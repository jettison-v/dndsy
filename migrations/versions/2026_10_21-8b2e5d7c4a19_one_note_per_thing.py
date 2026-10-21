"""one note per thing: merge shortlist and reminder notes into note picks

Revision ID: 8b2e5d7c4a19
Revises: 6d3f1a8c2e57
Create Date: 2026-10-21 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '8b2e5d7c4a19'
down_revision: Union[str, Sequence[str], None] = '6d3f1a8c2e57'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # One "note" row per (character, ref): the shortlist note, then the reminder note if it says something else.
    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT character_id, ref, label, kind, note FROM character_picks "
        "WHERE kind IN ('fav', 'remind') AND note <> '' ORDER BY character_id, ref, kind"
    )).all()
    merged: dict[tuple[int, str], dict] = {}
    for character_id, ref, label, kind, note in rows:  # "fav" sorts before "remind"
        m = merged.setdefault((character_id, ref), {"label": label, "notes": []})
        if note.strip() and note.strip() not in m["notes"]:
            m["notes"].append(note.strip())
    for (character_id, ref), m in merged.items():
        conn.execute(sa.text(
            "INSERT INTO character_picks (character_id, kind, ref, label, note, created_at, updated_at) "
            "VALUES (:c, 'note', :r, :l, :n, now(), now()) ON CONFLICT (character_id, kind, ref) DO NOTHING"
        ), {"c": character_id, "r": ref, "l": m["label"], "n": " · ".join(m["notes"])[:500]})
    conn.execute(sa.text("UPDATE character_picks SET note = '' WHERE kind IN ('fav', 'remind')"))


def downgrade() -> None:
    # Put each note back on the thing's shortlist pick (or reminder), then drop the note rows.
    conn = op.get_bind()
    conn.execute(sa.text(
        "UPDATE character_picks p SET note = n.note FROM character_picks n "
        "WHERE n.kind = 'note' AND p.kind IN ('fav', 'remind') AND p.character_id = n.character_id AND p.ref = n.ref"
    ))
    conn.execute(sa.text("DELETE FROM character_picks WHERE kind = 'note'"))
