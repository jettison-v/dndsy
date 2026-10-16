"""Pages for the whole table: Previously on…, Sessions, Campaign. Characters: app/character_pages.py."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import review
from app.auth import current_user
from app.db import get_db
from app.extraction import session_label, timeline
from app.linking import Linker, entity_linker
from app.models import Campaign, Correction, Entity, EntityKind, EventKind, GameSession, GlossaryTerm, Status
from app.relations import family_graph
from app.render import markdown_to_html
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


def _campaign(db: Session) -> Campaign | None:
    return db.scalar(select(Campaign).order_by(Campaign.id))


def published_items(db: Session, campaign: Campaign) -> list[dict]:
    """Published sessions in story order, each with its recap HTML and events."""
    items = []
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
            })
    return items


def published_story(db: Session) -> dict:
    campaign = _campaign(db)
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


def _signed_in(request: Request):
    return current_user(request)


def questions_card(db: Session, user: dict) -> list[dict]:
    """Claude's questions that a reviewer sent to this person ("Ask…")."""
    items = []
    for c in review.questions_for(db, user):
        s = db.get(GameSession, c.session_id) if c.session_id else None
        if s is not None:
            items.append({"c": c, "label": session_label(s) + (f": {s.title}" if s.title else "")})
    return items


def _linker(db: Session) -> Linker:
    campaign = _campaign(db)
    return entity_linker(db, campaign.id) if campaign else Linker(None, {})


@router.get("/")
@router.get("/story")
def story(request: Request, db: Session = Depends(get_db)):
    user = _signed_in(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(
        request,
        "story.html",
        {
            **published_story(db),
            "questions": questions_card(db, user),
            "toast": request.session.pop("toast", None),
            "ln": _linker(db),
        },
    )


@router.post("/questions/{correction_id:int}/answer")
def answer_question(
    request: Request, correction_id: int, answer: str = Form(""), remember: str = Form(""), db: Session = Depends(get_db)
):
    """The person a question was sent to answers it from Previously on…"""
    user = _signed_in(request)
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
    if not _signed_in(request):
        return RedirectResponse("/login", status_code=303)
    campaign = _campaign(db)
    items = list(reversed(published_items(db, campaign))) if campaign else []
    return templates.TemplateResponse(request, "sessions.html", {"items": items, "ln": _linker(db)})


@router.get("/campaign")
def campaign_page(request: Request, db: Session = Depends(get_db)):
    if not _signed_in(request):
        return RedirectResponse("/login", status_code=303)
    campaign = _campaign(db)
    groups, glossary = [], []
    if campaign:
        entities = list(
            db.scalars(
                select(Entity)
                .where(Entity.campaign_id == campaign.id, Entity.status == Status.PUBLISHED, Entity.kind != EntityKind.PC)
                .order_by(Entity.name)
            )
        )
        for kind, title in GROUPS:
            entries = [e for e in entities if e.kind == kind]
            if kind == EntityKind.QUEST:
                entries.sort(key=lambda e: (not e.quest_open, e.name))
            if entries:
                groups.append((title, entries))
        glossary = list(db.scalars(select(GlossaryTerm).where(GlossaryTerm.campaign_id == campaign.id).order_by(GlossaryTerm.term)))
        graph = family_graph(db, campaign.id, visible=lambda e: e.status == Status.PUBLISHED)
    return templates.TemplateResponse(
        request, "campaign.html", {"campaign": campaign, "groups": groups, "glossary": glossary, "tree": graph.mermaid() if campaign and graph.people else ""}
    )

