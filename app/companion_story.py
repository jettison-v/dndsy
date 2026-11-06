"""A companion's World entry (Your creatures, slice 9; Creatures as Characters board 4: "a companion gets an entry like
any NPC, linked to its master"). The first time a character's familiar or steed is cast through askdnd, askdnd makes it
a Campaign › World entry (a Creature, published: it's what the table did, not a draft), linked to its master ("serves"),
and from then keeps what it's done on its master (`Character.creature_story`): the forms it has taken, what it is
(Celestial, Fey or Fiend), when it went to the pocket dimension, came back, disappeared or was dismissed. The entry's
page shows that (`view`); what the recaps say about it comes the usual way, as its key moments, once its name is in a
reviewed recap. One that leaves (dismissed forever) keeps its entry.

A summon spirit isn't kept: a new one comes each casting and goes with Concentration."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import relations
from app.models import Character, Entity, EntityAlias, EntityKind, EntityPicture, EntityRelation, EventEntity, Fact, GameSession, Status

TABLE_TIME = ZoneInfo("America/Los_Angeles")  # (the table's evening: the server's clock is UTC, already tomorrow by then)

FAMILIAR, STEED = "familiar", "steed"
ROLES = {FAMILIAR: "familiar", STEED: "steed"}
# What each event says on the entry
SAYS = {"cast": "cast", "form": "took a new form", "away": "went to the pocket dimension", "back": "came back",
        "gone": "disappeared at 0 Hit Points", "dismissed": "was dismissed", "left": "left at a Long Rest (Wild Companion)"}


def _master_entity(db: Session, ch: Character) -> Entity | None:
    m = ch.membership
    return db.get(Entity, m.entity_id) if m and m.entity_id else None


def note(db: Session, ch: Character, role: str, what: str, name: str = "", form: str = "", kind: str = "", creature: str = "") -> int | None:
    """One thing a character's familiar or steed did, kept for its entry; casting it makes the entry the first time
    (with a name: the one given, else "<master>'s familiar"). `creature` is its picture's key (pictures.creature_key).
    Returns the id of an entry made now, else None (an entry the DM wrote already is never "made": Undo leaves it)."""
    if not ch.campaign_id or role not in ROLES:
        return None
    story = dict(ch.creature_story or {})
    s = dict(story.get(role) or {})
    entity = db.get(Entity, s["entity"]) if s.get("entity") else None
    made = None
    called = (name or "").strip()[:200]
    if entity is None and what == "cast":
        from app.entities import find_by_name

        title = called or f"{ch.name}'s {ROLES[role]}"
        entity = find_by_name(db, ch.campaign_id, title)  # (one the DM wrote already: that's its entry)
        if entity is None or entity.kind in (EntityKind.PC, EntityKind.PLACE, EntityKind.QUEST, EntityKind.FACTION):
            entity = Entity(campaign_id=ch.campaign_id, kind=EntityKind.CREATURE, name=title, status=Status.PUBLISHED, summary="", summary_by="")
            db.add(entity)
            db.flush()
            made = s["made"] = entity.id
        if (master := _master_entity(db, ch)) is not None and master.id != entity.id:
            relations.add(db, entity, "serves", master)
        s["entity"] = entity.id
    elif entity is not None and called and called.lower() != entity.name.lower():  # (named, or renamed: the old name stays an alias)
        # (each name once: renamed back and forth, Pip → Mote → Pip → Mote, the old name may be an alias already, and the
        # new one stops being one; Sentry ASKDND-V2-M, Nov 6: the second "Pip" alias failed the cast)
        have = {a.alias.lower(): a for a in entity.aliases}
        if not entity.name.endswith(f"'s {ROLES[role]}") and entity.name.lower() not in have:
            entity.aliases.append(EntityAlias(alias=entity.name))
        if (same := have.get(called.lower())) is not None:
            entity.aliases.remove(same)
        entity.name = called
    log = list(s.get("log") or [])
    before = next((x["form"] for x in reversed(log) if x.get("form")), "")
    around = bool(log) and log[-1]["what"] in ("cast", "form", "away", "back")
    if what == "cast" and around and before and form and form != before:
        what = "form"  # (one familiar at a time: casting again while it's around gives it a new form)
    if creature:
        s["creature"] = creature
    log.append({"on": datetime.now(TABLE_TIME).date().isoformat(), "what": what, **({"form": form} if form else {}), **({"kind": kind} if kind else {})})
    s["log"] = log[-100:]
    story[role] = s
    ch.creature_story = story
    return made


def restore(db: Session, ch: Character, was: dict | None, made: int | None) -> None:
    """Undo's half: the story as it was before the cast, and the entry it made, if it made one and nothing else has
    been added to it since."""
    ours = {(s or {}).get("made") for s in (ch.creature_story or {}).values()}  # (only an entry this story made itself)
    ch.creature_story = was or {}
    kept = {(s or {}).get("entity") for s in (ch.creature_story or {}).values()}
    if made and made in ours and made not in kept:
        e = db.get(Entity, made)
        if e is not None and e.campaign_id == ch.campaign_id and e.kind == EntityKind.CREATURE and not e.summary and not _added(db, e.id):
            db.delete(e)


def _added(db: Session, entity_id: int) -> bool:
    """Something someone added to the entry since: a fact, a key moment, a picture or a relationship other than serving."""
    for col in (Fact.entity_id, EventEntity.entity_id, EntityPicture.entity_id):
        if db.scalar(select(col).where(col == entity_id).limit(1)) is not None:
            return True
    other = select(EntityRelation.id).where(((EntityRelation.from_entity_id == entity_id) & (EntityRelation.type != "serves"))
                                            | (EntityRelation.to_entity_id == entity_id)).limit(1)
    return db.scalar(other) is not None


def _when(db: Session, campaign_id: int, on: str) -> str:
    """'Nov 5', or 'Nov 5 (session 12)' when a session was played that day."""
    d = date.fromisoformat(on)
    n = db.scalar(select(GameSession.number).where(GameSession.campaign_id == campaign_id, GameSession.played_on == d).limit(1))
    return f"{d.strftime('%b')} {d.day}" + (f" (session {n})" if n else "")


def view(db: Session, entity: Entity) -> dict | None:
    """What its entry shows about it: whose it is, where it is now, the forms it has taken, what it is, and the times it
    went away and came back. None for an entry that isn't a companion's."""
    if entity.kind == EntityKind.PC or not db.scalar(select(EntityRelation.id).where(EntityRelation.from_entity_id == entity.id,
                                                                                      EntityRelation.type == "serves").limit(1)):
        return None  # (a companion serves its master: anything else isn't one, without looking at every character)
    from app.characters import campaign_characters

    for ch in campaign_characters(db, entity.campaign_id):
        for role, s in (ch.creature_story or {}).items():
            if (s or {}).get("entity") != entity.id:
                continue
            log = s.get("log") or []
            forms: dict[str, str] = {}
            for x in log:
                if x.get("form") and x["form"] not in forms:
                    forms[x["form"]] = _when(db, entity.campaign_id, x["on"])
            last = next((x for x in reversed(log) if x["what"] in ("cast", "form", "away", "back", "gone", "dismissed", "left")), None)
            form = next((x["form"] for x in reversed(log) if x.get("form")), "")
            kind = next((x["kind"] for x in reversed(log) if x.get("kind")), "")
            now = {"cast": "Here", "form": "Here", "back": "Here", "away": "In the pocket dimension", "gone": "Gone (0 Hit Points)",
                   "dismissed": "Dismissed", "left": "Left (Wild Companion)"}.get(last["what"] if last else "", "")
            return {"master": ch, "role": ROLES[role], "creature": s.get("creature") or (FAMILIAR if role == FAMILIAR else ""), "now": now + (f", as {_a(form)}" if form and now == "Here" else ""),
                    "kind": kind, "forms": [{"form": f, "when": w} for f, w in forms.items()],
                    "times": [{"what": SAYS[x["what"]], "when": _when(db, entity.campaign_id, x["on"])}
                              for x in log if x["what"] in ("away", "back", "gone", "dismissed", "left")]}
    return None


def _a(form: str) -> str:
    return f"an {form}" if form[:1].lower() in "aeiou" else f"a {form}"
