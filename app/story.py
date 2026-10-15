"""Pages for the whole table: Previously on…, Sessions, Campaign, Characters."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.extraction import _order_key, session_label
from app.models import Campaign, Character, Entity, EntityKind, EventKind, GameSession, GlossaryTerm, Status
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
    for s in sorted(db.scalars(select(GameSession).where(GameSession.campaign_id == campaign.id)), key=_order_key):
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


@router.get("/")
@router.get("/story")
def story(request: Request, db: Session = Depends(get_db)):
    if not _signed_in(request):
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "story.html", published_story(db))


@router.get("/sessions")
def sessions(request: Request, db: Session = Depends(get_db)):
    if not _signed_in(request):
        return RedirectResponse("/login", status_code=303)
    campaign = _campaign(db)
    items = list(reversed(published_items(db, campaign))) if campaign else []
    return templates.TemplateResponse(request, "sessions.html", {"items": items})


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
    return templates.TemplateResponse(request, "campaign.html", {"campaign": campaign, "groups": groups, "glossary": glossary})


@router.get("/characters")
def characters(request: Request, db: Session = Depends(get_db)):
    if not _signed_in(request):
        return RedirectResponse("/login", status_code=303)
    campaign = _campaign(db)
    chars = (
        list(db.scalars(select(Character).join(Entity).where(Entity.campaign_id == campaign.id).order_by(Entity.name)))
        if campaign
        else []
    )
    return templates.TemplateResponse(request, "characters.html", {"characters": chars})
