"""Pages for the whole table: Previously on…, Sessions, Campaign. Characters: app/character_pages.py."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import web
from app import campaign_views, review
from app.auth import can_edit_entries, can_moderate, current_user
from app.db import get_db
from app.extraction import session_label, timeline
from app.linking import Linker, entity_linker
from app.models import (Campaign, Correction, Entity, EntityKind, EventEntity, EventKind, GameSession, GlossaryTerm, Status, StoryEvent,
                        Suggestion)
from app.render import markdown_to_html
from app.suggestions import waiting_count
from app.templating import templates

router = APIRouter()

GROUPS = [
    (EntityKind.QUEST, "Quests"),
    (EntityKind.NPC, "People"),
    (EntityKind.PLACE, "Places"),
    (EntityKind.FACTION, "Factions"),
    (EntityKind.ITEM, "Items"),
    (EntityKind.CREATURE, "Creatures"),
    (EntityKind.OTHER, "Other"),
]


def published_items(db: Session, campaign: Campaign) -> list[dict]:
    """Published sessions in story order, each with its recap HTML and events, plus the
    DM's corrections that came in after that recap was published (no review needed)."""
    items = []
    dm_notes = list(db.scalars(select(Suggestion).where(Suggestion.campaign_id == campaign.id, Suggestion.target_type == "session",
                                                        Suggestion.from_dm.is_(True)).order_by(Suggestion.id)))
    for s in timeline(db, campaign.id):
        recap = next((r for r in reversed(s.recaps) if r.status == Status.PUBLISHED), None)
        if recap:
            events = [e for e in s.events if e.status == Status.PUBLISHED]
            items.append({
                "s": s,
                "label": session_label(s),
                "html": markdown_to_html(recap.body, lambda n: None),
                "events": [e for e in events if e.kind != EventKind.THEORY],
                "theories": [e for e in events if e.kind == EventKind.THEORY],
                "dm_notes": [x for x in dm_notes if x.target_id == s.id and x.created_at >= recap.updated_at],
            })
    return items


def published_story(db: Session) -> dict:
    campaign = web.campaign(db)
    if campaign is None:
        return {"latest": None, "earlier": [], "threads": [], "quests": []}
    items = published_items(db, campaign)
    quests = list(
        db.scalars(
            select(Entity)
            .where(
                Entity.campaign_id == campaign.id,
                Entity.kind == EntityKind.QUEST,
                Entity.quest_open.is_(True),
                Entity.status == Status.PUBLISHED,
            )
            .order_by(Entity.name)
        )
    )
    return {
        "latest": items[-1] if items else None,
        "earlier": list(reversed(items[:-1])),
        "threads": [t for item in items[-3:] for t in item["theories"]],
        "quests": quests,
    }


def questions_card(db: Session, user: dict) -> list[dict]:
    """Claude's questions that a reviewer sent to this person ("Ask…")."""
    items = []
    for c in review.questions_for(db, user):
        s = db.get(GameSession, c.session_id) if c.session_id else None
        if s is not None:
            items.append({"c": c, "label": session_label(s) + (f": {s.title}" if s.title else "")})
    return items


def _linker(db: Session) -> Linker:
    campaign = web.campaign(db)
    return entity_linker(db, campaign.id) if campaign else Linker(None, {})


@router.get("/")
@router.get("/story")
def story(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "story.html",
        {
            **published_story(db),
            "questions": questions_card(db, user),
            "waiting": waiting_count(db) if can_moderate(user) else 0,
            "toast": request.session.pop("toast", None),
            "ln": _linker(db),
        },
    )


@router.post("/questions/{correction_id:int}/answer")
def answer_question(
    request: Request, correction_id: int, answer: str = Form(""), remember: str = Form(""), db: Session = Depends(get_db)
):
    """The person a question was sent to answers it from Previously on…"""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    c = db.get(Correction, correction_id)
    try:
        if c is None:
            raise review.ReviewError("That question isn't waiting on you any more.")
        review.answer_as_askee(db, c, user, answer, bool(remember))
        db.commit()
        request.session["toast"] = "Thanks! Your answer was sent to the reviewers."
    except review.ReviewError as e:
        db.rollback()
        request.session["toast"] = str(e)
    return RedirectResponse("/", status_code=303)


@router.get("/sessions")
def sessions(request: Request, db: Session = Depends(get_db)):
    if not current_user(request):
        return RedirectResponse("/login", status_code=303)
    campaign = web.campaign(db)
    items = list(reversed(published_items(db, campaign))) if campaign else []
    return templates.TemplateResponse(request, "sessions.html", {"items": items, "ln": _linker(db)})


def seen_in_sessions(db: Session, campaign_id: int) -> tuple[int | None, dict[int, dict]]:
    """The latest published session, and for each entry the published key moments that mention it: where it was
    last seen, how many moments, and the latest one."""
    sessions = timeline(db, campaign_id)
    order = {s.id: i for i, s in enumerate(sessions)}
    latest = next((s for s in reversed(sessions) if any(r.status == Status.PUBLISHED for r in s.recaps)), None)
    rows = db.execute(
        select(EventEntity.entity_id, StoryEvent)
        .join(StoryEvent, StoryEvent.id == EventEntity.event_id)
        .join(GameSession, GameSession.id == StoryEvent.session_id)
        .where(GameSession.campaign_id == campaign_id, StoryEvent.status == Status.PUBLISHED)
    ).all()
    by_entity: dict[int, list[StoryEvent]] = {}
    for entity_id, event in rows:
        by_entity.setdefault(entity_id, []).append(event)
    seen = {}
    for entity_id, events in by_entity.items():
        events.sort(key=lambda e: (order.get(e.session_id, 10**6), e.position, e.id))
        last = events[-1]
        seen[entity_id] = {"session_id": last.session_id, "label": session_label(last.session), "count": len(events), "latest": last.text}
    return (latest.id if latest else None), seen


@router.get("/campaign")
def campaign_page(request: Request, open: str = "", tab: str = "", db: Session = Depends(get_db)):
    """The Campaign page (roadmap step 11; Brett 2026-10-22): tabs World (the Reader: names down the left, one entry
    on the page), Quests (the board), Relationships (family trees, other ties, anyone's connections) and Glossary.
    `?open=<id>` is an entry's address (a quest's opens Quests); `?tab=` picks a tab."""
    from app.entity_pages import entity_context

    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    campaign = web.campaign(db)
    editor = can_edit_entries(user)  # the DM, reviewers and admins also see hidden entries, and get "+ New"
    visible = lambda e: e.status == Status.PUBLISHED or editor  # noqa: E731
    quests, done, groups, glossary, seen, latest, selected, board, fams, tie = [], [], [], [], {}, None, None, [], [], {}
    asked = None
    if campaign:
        entries = list(
            db.scalars(
                select(Entity)
                .where(Entity.campaign_id == campaign.id, Entity.kind != EntityKind.PC)
                .order_by(Entity.name)
            )
        )
        entries = [e for e in entries if visible(e)]
        latest, seen = seen_in_sessions(db, campaign.id)
        quests = [e for e in entries if e.kind == EntityKind.QUEST and e.quest_open is not False]
        done = [e for e in entries if e.kind == EntityKind.QUEST and e.quest_open is False]
        for kind, title in GROUPS:
            if kind != EntityKind.QUEST and (rows := [e for e in entries if e.kind == kind]):
                groups.append((title, rows))
        glossary = list(db.scalars(select(GlossaryTerm).where(GlossaryTerm.campaign_id == campaign.id).order_by(GlossaryTerm.term)))
        board = campaign_views.quest_board(db, campaign.id, quests, visible, latest)
        fams = campaign_views.families(db, campaign.id, visible)
        tie = campaign_views.ties(db, campaign.id, visible)
        # The entry to show: the one asked for, else something from the last session, else the first one
        asked = next((e for e in entries if open.isdigit() and e.id == int(open)), None)
        reference = [e for _, rows in groups for e in rows]
        recent = [e for e in reference if latest and seen.get(e.id, {}).get("session_id") == latest]
        selected = (asked if asked and asked.kind != EntityKind.QUEST else None) or next(iter(recent + reference), None)
    if tab not in ("world", "quests", "relationships", "glossary"):
        tab = "quests" if asked is not None and asked.kind == EntityKind.QUEST else "world"
    article = {**entity_context(db, selected, user), "where": "reader"} if selected else {}
    return templates.TemplateResponse(
        request, "campaign.html", {"campaign": campaign, "quests": quests, "done_quests": done, "groups": groups, "glossary": glossary,
                                   "editor": editor, "seen": seen, "latest": latest, "selected": selected, "tab": tab,
                                   "board": board, "families": fams, "ties": tie, "open_quest": asked.id if asked is not None else None,
                                   "toast": request.session.pop("toast", None), **article}
    )
