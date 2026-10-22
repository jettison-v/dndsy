"""The living campaign record: entity pages, facts added by anyone at the
table (merged or rejected by a reviewer, with undo), Claude's "Regenerate
description", and the @-mention name suggestions used by every text box.

Merging a fact shows it on the entity page as written; it never rewrites the
summary. Rewriting the summary is the separate reviewer action below.
"""

import json
from collections.abc import Callable

import anthropic
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from app import spending
from app.extraction import MODEL, ExtractionError, _cost, _norm, session_label, timeline
from app.models import (
    Entity,
    EntityAlias,
    EntityKind,
    EventEntity,
    EventKind,
    ExtractionRun,
    Fact,
    GlossaryTerm,
    Status,
    StoryEvent,
)


class EntityError(ValueError):
    pass


KIND_LABELS = {
    EntityKind.PC: "Player character",
    EntityKind.NPC: "Person",
    EntityKind.PLACE: "Place",
    EntityKind.FACTION: "Faction",
    EntityKind.QUEST: "Quest",
    EntityKind.ITEM: "Item",
    EntityKind.CREATURE: "Creature",
    EntityKind.OTHER: "Other",
}


# --- Facts -----------------------------------------------------------------------


def add_fact(db: Session, entity: Entity, text: str, user: dict, kind: str = "addition", merged: bool = False) -> Fact:
    """A fact from someone at the table; `merged` puts it straight on the page (the DM's)."""
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise EntityError("Write the fact first.")
    if len(text) > 4000:
        raise EntityError("That's a bit long for one fact (4,000 characters max).")
    fact = Fact(
        entity_id=entity.id,
        kind="correction" if kind == "correction" else "addition",
        text=text,
        author_name=(user.get("name") or user.get("email") or "")[:200],
        author_email=(user.get("email") or "")[:320],
        status="merged" if merged else "pending",
    )
    db.add(fact)
    return fact


def merge_fact(fact: Fact) -> None:
    """Add the fact to the entity page as written (the summary is left alone)."""
    if fact.status != "pending":
        raise EntityError("That fact was already decided.")
    fact.status = "merged"


def reject_fact(fact: Fact) -> None:
    if fact.status != "pending":
        raise EntityError("That fact was already decided.")
    fact.status = "rejected"


def undo_fact(fact: Fact) -> None:
    """Back one step: a Done fact returns to the page; a merged or rejected one to waiting."""
    fact.status = "merged" if fact.status == "done" else "pending"


def done_fact(fact: Fact) -> None:
    """The DM or an editor takes a fact off the page's list (it's in the description now, or no longer needed).
    It stays under Done, with Undo (Brett, 2026-10-22)."""
    if fact.status != "merged":
        raise EntityError("Only facts on the page can be marked Done.")
    fact.status = "done"


def merged_facts(db: Session, entity_id: int) -> list[Fact]:
    return list(db.scalars(select(Fact).where(Fact.entity_id == entity_id, Fact.status == "merged").order_by(Fact.id)))


# --- Key moments -------------------------------------------------------------------


def moments(db: Session, entity: Entity) -> list[dict]:
    """Every published key moment that mentions the entity, in story order."""
    events = list(
        db.scalars(
            select(StoryEvent)
            .join(EventEntity, EventEntity.event_id == StoryEvent.id)
            .where(EventEntity.entity_id == entity.id, StoryEvent.status == Status.PUBLISHED)
        )
    )
    if not events:
        return []
    order = {s.id: i for i, s in enumerate(timeline(db, entity.campaign_id))}
    events.sort(key=lambda e: (order.get(e.session_id, 10**6), e.position, e.id))
    return [{"e": e, "label": session_label(e.session)} for e in events]


# --- Regenerate description (Claude) ----------------------------------------------

DESCRIBE_SYSTEM = """\
You keep the campaign record for one Dungeons & Dragons (2024 rules) table. \
Rewrite one entry's summary (a person, place, faction, quest, item or \
creature) so it reflects everything the table knows now.

- 1-4 sentences, neutral, third person. Plain text, no headings or lists.
- Use only the material given: the current summary, facts added by people at \
the table (treat them as true), relationships, and key moments in story order \
(later ones are more recent).
- Key moments of kind "theory" are speculation; you may mention them only as \
open questions, never as fact.
- Keep names spelled exactly as given. Don't invent anything.
- Describe; never advise the players or tell them what to do.
- In used_fact_ids, list the id of every fact from the table that your summary \
now covers, so it can come off the list of facts."""

DESCRIBE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "used_fact_ids"],
    "properties": {"summary": {"type": "string"}, "used_fact_ids": {"type": "array", "items": {"type": "integer"}}},
}


def build_describe_messages(db: Session, entity: Entity) -> list[dict]:
    from app.relations import lines_for

    parts = [f"Name: {entity.name}", f"Kind: {KIND_LABELS.get(entity.kind, entity.kind.value)}"]
    if entity.kind == EntityKind.QUEST and entity.quest_open is not None:
        parts.append("Quest status: " + ("open" if entity.quest_open else "done"))
    if entity.aliases:
        parts.append("Also known as: " + ", ".join(a.alias for a in entity.aliases))
    parts.append("\nCurrent summary:\n" + (entity.summary or "(none yet)"))
    facts = merged_facts(db, entity.id)
    if facts:
        parts.append("\nFacts from the table (corrections override the summary):\n" + "\n".join(f"- [fact {f.id}] {f.labeled_text}" for f in facts))
    rels = lines_for(db, entity)
    if rels:
        parts.append("\nRelationships:\n" + "\n".join(f"- {l.label} {l.other.name}" + (f" ({l.note})" if l.note else "") for l in rels))
    ms = moments(db, entity)
    if ms:
        parts.append("\nKey moments (story order):\n" + "\n".join(f"- [{m['label']}] ({m['e'].kind.value}) {m['e'].text}" for m in ms))
    return [{"role": "user", "content": [{"type": "text", "text": "<entry>\n" + "\n".join(parts) + "\n</entry>\nWrite the new summary."}]}]


def regenerate(db: Session, entity: Entity, client_factory: Callable[[], anthropic.Anthropic] | None = None) -> str:
    """Ask Claude for a new summary and keep it as the entity's draft for a
    reviewer to accept, edit or discard. Recorded as an ExtractionRun ("entity")."""
    run = ExtractionRun(entity_id=entity.id, source="entity", model=MODEL, status="running")
    db.add(run)
    db.commit()
    try:
        spending.check(db)  # the monthly limit set on Manage › Usage
        client = (client_factory or anthropic.Anthropic)()
        with client.beta.messages.stream(
            model=MODEL,
            max_tokens=4000,
            system=DESCRIBE_SYSTEM,
            messages=build_describe_messages(db, entity),
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": DESCRIBE_SCHEMA}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason == "refusal":
            raise ExtractionError("Claude declined this one.")
        text = next((b.text for b in response.content if b.type == "text"), "")
        out = json.loads(text)
        summary = out["summary"].strip()
        if not summary:
            raise ExtractionError("Claude returned an empty summary.")
        entity.draft_summary = summary
        merged = {f.id for f in merged_facts(db, entity.id)}
        entity.draft_fact_ids = sorted(merged & {i for i in out.get("used_fact_ids") or [] if isinstance(i, int)})
        run.status = "done"
        run.input_tokens = (response.usage.input_tokens or 0) + (response.usage.cache_read_input_tokens or 0) + (
            response.usage.cache_creation_input_tokens or 0
        )
        run.output_tokens = response.usage.output_tokens or 0
        run.cost_usd = _cost(response.usage)
        db.commit()
        return summary
    except (ExtractionError, anthropic.APIError, json.JSONDecodeError, KeyError, AttributeError) as e:
        db.rollback()
        run = db.merge(run)
        run.status, run.error = "error", (str(e) or type(e).__name__)[:2000]
        db.commit()
        raise ExtractionError(run.error) from e


def accept_description(entity: Entity, text: str | None = None) -> None:
    """Use Claude's draft (or the reviewer's edit of it) as the summary; keep the old one for Undo."""
    new = (text if text is not None else entity.draft_summary or "").replace("\r\n", "\n").strip()
    if not new:
        raise EntityError("There's no new description to use.")
    from app.history import mark

    mark("claude")  # version history: this description came from Claude
    entity.previous_summary = entity.summary or ""
    entity.summary = new
    entity.draft_summary = None
    # Facts Claude worked in come off the list ("Added to the description" under Done, with Undo)
    db = object_session(entity)
    if db is not None and entity.draft_fact_ids:
        for fact in db.scalars(select(Fact).where(Fact.id.in_(entity.draft_fact_ids), Fact.status == "merged")):
            fact.status = "done"
    entity.draft_fact_ids = None


def discard_description(entity: Entity) -> None:
    entity.draft_summary = None
    entity.draft_fact_ids = None


def set_description(entity: Entity, text: str) -> None:
    """The DM's or an editor's own words, no Claude (Brett, 2026-10-22). Undo keeps the earlier one."""
    new = (text or "").replace("\r\n", "\n").strip()
    if len(new) > 4000:
        raise EntityError("That's a bit long for a description (4,000 characters max).")
    if new == (entity.summary or ""):
        raise EntityError("Nothing changed.")
    entity.previous_summary = entity.summary or ""
    entity.summary = new


def rename(entity: Entity, name: str) -> None:
    """A new name; the old one is kept as another name, so links, @-mentions and Claude still find it."""
    new = " ".join((name or "").split())
    if not new:
        raise EntityError("Enter a name.")
    if len(new) > 200:
        raise EntityError("That name is too long.")
    if new == entity.name:
        raise EntityError("That's already the name.")
    old = entity.name
    entity.name = new
    if not any(a.alias.casefold() == old.casefold() for a in entity.aliases):
        entity.aliases.append(EntityAlias(alias=old, misspelling=False, note="earlier name"))


def undo_description(entity: Entity) -> None:
    if entity.previous_summary is None:
        raise EntityError("Nothing to undo.")
    entity.summary, entity.previous_summary = entity.previous_summary, None


# --- @-mentions ---------------------------------------------------------------------

# People and places are what you usually mean; quests and items come last.
MENTION_ORDER = {
    EntityKind.PC: 0,
    EntityKind.NPC: 1,
    EntityKind.PLACE: 2,
    EntityKind.FACTION: 3,
    EntityKind.CREATURE: 4,
    EntityKind.ITEM: 5,
    EntityKind.OTHER: 6,
    EntityKind.QUEST: 7,
}


def mention_suggestions(db: Session, campaign_id: int, q: str, include_drafts: bool = False, limit: int = 8) -> list[dict]:
    """Entity names (and glossary spellings) matching what follows an "@".
    Matches the start of the name or of any word in it, aliases, and the
    glossary's misheard_as spellings; returns the canonical name to insert."""
    q = _norm(q)
    if not q:
        return []

    def hit(text: str) -> int | None:
        """0: the name starts with it (ignoring a leading "The"); 1: a later word
        does; None: no match. Later words also count how far in they are."""
        t = _norm(text)
        words = t.split()
        if t.startswith(q) or (words[:1] == ["the"] and " ".join(words[1:]).startswith(q)):
            return 0
        for i, w in enumerate(words):
            if w.startswith(q):
                return 1 + i / 100  # earlier word wins within the same tier
        return None

    found: dict[str, dict] = {}

    def offer(name: str, kind: str, rank: float, via: str = "", order: int = 9):
        key = _norm(name)
        candidate = {"name": name, "kind": kind, "via": via, "rank": rank, "order": order}
        if key not in found or (rank, order) < (found[key]["rank"], found[key]["order"]):
            found[key] = candidate

    entities = list(db.scalars(select(Entity).where(Entity.campaign_id == campaign_id)))
    by_name = {}
    for e in entities:
        if e.status != Status.PUBLISHED and not include_drafts:
            continue
        by_name[_norm(e.name)] = e
        kind, order = KIND_LABELS.get(e.kind, ""), MENTION_ORDER.get(e.kind, 9)
        r = hit(e.name)
        if r is not None:
            offer(e.name, kind, r, order=order)
        for a in e.aliases:
            r = hit(a.alias)
            if r is not None:
                offer(e.name, kind, r + 2, via=a.alias, order=order)
    for g in db.scalars(select(GlossaryTerm).where(GlossaryTerm.campaign_id == campaign_id)):
        target = by_name.get(_norm(g.term))
        kind = KIND_LABELS.get(target.kind, "") if target else "Glossary"
        order = MENTION_ORDER.get(target.kind, 9) if target else 9
        r = hit(g.term)
        if r is not None:
            offer(target.name if target else g.term, kind, r + 1, order=order)
        for m in g.misheard_as or []:
            r = hit(m)
            if r is not None:
                offer(target.name if target else g.term, kind, r + 4, via=m, order=order)
                if target is None:  # "Fennwood" -> "Fenwood" -> also "Aldric Fenwood"
                    for e in by_name.values():
                        if _norm(g.term) in _norm(e.name).split():
                            offer(e.name, KIND_LABELS.get(e.kind, ""), r + 5, via=m, order=MENTION_ORDER.get(e.kind, 9))
    ranked = sorted(found.values(), key=lambda d: (d["rank"], d["order"], len(d["name"]), d["name"].casefold()))[:limit]
    return [{k: d[k] for k in ("name", "kind", "via")} for d in ranked]


# --- The DM's own tools (docs/plans/2026-10-22-content-workflows.md, step 1) --------------------------------


def find_by_name(db: Session, campaign_id: int, name: str) -> Entity | None:
    """An entry already called this (by name or another name), so the DM isn't offered a duplicate."""
    key = _norm(name)
    for e in db.scalars(select(Entity).where(Entity.campaign_id == campaign_id)):
        if _norm(e.name) == key or any(_norm(a.alias) == key for a in e.aliases):
            return e
    return None


def create(db: Session, campaign_id: int, kind: str, name: str, summary: str = "", published: bool = True) -> Entity:
    """A new person, place, faction, item, quest or creature written by the DM (no transcript, no Claude)."""
    name = " ".join((name or "").split())
    if not name:
        raise EntityError("Enter a name.")
    if len(name) > 200:
        raise EntityError("That name is too long.")
    try:
        k = EntityKind(kind)
    except ValueError as e:
        raise EntityError("Pick what kind of entry it is.") from e
    if k == EntityKind.PC:
        raise EntityError("Player characters come from Manage › Characters.")
    if (same := find_by_name(db, campaign_id, name)) is not None:
        raise EntityError(f"{same.name} is already in the campaign record.")
    entity = Entity(campaign_id=campaign_id, kind=k, name=name, summary=(summary or "").replace("\r\n", "\n").strip()[:4000],
                    status=Status.PUBLISHED if published else Status.DRAFT, quest_open=True if k == EntityKind.QUEST else None)
    db.add(entity)
    db.flush()
    return entity


def set_details(entity: Entity, kind: str, quest_open: str, published: bool) -> None:
    """Kind, a quest's open or done, and whether the table sees it."""
    try:
        k = EntityKind(kind)
    except ValueError as e:
        raise EntityError("Pick what kind of entry it is.") from e
    if (k == EntityKind.PC) != (entity.kind == EntityKind.PC):
        raise EntityError("Player characters stay player characters; link them on Manage › Characters.")
    entity.kind = k
    entity.quest_open = (quest_open != "done") if k == EntityKind.QUEST else None
    entity.status = Status.PUBLISHED if published else Status.DRAFT


def _not_a_character(db: Session, entity: Entity, verb: str) -> None:
    from app.models import Character

    if entity.kind == EntityKind.PC or db.scalar(select(Character.id).where(Character.entity_id == entity.id)):
        raise EntityError(f"{entity.name} is a player character, so it can't be {verb} here.")


def delete(db: Session, entity: Entity) -> str:
    """Remove an entry. Its facts and relationships go one by one, so Manage › History can bring them back."""
    _not_a_character(db, entity, "deleted")
    from app.models import EntityRelation

    for fact in db.scalars(select(Fact).where(Fact.entity_id == entity.id)):
        db.delete(fact)
    for rel in db.scalars(select(EntityRelation).where((EntityRelation.from_entity_id == entity.id) | (EntityRelation.to_entity_id == entity.id))):
        db.delete(rel)
    name = entity.name
    db.delete(entity)
    db.flush()
    return name


def _alias_note(entity: Entity, alias: str) -> str:
    return next((a.note for a in entity.aliases if a.alias == alias), "") or ""


def merge(db: Session, source: Entity, target: Entity) -> None:
    """Fold a duplicate into the entry that stays: its name and other names become target's other names, and its
    facts, relationships, key moments and picture move over. Target's description stays; source's, if different,
    is kept as a fact so nothing is lost."""
    from app.models import EntityPicture, EntityRelation

    if source.id == target.id:
        raise EntityError("Pick a different entry to merge into.")
    if source.campaign_id != target.campaign_id:
        raise EntityError("Those entries are in different campaigns.")
    _not_a_character(db, source, "merged away")
    have = {_norm(target.name)} | {_norm(a.alias) for a in target.aliases}
    for alias, misspelling in [(source.name, False)] + [(a.alias, a.misspelling) for a in source.aliases]:
        if _norm(alias) not in have:
            target.aliases.append(EntityAlias(alias=alias, misspelling=misspelling, note=f"merged from {source.name}" if alias == source.name else _alias_note(source, alias)))
            have.add(_norm(alias))
    for fact in db.scalars(select(Fact).where(Fact.entity_id == source.id)):
        fact.entity_id = target.id
    if (source.summary or "").strip() and source.summary.strip() != (target.summary or "").strip():
        if not (target.summary or "").strip():
            target.summary = source.summary
        else:
            db.add(Fact(entity_id=target.id, kind="addition", text=f"From the merged entry {source.name}: {source.summary.strip()}",
                        author_name="Merged entry", author_email="", status="merged"))
    for rel in list(db.scalars(select(EntityRelation).where((EntityRelation.from_entity_id == source.id) | (EntityRelation.to_entity_id == source.id)))):
        ends = (target.id if rel.from_entity_id == source.id else rel.from_entity_id, target.id if rel.to_entity_id == source.id else rel.to_entity_id)
        clash = ends[0] == ends[1] or db.scalar(select(EntityRelation.id).where(
            EntityRelation.from_entity_id == ends[0], EntityRelation.type == rel.type, EntityRelation.to_entity_id == ends[1]))
        if clash:
            db.delete(rel)
        else:
            rel.from_entity_id, rel.to_entity_id = ends
    linked = set(db.scalars(select(EventEntity.event_id).where(EventEntity.entity_id == target.id)))
    for link in list(db.scalars(select(EventEntity).where(EventEntity.entity_id == source.id))):
        if link.event_id not in linked:
            db.add(EventEntity(event_id=link.event_id, entity_id=target.id))
        db.delete(link)
    pic = db.scalar(select(EntityPicture).where(EntityPicture.entity_id == source.id))
    if pic is not None and db.scalar(select(EntityPicture.id).where(EntityPicture.entity_id == target.id)) is None:
        pic.entity_id = target.id
    db.flush()
    db.delete(source)
    db.flush()


def add_moment(db: Session, entity: Entity, session_id: int, kind: str, text: str) -> StoryEvent:
    """A key moment written by the DM, in a session's story, mentioning this entry. Shown straight away."""
    from app.models import GameSession

    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        raise EntityError("Write what happened.")
    session = db.get(GameSession, session_id)
    if session is None or session.campaign_id != entity.campaign_id:
        raise EntityError("Pick the session it happened in.")
    try:
        k = EventKind(kind)
    except ValueError as e:
        raise EntityError("Pick what kind of moment it is.") from e
    last = max((e.position for e in session.events), default=0)
    event = StoryEvent(session_id=session.id, position=last + 1, kind=k, text=text[:2000], status=Status.PUBLISHED)
    db.add(event)
    db.flush()
    db.add(EventEntity(event_id=event.id, entity_id=entity.id))
    db.flush()
    return event
