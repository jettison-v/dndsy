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
from sqlalchemy.orm import Session

from app.extraction import MODEL, ExtractionError, _cost, _norm, session_label, timeline
from app.models import (
    Entity,
    EntityKind,
    EventEntity,
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


def add_fact(db: Session, entity: Entity, text: str, user: dict) -> Fact:
    text = text.replace("\r\n", "\n").strip()
    if not text:
        raise EntityError("Write the fact first.")
    if len(text) > 4000:
        raise EntityError("That's a bit long for one fact (4,000 characters max).")
    fact = Fact(
        entity_id=entity.id,
        text=text,
        author_name=(user.get("name") or user.get("email") or "")[:200],
        author_email=(user.get("email") or "")[:320],
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
    fact.status = "pending"


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
- Describe; never advise the players or tell them what to do."""

DESCRIBE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary"],
    "properties": {"summary": {"type": "string"}},
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
        parts.append("\nFacts from the table:\n" + "\n".join(f"- {f.text}" for f in facts))
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
        summary = json.loads(text)["summary"].strip()
        if not summary:
            raise ExtractionError("Claude returned an empty summary.")
        entity.draft_summary = summary
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
    entity.previous_summary = entity.summary or ""
    entity.summary = new
    entity.draft_summary = None


def discard_description(entity: Entity) -> None:
    entity.draft_summary = None


def undo_description(entity: Entity) -> None:
    if entity.previous_summary is None:
        raise EntityError("Nothing to undo.")
    entity.summary, entity.previous_summary = entity.previous_summary, None


# --- @-mentions ---------------------------------------------------------------------


def mention_suggestions(db: Session, campaign_id: int, q: str, include_drafts: bool = False, limit: int = 8) -> list[dict]:
    """Entity names (and glossary spellings) matching what follows an "@".
    Matches the start of the name or of any word in it, aliases, and the
    glossary's misheard_as spellings; returns the canonical name to insert."""
    q = _norm(q)
    if not q:
        return []

    def hit(text: str) -> int | None:
        t = _norm(text)
        if t.startswith(q):
            return 0
        if any(w.startswith(q) for w in t.split()):
            return 1
        return None

    found: dict[str, dict] = {}

    def offer(name: str, kind: str, rank: int, via: str = ""):
        key = _norm(name)
        if key not in found or rank < found[key]["rank"]:
            found[key] = {"name": name, "kind": kind, "via": via, "rank": rank}

    entities = list(db.scalars(select(Entity).where(Entity.campaign_id == campaign_id)))
    by_name = {}
    for e in entities:
        if e.status != Status.PUBLISHED and not include_drafts:
            continue
        by_name[_norm(e.name)] = e
        kind = KIND_LABELS.get(e.kind, "")
        r = hit(e.name)
        if r is not None:
            offer(e.name, kind, r)
        for a in e.aliases:
            r = hit(a.alias)
            if r is not None:
                offer(e.name, kind, r + 2, via=a.alias)
    for g in db.scalars(select(GlossaryTerm).where(GlossaryTerm.campaign_id == campaign_id)):
        target = by_name.get(_norm(g.term))
        kind = KIND_LABELS.get(target.kind, "") if target else "Glossary"
        r = hit(g.term)
        if r is not None:
            offer(target.name if target else g.term, kind, r + 1)
        for m in g.misheard_as or []:
            r = hit(m)
            if r is not None:
                offer(target.name if target else g.term, kind, r + 4, via=m)
                if target is None:  # "Fennwood" -> "Fenwood" -> also "Aldric Fenwood"
                    for e in by_name.values():
                        if _norm(g.term) in _norm(e.name).split():
                            offer(e.name, KIND_LABELS.get(e.kind, ""), r + 5, via=m)
    ranked = sorted(found.values(), key=lambda d: (d["rank"], d["name"].casefold()))[:limit]
    return [{k: d[k] for k in ("name", "kind", "via")} for d in ranked]
