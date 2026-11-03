"""Features and Labs (Brett, 2026-11-03; app/vtt.py): campaigns' switched-on keys moved to the new names

A campaign that had the D&D Beyond bridge (or Play through askdnd, or any of its pieces) gets "sync"; one that had
askdnd's VTT gets "labs" and "vtt". A test campaign used to have every piece without switching it on, and no longer
does, so each keeps what it had: "sync", "labs" and "vtt". The thrown-dice piece is gone (now full screen for everyone,
the dice tray each person's own choice in Your dice).

Revision ID: d8e1f4a6b2c9
Revises: c4d9a2e7f1b3
Create Date: 2026-11-03 10:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd8e1f4a6b2c9'
down_revision: Union[str, Sequence[str], None] = 'c4d9a2e7f1b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SYNC = {"ddb_bridge", "play", "live_state", "dm_backup"}
VTT = {"vtt", "vtt_table"}


def upgrade() -> None:
    conn = op.get_bind()
    for cid, is_test, kept in conn.execute(sa.text("SELECT id, is_test, vtt_pieces FROM campaigns")).all():
        kept = set(kept or [])
        new = []
        if is_test or kept & SYNC:
            new.append("sync")
        if is_test or kept & VTT:
            new += ["labs", "vtt"]
        conn.execute(sa.text("UPDATE campaigns SET vtt_pieces = CAST(:p AS JSONB) WHERE id = :id"), {"p": json.dumps(new), "id": cid})


def downgrade() -> None:
    conn = op.get_bind()
    for cid, kept in conn.execute(sa.text("SELECT id, vtt_pieces FROM campaigns")).all():
        old = ["ddb_bridge"] if "sync" in (kept or []) else []
        conn.execute(sa.text("UPDATE campaigns SET vtt_pieces = CAST(:p AS JSONB) WHERE id = :id"), {"p": json.dumps(old), "id": cid})
