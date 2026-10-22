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
    CampaignCharacter,
    Campaign,
    Character,
    CharacterPick,
    Entity,
    EntityAlias,
    EntityRelation,
    EventKind,
    Fact,
    StoryEvent,
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
    Character: ("name", "ddb_id", "player_name", "owner_id"),
    CampaignCharacter: ("wild_shape_keep",),
    PlayerNote: ("title", "status", "data"),
    CharacterPick: ("note",),
    Campaign: ("name", "dm_name"),
    User: ("name", "access", "is_dm"),
    StoryEvent: ("text", "kind", "status"),
    EntityAlias: ("alias", "misspelling", "note"),
    EntityRelation: ("type", "note"),
    Fact: ("text", "status"),
}
# Their whole content goes into history when deleted, so it can be brought back
KEEP_ON_DELETE = (PlayerNote, GlossaryTerm, StoryEvent, EntityAlias, EntityRelation, Fact, Entity)
# Everything needed to recreate a deleted row (besides its tracked fields)
DELETE_CONTEXT = {
    PlayerNote: ("kind", "character_id", "position", "campaign_id"),
    GlossaryTerm: ("campaign_id", "misheard_as"),
    StoryEvent: ("session_id", "position"),
    EntityAlias: ("entity_id",),
    EntityRelation: ("from_entity_id", "to_entity_id"),
    Fact: ("entity_id", "author_name", "author_email", "kind"),
    Entity: ("campaign_id", "kind"),
}
BRING_BACK = ("player_notes", "glossary_terms", "story_events", "entity_aliases", "relationships", "facts")
SOURCES = {"edit": "Edited", "import": "Import", "claude": "Claude rewrite accepted", "recap": "From a recap",
           "restore": "Restored", "undo-import": "Import undone"}
FIELD_LABELS = {"summary": "Description", "quest_open": "Quest", "status": "Published", "name": "Name", "term": "Term",
                "description": "Description", "title": "Title", "played_on": "Date played", "ddb_id": "D&D Beyond link",
                "player_name": "Player name", "owner_id": "Played by", "data": "Content", "note": "Note",
                "dm_name": "DM name", "access": "Access", "is_dm": "DM", "deleted": "Deleted",
                "wild_shape_keep": "Kept in Wild Shape", "text": "Text", "kind": "Kind", "alias": "Name",
                "misspelling": "Misspelling", "type": "Relationship"}

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


def _entity_name(obj, entity_id) -> str:
    from sqlalchemy.orm import object_session

    e = object_session(obj).get(Entity, entity_id) if entity_id and object_session(obj) else None
    return e.name if e else "an entry"


def label(obj) -> str:
    if isinstance(obj, StoryEvent):
        gs = obj.session
        return f"Key moment, {'Session ' + str(gs.number) if gs and gs.number else 'a session'}"
    if isinstance(obj, EntityAlias):
        return f"Other name of {_entity_name(obj, obj.entity_id)}"
    if isinstance(obj, EntityRelation):
        return f"Relationship: {_entity_name(obj, obj.from_entity_id)} {obj.type.replace('_', ' ')} {_entity_name(obj, obj.to_entity_id)}"
    if isinstance(obj, Fact):
        return f"Fact on {_entity_name(obj, obj.entity_id)}"
    if isinstance(obj, Entity):
        return f"{obj.name} ({obj.kind.value if obj.kind else ''})"
    if isinstance(obj, GlossaryTerm):
        return f"Glossary: {obj.term}"
    if isinstance(obj, GameSession):
        return f"Session {obj.number}" if obj.number else f"Session of {obj.played_on}"
    if isinstance(obj, CampaignCharacter):
        return f"Character: {obj.character.name if obj.character else obj.character_id}"
    if isinstance(obj, Character):
        return f"Character: {obj.name or obj.id}"
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
            content |= {f: _json(getattr(obj, f)) for f in DELETE_CONTEXT[type(obj)]}
            if isinstance(obj, StoryEvent):
                content["entity_ids"] = [e.id for e in obj.entities]
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
    if model is StoryEvent and field == "status":
        return Status(v) if v is not None else Status.DRAFT
    if model is StoryEvent and field == "kind":
        return EventKind(v)
    return v


def target(db: Session, rev: Revision):
    model = MODELS.get(rev.table)
    return db.get(model, rev.row_id) if model else None


def can_restore(db: Session, rev: Revision) -> bool:
    if rev.field == "deleted":
        return rev.table in BRING_BACK and target(db, rev) is None
    obj = target(db, rev)
    return obj is not None and rev.field in TRACKED.get(type(obj), ())


def restore(db: Session, rev: Revision) -> str:
    """Put back the value from before this change (or recreate a deleted note or term)."""
    with source("restore"):
        if rev.field == "deleted":
            c = dict(rev.old or {})
            if rev.table == "player_notes":
                db.add(PlayerNote(character_id=c["character_id"], kind=c["kind"], title=c.get("title", ""),
                                  status=c.get("status", ""), data=c.get("data") or {}, position=c.get("position", 0),
                                  campaign_id=c.get("campaign_id")))
            elif rev.table == "glossary_terms":
                db.add(GlossaryTerm(campaign_id=c["campaign_id"], term=c.get("term", ""), description=c.get("description", ""),
                                    misheard_as=c.get("misheard_as") or []))
            elif rev.table == "story_events":
                ev = StoryEvent(session_id=c["session_id"], position=c.get("position", 0), kind=EventKind(c["kind"]),
                                text=c.get("text", ""), status=Status(c.get("status") or Status.DRAFT.value))
                ev.entities = [e for e in (db.get(Entity, i) for i in c.get("entity_ids") or []) if e]
                db.add(ev)
            elif rev.table == "entity_aliases":
                db.add(EntityAlias(entity_id=c["entity_id"], alias=c.get("alias", ""), note=c.get("note", ""),
                                   misspelling=bool(c.get("misspelling"))))
            elif rev.table == "relationships":
                db.add(EntityRelation(from_entity_id=c["from_entity_id"], to_entity_id=c["to_entity_id"], type=c.get("type", ""),
                                      note=c.get("note", "")))
            elif rev.table == "facts":
                db.add(Fact(entity_id=c["entity_id"], text=c.get("text", ""), status=c.get("status", "merged"),
                            author_name=c.get("author_name", ""), author_email=c.get("author_email", ""), kind=c.get("kind", "addition")))
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

