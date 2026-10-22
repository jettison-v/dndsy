"""Session review rules: answering Claude's questions, deciding suggestions
(with undo), editing the recap and key moments, publishing.

Routes live in admin_sessions.py; this module holds the behavior so it can be
tested on its own.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.characters import campaign_characters

from app import relations
from app.models import (
    Correction,
    Entity,
    EntityAlias,
    EntityRelation,
    EntityKind,
    EventKind,
    ExtractionRun,
    GameSession,
    NON_DRAFTING_SOURCES,
    GlossaryTerm,
    Proposal,
    Recap,
    Status,
    StoryEvent,
)


class ReviewError(ValueError):
    pass


# --- Questions ---------------------------------------------------------------


def _question_row(db: Session, session: GameSession, question: str) -> Correction | None:
    return db.scalar(
        select(Correction).where(
            Correction.session_id == session.id,
            Correction.kind.in_(QUESTION_KINDS),
            Correction.before == question,
        )
    )


QUESTION_KINDS = ("answer", "skip", "ask")


def answer_question(
    db: Session, session: GameSession, question: str, answer: str, remember: bool, answered_by: str = ""
) -> None:
    answer = answer.strip()
    if not answer:
        raise ReviewError("Type an answer, or use Skip.")
    row = _question_row(db, session, question) or Correction(
        campaign_id=session.campaign_id, session_id=session.id, before=question
    )
    row.kind, row.after, row.standing_instruction, row.note = "answer", answer, remember, ""
    row.answered_by = answered_by.strip()[:200]
    db.add(row)


def ask_question(db: Session, session: GameSession, question: str, person: str, note: str, asked_by: str) -> None:
    """Defer a question to someone at the table; it waits until they (or a reviewer) answer."""
    person = " ".join(person.split())
    if not person:
        raise ReviewError("Choose who to ask.")
    row = _question_row(db, session, question) or Correction(
        campaign_id=session.campaign_id, session_id=session.id, before=question
    )
    row.kind, row.after, row.standing_instruction = "ask", "", False
    row.asked_of, row.asked_by, row.note, row.answered_by = person[:200], asked_by[:200], note.strip(), ""
    db.add(row)


def ask_options(db: Session, campaign_id: int) -> list[tuple[str, str]]:
    """People a question can be sent to: (name, hint) for the DM and each player."""
    from app.models import Campaign

    campaign = db.get(Campaign, campaign_id)
    options: dict[str, str] = {}
    if campaign and campaign.dm_name:
        options[campaign.dm_name] = "Dungeon Master"
    for ch in campaign_characters(db, campaign_id):
        player = ch.player_name or (ch.owner.name if ch.owner else "")
        if player and player not in options:
            options[player] = f"plays {ch.name}"
    return list(options.items())


def names_for(db: Session, user: dict) -> set[str]:
    """Names a deferred question may use for this signed-in person (casefolded):
    their email, Google name and first name, the player name on characters they
    own, and the campaign's DM name if they're the DM."""
    from app.models import Campaign, CampaignMember, Character, Role, User

    email = (user.get("email") or "").strip().lower()
    full = " ".join((user.get("name") or "").split())
    names = {email, full.casefold()}
    if full:
        names.add(full.split()[0].casefold())
    account = db.scalar(select(User).where(User.email == email)) if email else None
    if account:
        names.add(" ".join(account.name.split()).casefold())
        for ch in db.scalars(select(Character).where(Character.owner_id == account.id)):
            if ch.player_name:
                names.add(" ".join(ch.player_name.split()).casefold())
        for m in db.scalars(select(CampaignMember).where(CampaignMember.user_id == account.id, CampaignMember.role == Role.DM,
                                                         CampaignMember.left_on.is_(None))):
            campaign = db.get(Campaign, m.campaign_id)
            if campaign.dm_name:
                names.add(" ".join(campaign.dm_name.split()).casefold())
    names.discard("")
    return names


def questions_for(db: Session, user: dict) -> list[Correction]:
    """Questions waiting on this person, oldest first."""
    names = names_for(db, user)
    asks = db.scalars(select(Correction).where(Correction.kind == "ask").order_by(Correction.id))
    return [c for c in asks if " ".join(c.asked_of.split()).casefold() in names]


def answer_as_askee(db: Session, correction: Correction, user: dict, answer: str, remember: bool) -> GameSession:
    """The asked person answers from Previously on…; it counts like a reviewer's answer."""
    if correction.kind != "ask" or " ".join(correction.asked_of.split()).casefold() not in names_for(db, user):
        raise ReviewError("That question isn't waiting on you any more.")
    session = db.get(GameSession, correction.session_id)
    answer_question(db, session, correction.before, answer, remember, answered_by=user.get("name") or user.get("email", ""))
    return session


def skip_question(db: Session, session: GameSession, question: str) -> None:
    row = _question_row(db, session, question) or Correction(
        campaign_id=session.campaign_id, session_id=session.id, before=question
    )
    row.kind, row.after, row.standing_instruction = "skip", "", False
    db.add(row)


def reopen_question(db: Session, session: GameSession, question: str) -> None:
    """Remove an answer or a skip so the question is open again."""
    row = _question_row(db, session, question)
    if row:
        db.delete(row)


def _last_draft_run(db: Session, session: GameSession, status: str | None = "done") -> ExtractionRun | None:
    """Most recent drafting run (conversation checks and entity runs don't count)."""
    q = select(ExtractionRun).where(ExtractionRun.session_id == session.id, ExtractionRun.source.notin_(NON_DRAFTING_SOURCES))
    if status:
        q = q.where(ExtractionRun.status == status)
    return db.scalar(q.order_by(ExtractionRun.id.desc()))


def latest_questions(db: Session, session: GameSession) -> list[str]:
    run = _last_draft_run(db, session)
    return list(run.to_check) if run else []


def unused_answer_count(db: Session, session: GameSession) -> int:
    """Answers saved after the latest successful draft (so a redraft would use them)."""
    run = _last_draft_run(db, session)
    if run is None:
        return 0
    return (
        db.scalar(
            select(func.count())
            .select_from(Correction)
            .where(
                Correction.session_id == session.id,
                Correction.kind == "answer",
                Correction.updated_at >= run.updated_at,
            )
        )
        or 0
    )


# --- Suggestions (proposals) -------------------------------------------------


def accept_proposal(db: Session, p: Proposal, summary: str | None = None, by: str = "") -> None:
    """Apply a suggestion and remember what it replaced, so Undo can restore it. `summary` is the reviewer's edit
    of the proposed description (which makes it theirs: `by`)."""
    if p.status != "pending":
        raise ReviewError("That suggestion was already decided.")
    from app.history import mark

    mark("recap")  # version history: these changes came from a recap's suggestions
    session = db.get(GameSession, p.session_id)
    data = dict(p.payload)
    if p.kind == "glossary":
        term = db.scalar(
            select(GlossaryTerm).where(GlossaryTerm.campaign_id == session.campaign_id, GlossaryTerm.term == data["term"])
        )
        if term is None:
            term = GlossaryTerm(
                campaign_id=session.campaign_id,
                term=data["term"],
                description=data.get("description", ""),
                misheard_as=data.get("misheard_as", []),
            )
            db.add(term)
            db.flush()
            data["undo"] = {"created_term_id": term.id}
        else:
            data["undo"] = {}
    elif p.kind == "relationship":
        ends = []
        for side in ("from", "to"):
            entity = _resolve_entity(db, session.campaign_id, data.get(f"{side}_id"), data[f"{side}_name"])
            if entity is None:
                raise ReviewError(f"Accept {data[f'{side}_name']} first; askdnd doesn't know them yet.")
            ends.append(entity)
        try:
            rel, created = relations.add(db, ends[0], data["type"], ends[1], data.get("note", ""))
        except relations.RelationError as e:
            raise ReviewError(str(e)) from e
        data["from_id"], data["to_id"] = ends[0].id, ends[1].id
        data["undo"] = {"created_relation_id": rel.id} if created else {}
    else:
        edited = summary is not None and bool(summary.strip()) and summary.strip() != data["summary"].strip()
        if summary is not None and summary.strip():
            data["summary"] = summary.strip()
        entity = db.get(Entity, data["entity_id"]) if data.get("entity_id") else None
        # Protect what's there now: the draft was a marked-up edit of the description at drafting time. If someone has
        # changed it since, accepting would undo their change, so combine the two by hand.
        if entity is not None and not edited and (entity.summary or "").strip() != (data.get("old_summary") or "").strip():
            raise ReviewError(f"{entity.name}'s description changed since this draft. Use Edit to combine the two.")
        # A "new" entry that exists by now (another session's suggestion was accepted first, or the DM added it):
        # add to it instead of making a duplicate, and keep its description; this draft's version becomes a fact.
        late = entity is None and _resolve_entity(db, session.campaign_id, None, data["name"])
        if late:
            entity = late
        if entity is None:
            entity = Entity(campaign_id=session.campaign_id, kind=EntityKind(data["kind"]), name=data["name"])
            db.add(entity)
            db.flush()
            undo = {"created_entity_id": entity.id}
        else:
            undo = {
                "entity_id": entity.id,
                "summary": entity.summary,
                "quest_open": entity.quest_open,
                "status": entity.status.value,
                "summary_by": entity.summary_by,
            }
        if late and (entity.summary or "").strip() and data["summary"].strip() != entity.summary.strip():
            from app.models import Fact

            fact = Fact(entity_id=entity.id, kind="addition", text=data["summary"].strip(), status="merged",
                        author_name=f"{session_label_short(session)} draft", author_email="")
            db.add(fact)
            db.flush()
            undo["created_fact_id"] = fact.id
        else:
            entity.summary = data["summary"]
            entity.summary_by = by[:200] if edited and by else "claude"
        if data.get("quest_open") is not None:
            entity.quest_open = data["quest_open"]
        have = {a.alias.casefold() for a in entity.aliases}
        added = []
        for alias in data.get("new_aliases", []):
            if alias.casefold() not in have and alias.casefold() != entity.name.casefold():
                entity.aliases.append(EntityAlias(alias=alias))
                have.add(alias.casefold())
                added.append(alias)
        entity.status = Status.PUBLISHED
        undo["added_aliases"] = added
        data["undo"] = undo
        data["applied_entity_id"] = entity.id
    p.payload = data
    p.status = "accepted"


def session_label_short(session: GameSession) -> str:
    return f"Session {session.number}" if session.number is not None else "A session's"


def _resolve_entity(db: Session, campaign_id: int, entity_id: int | None, name: str) -> Entity | None:
    """The entity a relationship suggestion names: by id, else by name or alias
    (it may have been created since, by accepting its own suggestion)."""
    from app.extraction import _entity_index, _norm

    entity = db.get(Entity, entity_id) if entity_id else None
    return entity or _entity_index(db, campaign_id).get(_norm(name))


def reject_proposal(db: Session, p: Proposal) -> None:
    if p.status != "pending":
        raise ReviewError("That suggestion was already decided.")
    p.status = "rejected"


def undo_proposal(db: Session, p: Proposal) -> None:
    """Put things back as they were and make the suggestion pending again."""
    if p.status == "rejected":
        p.status = "pending"
        return
    if p.status != "accepted":
        return
    data = dict(p.payload)
    undo = data.pop("undo", {}) or {}
    if p.kind == "relationship":
        rel = db.get(EntityRelation, undo["created_relation_id"]) if undo.get("created_relation_id") else None
        if rel:
            db.delete(rel)
    elif p.kind == "glossary":
        term = db.get(GlossaryTerm, undo["created_term_id"]) if undo.get("created_term_id") else None
        if term:
            db.delete(term)
    elif undo.get("created_entity_id"):
        entity = db.get(Entity, undo["created_entity_id"])
        if entity:
            db.delete(entity)
    elif undo.get("entity_id"):
        entity = db.get(Entity, undo["entity_id"])
        if undo.get("created_fact_id"):
            from app.models import Fact

            fact = db.get(Fact, undo["created_fact_id"])
            if fact:
                db.delete(fact)
        if entity:
            entity.summary = undo.get("summary", entity.summary)
            entity.summary_by = undo.get("summary_by", "")
            entity.quest_open = undo.get("quest_open")
            entity.status = Status(undo.get("status", entity.status.value))
            added = {a.casefold() for a in undo.get("added_aliases", [])}
            for alias in list(entity.aliases):
                if alias.alias.casefold() in added:
                    entity.aliases.remove(alias)
    data.pop("applied_entity_id", None)
    p.payload = data
    p.status = "pending"


def edit_accepted_proposal(db: Session, p: Proposal, summary: str, by: str = "") -> None:
    """Change the summary of an accepted suggestion (and the entity it updated)."""
    summary = summary.strip()
    if p.status != "accepted" or p.kind != "entity" or not summary:
        raise ReviewError("Only accepted people/place suggestions can be edited.")
    entity = db.get(Entity, p.payload.get("applied_entity_id"))
    if entity:
        entity.summary = summary
        entity.summary_by = by[:200]
    p.payload = {**p.payload, "summary": summary}


# --- Recap, key moments, publishing -------------------------------------------


def latest_recap(session: GameSession) -> Recap | None:
    return session.recaps[-1] if session.recaps else None


def published_recap(session: GameSession) -> Recap | None:
    return next((r for r in reversed(session.recaps) if r.status == Status.PUBLISHED), None)


def review_status(session: GameSession, drafting: bool) -> str:
    if drafting:
        return "drafting"
    latest, published = latest_recap(session), published_recap(session)
    if published is None:
        return "draft" if latest else "no draft"
    return "published" if latest.id == published.id else "edited"


def save_recap(db: Session, session: GameSession, body: str, note: str = "", standing: bool = False, by: str = "") -> Recap:
    body = body.replace("\r\n", "\n").strip()
    if not body:
        raise ReviewError("The recap can't be empty.")
    latest = latest_recap(session)
    if latest is None or latest.body.strip() != body:
        version = (db.scalar(select(func.max(Recap.version)).where(Recap.session_id == session.id)) or 0) + 1
        latest = Recap(session_id=session.id, version=version, body=body, author="brett", author_name=by[:200], status=Status.DRAFT)
        db.add(latest)
        db.flush()
        db.refresh(session)
    ai_draft = next((r for r in reversed(session.recaps) if r.author == "ai"), None)
    if ai_draft and (note.strip() or ai_draft.body.strip() != body):
        existing = db.scalar(
            select(Correction).where(
                Correction.session_id == session.id, Correction.kind == "edit", Correction.before == ai_draft.body
            )
        )
        correction = existing or Correction(campaign_id=session.campaign_id, session_id=session.id, kind="edit", before=ai_draft.body)
        correction.after = body
        if note.strip():  # a later save without a note keeps the earlier note and choice
            correction.note = note.strip()
            correction.standing_instruction = standing
        db.add(correction)
    return latest


def person_version(session: GameSession) -> Recap | None:
    """When Claude redrafted over a recap someone wrote: their latest version, to show Claude's draft as a marked-up
    edit of it and offer to keep theirs (content workflows step 3)."""
    latest = latest_recap(session)
    if latest is None or latest.author != "ai":
        return None
    return next((r for r in reversed(session.recaps) if r.author != "ai" and r.version < latest.version), None)


def keep_person_version(db: Session, session: GameSession) -> Recap:
    """Set Claude's redraft aside and make the person's version the latest again (the redraft stays in the versions)."""
    mine = person_version(session)
    if mine is None:
        raise ReviewError("There's no earlier version of yours to go back to.")
    return save_recap(db, session, mine.body, by=mine.author_name)


def publish(db: Session, session: GameSession) -> None:
    latest = latest_recap(session)
    if latest is None:
        raise ReviewError("There's no recap to publish yet.")
    for r in session.recaps:
        if r.status == Status.PUBLISHED and r.id != latest.id:
            r.status = Status.DRAFT
    latest.status = Status.PUBLISHED
    for ev in session.events:
        ev.status = Status.PUBLISHED


def save_event(db: Session, session: GameSession, event_id: int | None, kind: str, text: str) -> None:
    text = text.strip()
    if not text:
        raise ReviewError("A key moment needs some text.")
    if kind not in {k.value for k in EventKind}:
        raise ReviewError("Unknown type.")
    if event_id is None:
        position = max((e.position for e in session.events), default=0) + 1
        db.add(StoryEvent(session_id=session.id, position=position, kind=EventKind(kind), text=text))
        return
    ev = db.get(StoryEvent, event_id)
    if ev is None or ev.session_id != session.id:
        raise ReviewError("That key moment no longer exists.")
    ev.kind, ev.text = EventKind(kind), text


def delete_event(db: Session, session: GameSession, event_id: int) -> None:
    ev = db.get(StoryEvent, event_id)
    if ev is not None and ev.session_id == session.id:
        db.delete(ev)  # one at a time, so version history keeps it


# --- Everything the review page needs ------------------------------------------


def review_context(db: Session, session: GameSession, drafting: bool) -> dict:
    questions = latest_questions(db, session)
    rows = {
        c.before: c
        for c in db.scalars(
            select(Correction).where(Correction.session_id == session.id, Correction.kind.in_(QUESTION_KINDS))
        )
    }
    open_questions = [q for q in questions if q not in rows]
    handled = [rows[q] for q in questions if q in rows] + [c for q, c in rows.items() if q not in questions]
    waiting: dict[str, list[Correction]] = {}
    for c in handled:
        if c.kind == "ask":
            waiting.setdefault(c.asked_of, []).append(c)
    done_questions = [c for c in handled if c.kind != "ask"]
    proposals = list(db.scalars(select(Proposal).where(Proposal.session_id == session.id).order_by(Proposal.id)))
    open_proposals = [p for p in proposals if p.status == "pending"]
    done_proposals = sorted((p for p in proposals if p.status != "pending"), key=lambda p: p.updated_at, reverse=True)
    last_run = _last_draft_run(db, session, status=None)
    last_done = _last_draft_run(db, session)
    return {
        "status": review_status(session, drafting),
        "latest": latest_recap(session),
        "published": published_recap(session),
        "person_version": person_version(session),
        "current": {e.id: e for e in db.scalars(select(Entity).where(Entity.id.in_(
            {p.payload.get("entity_id") for p in open_proposals if p.kind == "entity" and p.payload.get("entity_id")})))},
        "events": list(session.events),
        "event_kinds": [k.value for k in EventKind],
        "open_questions": open_questions,
        "done_questions": done_questions,
        "waiting": sorted(waiting.items(), key=lambda kv: kv[0].casefold()),
        "waiting_count": sum(len(v) for v in waiting.values()),
        "ask_options": ask_options(db, session.campaign_id),
        "unused_answers": unused_answer_count(db, session),
        "open_proposals": open_proposals,
        "done_proposals": done_proposals,
        "accepted_count": sum(1 for p in done_proposals if p.status == "accepted"),
        "rejected_count": sum(1 for p in done_proposals if p.status == "rejected"),
        "last_run": last_run,
        "last_done": last_done,
        "drafting": drafting,
    }
