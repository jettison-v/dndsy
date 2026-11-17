"""Every line of a check's history says what happened as a key (Readers, Rebuilt, Nov 17: its timeline is drawn from
keys, never from its words). Lines written before that get their key from how they were written, once, here.

Revision ID: b4d6f8a0c2e3
Revises: f2c4e6a8b0d1
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "b4d6f8a0c2e3"
down_revision = "f2c4e6a8b0d1"
branch_labels = None
depends_on = None

# how each was written then (testing.SAYS and the engine's own lines, Nov 16–17), longest first
WRITTEN = [("Fixed · try again", "again"), ("Fix on its way", "fixed"), ("Claude ran it", "claude"), ("Another issue", "issue"),
           ("An issue", "issue"), ("Passed", "passed"), ("Failed", "failed"), ("Skipped", "skipped"), ("Ready", "ready")]


def key_of(what: str) -> str:
    if what.startswith("Note ") and "still to go" in what:
        return "fixing"
    return next((k for w, k in WRITTEN if what == w or what.startswith(w + ":")), "")


def upgrade() -> None:
    conn = op.get_bind()
    for cid, history in conn.execute(sa.text("SELECT id, history FROM checks")).all():
        changed = False
        for h in history or []:
            if "key" not in h and (k := key_of(h.get("what", ""))):
                h["key"] = k
                changed = True
        if changed:
            conn.execute(sa.text("UPDATE checks SET history = CAST(:h AS jsonb) WHERE id = :i"), {"h": json.dumps(history), "i": cid})


def downgrade() -> None:
    pass  # (the keys are only added to lines; the words stay as they were)
