"""Version history: every change to the fields below is recorded as a Revision
(old value, new value, who, how), so anything edited in place can be restored.

It hooks into every database flush, so no page has to remember to record it.
Who and how come from context set elsewhere: auth.current_user sets the actor;
the importer, Claude rewrites, recap proposals and restores set the source.

Players' notes keep the same privacy in history: their revisions carry the
character id and are shown only to people who may read player notes.
"""

import contextvars
import secrets
from contextlib import contextmanager
from datetime import date, datetime
from enum import Enum

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from app.models import (
    Campaign,
    Character,
    CharacterPick,
    Entity,
    GameSession,
    GlossaryTerm,
    PlayerNote,
    Revision,
    Status,
    User,
)

TRACKED = {
    Entity: ("name", "summary", "quest_open", "status"),
    GlossaryTerm: ("term", "description"),
    GameSession: ("title", "played_on"),
    Character: ("ddb_id", "player_name", "owner_id"),
    PlayerNote: ("title", "status", "data"),
    CharacterPick: ("note",),
    Campaign: ("name", "dm_name"),
    User: ("name", "access", "is_dm"),
}
KEEP_ON_DELETE = (PlayerNote, GlossaryTerm)  # their whole content goes into history when deleted
SOURCES = {"edit": "Edited", "import": "Import", "claude": "Claude rewrite accepted", "recap": "From a recap",
           "restore": "Restored", "undo-import": "Import undone"}
FIELD_LABELS = {"summary": "Description", "quest_open": "Quest", "status": "Published", "name": "Name", "term": "Term",
                "description": "Description", "title": "Title", "played_on": "Date played", "ddb_id": "D&D Beyond link",
                "player_name": "Player name", "owner_id": "Played by", "data": "Content", "note": "Note",
                "dm_name": "DM name", "access": "Access", "is_dm": "DM", "deleted": "Deleted"}

_actor: contextvars.ContextVar[str] = contextvars.ContextVar("history_actor", default="")
_source: contextvars.ContextVar[tuple[str, str | None]] = contextvars.ContextVar("history_source", default=("edit", None))


def set_actor(email: str) -> None:
    _actor.set(email or "")


@contextmanager
def source(name: str, batch: str | None = None):
    """Mark changes made inside this block (e.g. source("import", batch))."""
    token = _source.set((name, batch))
    try:
        yield
    finally:
        _source.reset(token)


def mark(name: str) -> None:
    """Label the rest of this request's changes (they're saved when the page commits)."""
    _source.set((name, None))


def new_batch() -> str:
    return secrets.token_hex(8)


def _json(v):
    if isinstance(v, Enum):
        return v.value
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


def label(obj) -> str:
    if isinstance(obj, Entity):
        return f"{obj.name} ({obj.kind.value if obj.kind else ''})"
    if isinstance(obj, GlossaryTerm):
        return f"Glossary: {obj.term}"
    if isinstance(obj, GameSession):
        return f"Session {obj.number}" if obj.number else f"Session of {obj.played_on}"
    if isinstance(obj, Character):
        return f"Character: {obj.entity.name if obj.entity else obj.id}"
    if isinstance(obj, PlayerNote):
        return f"Note: {obj.title}"
    if isinstance(obj, CharacterPick):
        return f"Note on {obj.ref.split(':', 1)[-1]}"
    if isinstance(obj, Campaign):
        return f"Campaign: {obj.name}"
    if isinstance(obj, User):
        return f"Person: {obj.email}"
    return type(obj).__name__


def _character_id(obj) -> int | None:
    return getattr(obj, "character_id", None) if isinstance(obj, (PlayerNote, CharacterPick)) else None


@event.listens_for(Session, "before_flush")
def _record(session: Session, flush_context, instances) -> None:
    src, batch = _source.get()
    actor = _actor.get()
    for obj in list(session.dirty):
        fields = TRACKED.get(type(obj))
        if not fields or not session.is_modified(obj, include_collections=False):
            continue
        state = inspect(obj)
        for f in fields:
            hist = state.attrs[f].history
            if not hist.has_changes():
                continue
            old = hist.deleted[0] if hist.deleted else None
            new = hist.added[0] if hist.added else None
            if _json(old) == _json(new):
                continue
            session.add(Revision(table=type(obj).__tablename__, row_id=obj.id, label=label(obj)[:300], field=f,
                                 old=_json(old), new=_json(new), actor=actor, source=src, batch=batch,
                                 character_id=_character_id(obj)))
    for obj in list(session.deleted):
        if isinstance(obj, KEEP_ON_DELETE):
            content = {f: _json(getattr(obj, f)) for f in TRACKED[type(obj)]}
            if isinstance(obj, PlayerNote):
                content |= {"kind": obj.kind, "character_id": obj.character_id, "position": obj.position}
            if isinstance(obj, GlossaryTerm):
                content |= {"campaign_id": obj.campaign_id, "misheard_as": obj.misheard_as}
            session.add(Revision(table=type(obj).__tablename__, row_id=obj.id, label=label(obj)[:300], field="deleted",
                                 old=content, new=None, actor=actor, source=src, batch=batch,
                                 character_id=_character_id(obj)))


# ------------------------------------------------------------------ restore

MODELS = {m.__tablename__: m for m in TRACKED}


def _value(model, field: str, v):
    if model is Entity and field == "status":
        return Status(v) if v is not None else Status.DRAFT
    if model is GameSession and field == "played_on":
        return date.fromisoformat(v) if v else None
    return v


def target(db: Session, rev: Revision):
    model = MODELS.get(rev.table)
    return db.get(model, rev.row_id) if model else None


def can_restore(db: Session, rev: Revision) -> bool:
    if rev.field == "deleted":
        return rev.table in ("player_notes", "glossary_terms") and target(db, rev) is None
    obj = target(db, rev)
    return obj is not None and rev.field in TRACKED.get(type(obj), ())


def restore(db: Session, rev: Revision) -> str:
    """Put back the value from before this change (or recreate a deleted note or term)."""
    with source("restore"):
        if rev.field == "deleted":
            c = dict(rev.old or {})
            if rev.table == "player_notes":
                db.add(PlayerNote(character_id=c["character_id"], kind=c["kind"], title=c.get("title", ""),
                                  status=c.get("status", ""), data=c.get("data") or {}, position=c.get("position", 0)))
            else:
                db.add(GlossaryTerm(campaign_id=c["campaign_id"], term=c.get("term", ""), description=c.get("description", ""),
                                    misheard_as=c.get("misheard_as") or []))
            db.flush()
            return f"Brought back {rev.label}"
        obj = target(db, rev)
        if obj is None:
            raise ValueError("That no longer exists.")
        setattr(obj, rev.field, _value(type(obj), rev.field, rev.old))
        db.flush()
    return f"Restored {FIELD_LABELS.get(rev.field, rev.field).lower()} of {rev.label}"


def undo_import(db: Session, batch: str) -> tuple[int, int]:
    """Put back everything one import changed, newest first. A field changed again
    since the import is left alone. Returns (restored, skipped)."""
    done = skipped = 0
    revs = list(db.scalars(select(Revision).where(Revision.batch == batch).order_by(Revision.id.desc())))
    with source("undo-import", batch=None):
        for rev in revs:
            if rev.field == "deleted":
                continue
            obj = target(db, rev)
            if obj is None or _json(getattr(obj, rev.field)) != rev.new:
                skipped += 1
                continue
            setattr(obj, rev.field, _value(type(obj), rev.field, rev.old))
            done += 1
        db.flush()
    return done, skipped


def shown(value, field: str) -> str:
    """A value as the history page shows it."""
    if field == "quest_open":
        return {True: "Open", False: "Done", None: "Not set"}.get(value, str(value))
    if field == "status":
        return "Published" if value == Status.PUBLISHED.value else "Not published"
    if field == "is_dm":
        return "Yes" if value else "No"
    if value is None or value == "":
        return "—"
    if isinstance(value, dict):
        return ", ".join(f"{k}: {v}" for k, v in value.items() if v not in ("", None, [], {}))[:600]
    return str(value)

