"""Draft a session's story with Claude: recap, events, entity and glossary
suggestions. Everything lands as a draft (or pending proposal) for Brett.

Sources: a session's section of the synced campaign notes, or a filtered
transcript. The transcript text is used only for this call and never stored.
"""

import base64
import json
import re
from datetime import date
from collections.abc import Callable
from dataclasses import dataclass, field

import anthropic
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app import spending
from app.relations import TYPES as REL_TYPES
from app.relations import find as find_relation
from app.models import (
    Campaign,
    Character,
    Correction,
    Entity,
    EntityKind,
    EventKind,
    ExtractionRun,
    Fact,
    GameSession,
    GlossaryTerm,
    NoteImage,
    NoteSnapshot,
    NoteSource,
    Proposal,
    Recap,
    Status,
    StoryEvent,
)

MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 32000
# Claude Opus 5.5 prices per million tokens (input, output, cache write, cache read).
PRICES = {"input": 4.00, "output": 20.00, "cache_write": 5.00, "cache_read": 0.20}
MAX_IMAGES = 12

SYSTEM_PROMPT = """\
You keep the campaign record for one Dungeons & Dragons (2024 rules) table: \
four players and a Dungeon Master who play over Zoom. From one session's \
source material you draft what happened, for the players to read before the \
next session. A human (Brett, one of the players) reviews everything before \
the table sees it.

Write for the whole table:
- Neutral, third person, past tense. Name characters ("Cole learned...") \
instead of "I", "my" or "we" — the notes are written from Cole's point of view.
- Use character names, not player names, for in-game actions.
- Spell names exactly as in the glossary and known names list, even when the \
source misspells them or a transcript mishears them.
- Keep facts and speculation apart. Notes mark speculation with "←" or words \
like "I think", "maybe", "could be". Those are theories, never facts.
- Don't invent anything. If the source is unclear, say so in to_check rather \
than guessing.
- Describe what happened and what the party learned. Don't give advice or \
tell players what they should do next; listing open threads is fine.

The recap: 150-400 words of Markdown, a few short paragraphs, most important \
developments first, ending with where the party is and what is unresolved. \
No headings.

Events: the session's key moments in order, each one or two sentences. Kinds: \
event (something happened), reveal (lore or information learned), decision \
(the party chose something), loot (items or rewards gained, lost or used up), \
theory (speculation from the notes or the table). List the names of the \
people, places, factions, items and quests each event involves.

Entities: only ones this session adds information about. Use the existing \
name when it is already known (match aliases and misspellings); give a full \
updated summary of 1-3 sentences that merges what was known with what's new. \
For new ones, pick the kind and write a summary. Add aliases only for real \
alternative names or spellings. A summary marked "written by" a person is their \
words: keep its wording and order, and change only what this session adds or \
corrects (add a sentence, fix a detail); never rephrase what's still true, and \
it may stay longer than 3 sentences.

Relationships: lasting links between people, factions and places that this \
session reveals or changes and that aren't in the known relationships yet. \
Types: parent_of, married_to, sibling_of, member_of (a person in a faction), \
serves (a person serving another person or a faction), ally_of, enemy_of. \
Use exact known names (or the names of new entities you list). Only state \
what the source says, not guesses.

Glossary: proper nouns that a transcription might mangle and that aren't \
already in the glossary.

to_check: short questions for Brett about anything ambiguous, contradictory, \
or possibly wrong (including apparent rules mistakes in the notes). Brett can \
answer them, and his answers come back to you as clarifications. Don't ask \
again about something a clarification already settles.

Time: the known world describes the campaign as it stands NOW, which may be \
well after the session you're drafting. Describe only what happened in this \
session and what the party knew by its end; never mention later events (for \
example a character's later death) in the recap or events. Don't flag the \
known world being ahead of this session — that's expected."""

_ENTITY_KINDS = [k.value for k in EntityKind]
_EVENT_KINDS = [k.value for k in EventKind]
_REL_TYPES = list(REL_TYPES)

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "recap", "events", "entities", "relationships", "glossary", "to_check"],
    "properties": {
        "title": {"type": "string", "description": "Short session title, 2-6 words"},
        "recap": {"type": "string"},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "text", "entities"],
                "properties": {
                    "kind": {"type": "string", "enum": _EVENT_KINDS},
                    "text": {"type": "string"},
                    "entities": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "kind", "summary", "aliases", "quest_status"],
                "properties": {
                    "name": {"type": "string"},
                    "kind": {"type": "string", "enum": _ENTITY_KINDS},
                    "summary": {"type": "string"},
                    "aliases": {"type": "array", "items": {"type": "string"}},
                    "quest_status": {"type": "string", "enum": ["open", "done", "not_a_quest"]},
                },
            },
        },
        "relationships": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["from", "type", "to", "note"],
                "properties": {
                    "from": {"type": "string"},
                    "type": {"type": "string", "enum": _REL_TYPES},
                    "to": {"type": "string"},
                    "note": {"type": "string", "description": "Optional short detail, e.g. 'adopted'; empty if none"},
                },
            },
        },
        "glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["term", "description", "misheard_as"],
                "properties": {
                    "term": {"type": "string"},
                    "description": {"type": "string"},
                    "misheard_as": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "to_check": {"type": "array", "items": {"type": "string"}},
    },
}


class ExtractionError(RuntimeError):
    pass


# --- Notes: split the synced campaign notes into per-session sections ---

HEADING = re.compile(r"^(#+)\s+(.*)$")
SESSION_HEADING = re.compile(r"^session\s+(\d+)\b", re.IGNORECASE)


def split_notes(text: str) -> tuple[str, dict[int, str]]:
    """(background, {session number: section}). A session section runs until
    the next session heading or a heading higher up the outline."""
    background: list[str] = []
    sections: dict[int, list[str]] = {}
    current: int | None = None
    level = 0
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            depth, title = len(m.group(1)), m.group(2).strip()
            s = SESSION_HEADING.match(title)
            if s:
                current, level = int(s.group(1)), depth
                sections.setdefault(current, []).append(line)
                continue
            if current is not None and depth < level:
                current = None
        (sections[current] if current is not None else background).append(line)
    return "\n".join(background).strip(), {n: "\n".join(lines).strip() for n, lines in sections.items()}


IMAGE_REF = re.compile(r"\[image: ([^\]]+)\]")


def latest_campaign_notes(db: Session, campaign_id: int) -> NoteSnapshot | None:
    """Most recent snapshot of the campaign (not character) notes."""
    return db.scalar(
        select(NoteSnapshot)
        .join(NoteSource)
        .where(NoteSource.campaign_id == campaign_id, NoteSource.character_id.is_(None))
        .order_by(NoteSnapshot.id.desc())
    )


# --- Building the request ---


@dataclass
class Source:
    kind: str  # "notes" or "transcript"
    text: str
    images: list[NoteImage] = field(default_factory=list)


def _image_block(img: NoteImage, label: str) -> list[dict]:
    return [
        {"type": "text", "text": f"Image {label}:"},
        {
            "type": "image",
            "source": {"type": "base64", "media_type": img.content_type, "data": base64.b64encode(img.data).decode()},
        },
    ]


def _alias_text(e: Entity) -> str:
    """" Also: X. Often misspelled: Y." (misspellings: use the name, never these)."""
    names = [a.alias for a in e.aliases if not a.misspelling]
    wrong = [a.alias for a in e.aliases if a.misspelling]
    return (f" Also: {', '.join(names)}." if names else "") + (f" Often misspelled: {', '.join(wrong)}." if wrong else "")


def _known_world(db: Session, campaign: Campaign) -> str:
    lines = [f"Campaign: {campaign.name}"]
    if campaign.dm_name:
        lines.append(f"Dungeon Master: {campaign.dm_name}")
    lines.append("\nPlayer characters (character — player):")
    for ch in db.scalars(select(Character).join(Entity).where(Entity.campaign_id == campaign.id).order_by(Entity.name)):
        player = ch.player_name or (ch.owner.name if ch.owner else "unknown")
        lines.append(f"- {ch.entity.name} — {player}{_alias_text(ch.entity)}")
    lines.append("\nKnown people, places and things (name [kind]: summary; aliases):")
    for e in db.scalars(
        select(Entity).where(Entity.campaign_id == campaign.id, Entity.kind != EntityKind.PC).order_by(Entity.kind, Entity.name)
    ):
        quest = "" if e.quest_open is None else (" (open)" if e.quest_open else " (done)")
        who = f" (written by {e.written_by_person}: keep their wording)" if e.written_by_person else ""
        lines.append(f"- {e.name} [{e.kind.value}]{quest}{who}: {e.summary}{_alias_text(e)}")
    facts: dict[int, list[str]] = {}
    for f in db.scalars(
        select(Fact).join(Entity).where(Entity.campaign_id == campaign.id, Fact.status == "merged").order_by(Fact.id)
    ):
        facts.setdefault(f.entity_id, []).append(f.labeled_text)
    if facts:
        names = {e.id: e.name for e in db.scalars(select(Entity).where(Entity.id.in_(facts)))}
        lines.append("\nFacts added by people at the table (true; not yet in the summaries above):")
        for eid, texts in sorted(facts.items(), key=lambda kv: names[kv[0]].casefold()):
            lines.extend(f"- {names[eid]}: {t}" for t in texts)
    from app.relations import describe

    rels = describe(db, campaign.id)
    if rels:
        lines.append("\nKnown relationships:")
        lines.extend(f"- {r}" for r in rels)
    lines.append("\nGlossary (correct spelling: description; often misheard as):")
    for g in db.scalars(select(GlossaryTerm).where(GlossaryTerm.campaign_id == campaign.id).order_by(GlossaryTerm.term)):
        heard = f"; misheard as {', '.join(g.misheard_as)}" if g.misheard_as else ""
        lines.append(f"- {g.term}: {g.description}{heard}")
    rules = list(
        db.scalars(
            select(Correction).where(Correction.campaign_id == campaign.id, Correction.standing_instruction.is_(True))
        )
    )
    if rules:
        lines.append("\nStanding instructions and facts from Brett's past reviews:")
        for c in rules:
            if c.kind == "answer":
                lines.append(f"- Q: {c.before} A: {c.after}")
            elif c.note:
                lines.append(f"- {c.note}")
    return "\n".join(lines)


def timeline(db: Session, campaign_id: int) -> list[GameSession]:
    """Sessions in story order. Dated sessions sort by date; an undated session
    (e.g. early notes without dates) takes the date of the next dated session
    with a higher number, and ties break by number."""
    sessions = list(db.scalars(select(GameSession).where(GameSession.campaign_id == campaign_id)))
    dated_numbered = sorted((s for s in sessions if s.played_on and s.number is not None), key=lambda s: s.number)

    def effective(s: GameSession):
        if s.played_on:
            return s.played_on
        if s.number is not None:
            later = next((d for d in dated_numbered if d.number > s.number), None)
            if later:
                return later.played_on
        return date.max

    return sorted(sessions, key=lambda s: (effective(s), s.number if s.number is not None else 10**6, s.id))


def _story_so_far(db: Session, session: GameSession) -> str:
    """Latest recap of each earlier session (published if any, else draft)."""
    order = timeline(db, session.campaign_id)
    earlier = order[: order.index(session)]
    parts = []
    for s in earlier:
        recap = _best_recap(s)
        if recap:
            parts.append(f"### {session_label(s)}\n{recap.body}")
    return "\n\n".join(parts) or "(No earlier recaps yet.)"


def _story_after(db: Session, session: GameSession, count: int = 2) -> str:
    """Recaps of the next few sessions, for checking a gap from both sides."""
    order = timeline(db, session.campaign_id)
    parts = []
    for s in order[order.index(session) + 1 :]:
        recap = _best_recap(s)
        if recap:
            parts.append(f"### {session_label(s)}\n{recap.body}")
        if len(parts) == count:
            break
    return "\n\n".join(parts) or "(No later recaps yet.)"


def _best_recap(s: GameSession) -> Recap | None:
    published = [r for r in s.recaps if r.status == Status.PUBLISHED]
    if published:
        return published[-1]
    return s.recaps[-1] if s.recaps else None


def session_label(s: GameSession) -> str:
    bits = []
    if s.number is not None:
        bits.append(f"Session {s.number}")
    if s.played_on:
        bits.append(s.played_on.strftime("%b %-d, %Y"))
    return " — ".join(bits) or f"Session #{s.id}"


def build_messages(db: Session, session: GameSession, source: Source, background: str = "", background_images=()) -> list[dict]:
    campaign = db.get(Campaign, session.campaign_id)
    stable: list[dict] = [{"type": "text", "text": "<known_world>\n" + _known_world(db, campaign) + "\n</known_world>"}]
    if background:
        stable.append({"type": "text", "text": "<background_notes>\n" + background + "\n</background_notes>"})
    for img in list(background_images)[:MAX_IMAGES]:
        stable += _image_block(img, f"from background notes ({img.name})")
    stable[-1]["cache_control"] = {"type": "ephemeral"}  # reused across sessions in a backfill

    if source.kind == "notes":
        intro = (
            "Below are Brett's notes for this session, written from Cole's point of view. "
            "Images referenced as [image: name] follow the notes."
        )
    elif source.kind == "account":
        intro = (
            "Below is a written account of this session by someone at the table (it has no notes "
            "or recording), followed by a clarifying conversation with you. Later messages override "
            "earlier ones; draft from the final version of events."
        )
    else:
        intro = (
            "Below is the filtered transcript of this session (table talk already removed). "
            "Speaker labels are unreliable: the DM's narration is often labeled as a player, "
            "and fantasy names are often misheard. The DM's narration carries the story; "
            "use player lines for decisions and plans."
        )
    volatile: list[dict] = [
        {"type": "text", "text": "<story_so_far>\n" + _story_so_far(db, session) + "\n</story_so_far>"},
        {"type": "text", "text": f"<session>{session_label(session)}</session>\n{intro}\n<source>\n{source.text}\n</source>"},
    ]
    for img in source.images[:MAX_IMAGES]:
        volatile += _image_block(img, img.name)
    answers = list(
        db.scalars(
            select(Correction).where(Correction.session_id == session.id, Correction.kind == "answer").order_by(Correction.id)
        )
    )
    if answers:
        qa = "\n".join(f"- Q: {c.before}\n  A: {c.after}" for c in answers)
        volatile.append({"type": "text", "text": f"<clarifications_from_brett>\n{qa}\n</clarifications_from_brett>"})
    latest = session.recaps[-1] if session.recaps else None
    if latest is not None and latest.author != "ai":  # protect their words (content workflows step 3)
        who = latest.author_name or "someone at the table"
        volatile.append({"type": "text", "text": (
            f"<current_recap written_by=\"{who}\">\n{latest.body}\n</current_recap>\n"
            f"{who} wrote or edited the current recap. Your recap must keep their wording, order and paragraphs: "
            "change only what the source or the clarifications show is wrong or missing. Don't rephrase anything "
            "that's still true.")})
    volatile.append({"type": "text", "text": "Draft this session's record."})
    return [{"role": "user", "content": stable + volatile}]


def _cost(usage) -> float:
    def g(name):
        return getattr(usage, name, 0) or 0

    return round(
        (
            g("input_tokens") * PRICES["input"]
            + g("output_tokens") * PRICES["output"]
            + g("cache_creation_input_tokens") * PRICES["cache_write"]
            + g("cache_read_input_tokens") * PRICES["cache_read"]
        )
        / 1_000_000,
        4,
    )


def call_claude(client: anthropic.Anthropic, messages: list[dict]) -> tuple[dict, object]:
    with client.beta.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
        output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        details = getattr(response, "stop_details", None)
        raise ExtractionError(f"Claude declined this request ({getattr(details, 'category', None) or 'no category'}).")
    if response.stop_reason == "max_tokens":
        raise ExtractionError("The response was cut off (too long). Try a shorter source.")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise ExtractionError("Claude returned no text.")
    return json.loads(text), response


# --- Storing the result ---


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()


def _entity_index(db: Session, campaign_id: int) -> dict[str, Entity]:
    """Names and aliases -> entity. A lone first name ("Lillippi") also matches
    when exactly one multi-word name starts with it."""
    index: dict[str, Entity] = {}
    first_words: dict[str, set[int]] = {}
    entities = list(db.scalars(select(Entity).where(Entity.campaign_id == campaign_id)))
    for e in entities:
        index[_norm(e.name)] = e
        for a in e.aliases:
            index.setdefault(_norm(a.alias), e)
        words = _norm(e.name).removeprefix("the ").split()
        if len(words) > 1:
            first_words.setdefault(words[0], set()).add(e.id)
    by_id = {e.id: e for e in entities}
    for word, ids in first_words.items():
        if len(ids) == 1:
            index.setdefault(word, by_id[next(iter(ids))])
    return index


def store_result(db: Session, session: GameSession, run: ExtractionRun, data: dict) -> None:
    """Save Claude's draft: a new recap version, draft events, pending proposals."""
    if data.get("title") and not session.title:
        session.title = data["title"].strip()
    version = (db.scalar(select(func.max(Recap.version)).where(Recap.session_id == session.id)) or 0) + 1
    db.add(Recap(session_id=session.id, version=version, body=data["recap"].strip(), author="ai", status=Status.DRAFT))

    index = _entity_index(db, session.campaign_id)
    for old_event in db.scalars(select(StoryEvent).where(StoryEvent.session_id == session.id, StoryEvent.status == Status.DRAFT)):
        db.delete(old_event)  # one at a time, so version history keeps the replaced draft moments
    for pos, ev in enumerate(data.get("events", []), start=1):
        event = StoryEvent(session_id=session.id, position=pos, kind=EventKind(ev["kind"]), text=ev["text"].strip())
        linked = {index[_norm(n)].id: index[_norm(n)] for n in ev.get("entities", []) if _norm(n) in index}
        event.entities = list(linked.values())
        db.add(event)

    db.execute(delete(Proposal).where(Proposal.session_id == session.id, Proposal.status == "pending"))
    for item in data.get("entities", []):
        existing = index.get(_norm(item["name"])) or next(
            (index[_norm(a)] for a in item.get("aliases", []) if _norm(a) in index), None
        )
        known_aliases = {_norm(a.alias) for a in existing.aliases} | {_norm(existing.name)} if existing else set()
        new_aliases = [a for a in item.get("aliases", []) if _norm(a) not in known_aliases]
        quest_open = {"open": True, "done": False}.get(item.get("quest_status"))
        if existing and existing.summary.strip() == item["summary"].strip() and not new_aliases and (
            quest_open is None or quest_open == existing.quest_open
        ):
            continue  # nothing new
        db.add(
            Proposal(
                session_id=session.id,
                kind="entity",
                payload={
                    "entity_id": existing.id if existing else None,
                    "name": existing.name if existing else item["name"].strip(),
                    "kind": existing.kind.value if existing else item["kind"],
                    "old_summary": existing.summary if existing else "",
                    "written_by": existing.written_by_person if existing else "",  # shown as a marked-up edit of theirs
                    "summary": item["summary"].strip(),
                    "new_aliases": new_aliases,
                    "quest_open": quest_open,
                },
            )
        )
    seen_rels = set()
    for rel in data.get("relationships", []):
        type_ = rel.get("type")
        if type_ not in REL_TYPES or not rel.get("from", "").strip() or not rel.get("to", "").strip():
            continue
        a, b = index.get(_norm(rel["from"])), index.get(_norm(rel["to"]))
        if a and b and (a.id == b.id or find_relation(db, a.id, type_, b.id)):
            continue  # already known
        key = (_norm(a.name if a else rel["from"]), type_, _norm(b.name if b else rel["to"]))
        if key in seen_rels or (REL_TYPES[type_].symmetric and (key[2], type_, key[0]) in seen_rels):
            continue
        seen_rels.add(key)
        db.add(
            Proposal(
                session_id=session.id,
                kind="relationship",
                payload={
                    "from_id": a.id if a else None,
                    "from_name": a.name if a else rel["from"].strip(),
                    "type": type_,
                    "to_id": b.id if b else None,
                    "to_name": b.name if b else rel["to"].strip(),
                    "note": (rel.get("note") or "").strip()[:300],
                },
            )
        )
    known_terms = {
        _norm(t) for t in db.scalars(select(GlossaryTerm.term).where(GlossaryTerm.campaign_id == session.campaign_id))
    }
    for g in data.get("glossary", []):
        if _norm(g["term"]) not in known_terms:
            db.add(Proposal(session_id=session.id, kind="glossary", payload=g))
    run.to_check = [t for t in data.get("to_check", []) if t.strip()]


def extract_session(
    db: Session,
    session: GameSession,
    source: Source,
    client_factory: Callable[[], anthropic.Anthropic] = anthropic.Anthropic,
    background: str = "",
    background_images=(),
) -> ExtractionRun:
    """Run one extraction and store the drafts. Commits; never raises for API errors
    (they're recorded on the run so the admin page can show them)."""
    run = ExtractionRun(session_id=session.id, source=source.kind, model=MODEL, status="running")
    db.add(run)
    db.commit()
    try:
        spending.check(db)  # the monthly limit set on Manage › Usage
        messages = build_messages(db, session, source, background, background_images)
        data, response = call_claude(client_factory(), messages)
        run.input_tokens = (response.usage.input_tokens or 0) + (response.usage.cache_read_input_tokens or 0) + (
            response.usage.cache_creation_input_tokens or 0
        )
        run.output_tokens = response.usage.output_tokens or 0
        run.cost_usd = _cost(response.usage)
        run.model = getattr(response, "model", MODEL) or MODEL
        store_result(db, session, run, data)
        run.status = "done"
    except (ExtractionError, anthropic.APIError, json.JSONDecodeError, KeyError, ValueError) as e:
        db.rollback()
        run = db.merge(run)
        run.status, run.error = "error", (str(e) or type(e).__name__)[:2000]
    db.commit()
    return run


def notes_source_for(db: Session, session: GameSession) -> tuple[Source, str, list[NoteImage]]:
    """This session's section of the latest campaign notes, plus background."""
    snap = latest_campaign_notes(db, session.campaign_id)
    if snap is None:
        raise ExtractionError("No synced campaign notes yet. Sync them on the Notes page first.")
    background, sections = split_notes(snap.text)
    if session.number is None or session.number not in sections:
        raise ExtractionError(f"The campaign notes have no section for {session_label(session)}.")
    images = {img.name: img for img in snap.images}
    section = sections[session.number]
    section_images = [images[n] for n in IMAGE_REF.findall(section) if n in images]
    background_images = [images[n] for n in IMAGE_REF.findall(background) if n in images]
    return Source("notes", section, section_images), background, background_images
