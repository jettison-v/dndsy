"""Manage › Data: show what an import would change before anything is written.

The upload is applied inside a savepoint, compared with how things were, and rolled
back. The file waits here (in memory, for this admin, for a while) until they press
Import or Cancel. One server process runs askdnd, so memory is enough; after a
restart the admin just uploads again.
"""

import secrets
import time
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.entities import KIND_LABELS
from app.importer import import_bundle
from app.models import Entity, Status

PENDING_SECONDS = 30 * 60
_pending: dict[str, dict] = {}


def hold(bundle: dict, filename: str, email: str) -> str:
    """Keep an uploaded bundle until it's confirmed. Returns its token."""
    now = time.time()
    for token in [t for t, p in _pending.items() if now - p["at"] > PENDING_SECONDS or p["email"] == email]:
        _pending.pop(token, None)  # one waiting upload per admin
    token = secrets.token_urlsafe(16)
    _pending[token] = {"bundle": bundle, "filename": filename, "email": email, "at": now}
    return token


def take(token: str, email: str) -> dict | None:
    """The waiting upload, if it's this admin's and hasn't expired. Removes it."""
    p = _pending.pop(token or "", None)
    if p is None or p["email"] != email or time.time() - p["at"] > PENDING_SECONDS:
        return None
    return p


def peek(token: str, email: str) -> dict | None:
    p = _pending.get(token or "")
    return p if p and p["email"] == email and time.time() - p["at"] <= PENDING_SECONDS else None


def _state(db: Session) -> dict[int, dict]:
    return {e.id: {"kind": e.kind, "name": e.name, "summary": e.summary or "", "quest_open": e.quest_open,
                   "status": e.status, "rewritten": e.previous_summary is not None}
            for e in db.scalars(select(Entity))}


def preview(db: Session, bundle: dict, keep_text: bool = False) -> dict:
    """What importing `bundle` would do, without keeping any of it. Raises like import_bundle."""
    before = _state(db)
    savepoint = db.begin_nested()
    try:
        counts: Counter = import_bundle(db, bundle, keep_text=keep_text)
        db.flush()
        after = _state(db)
    finally:
        savepoint.rollback()
        db.expire_all()

    created, changed = [], []
    for eid, a in after.items():
        label = KIND_LABELS.get(a["kind"], a["kind"].value)
        b = before.get(eid)
        if b is None:
            created.append({"name": a["name"], "kind": label})
            continue
        diffs = {}
        if a["name"] != b["name"]:
            diffs["name"] = (b["name"], a["name"])
        if a["summary"] != b["summary"]:
            diffs["summary"] = (b["summary"], a["summary"])
        if a["quest_open"] != b["quest_open"]:
            fmt = {True: "Open", False: "Done", None: "Not set"}
            diffs["quest"] = (fmt[b["quest_open"]], fmt[a["quest_open"]])
        if a["status"] != b["status"]:
            diffs["status"] = ("Not published" if b["status"] != Status.PUBLISHED else "Published",
                               "Published" if a["status"] == Status.PUBLISHED else "Not published")
        if diffs:
            changed.append({"name": a["name"], "kind": label, "diffs": diffs, "rewritten": b["rewritten"]})
    unchanged = max(0, counts.get("entities updated", 0) - len(changed))  # in the file, already the same here
    other = {k: v for k, v in counts.items() if not k.startswith("entities ")}
    text_changes = sum(1 for c in changed if set(c["diffs"]) & {"summary", "quest", "status"})
    return {"created": created, "changed": changed, "unchanged": unchanged, "other": other,
            "text_changes": text_changes, "nothing": not (created or changed or other)}
