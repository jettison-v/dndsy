"""'Previously on…': the published story, for everyone at the table."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.db import get_db
from app.extraction import _order_key, session_label
from app.models import Campaign, Entity, EntityKind, EventKind, GameSession, Status
from app.render import markdown_to_html
from app.templating import templates

router = APIRouter()


def published_story(db: Session) -> dict:
    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    if campaign is None:
        return {"latest": None, "earlier": [], "threads": [], "quests": []}
    sessions = sorted(db.scalars(select(GameSession).where(GameSession.campaign_id == campaign.id)), key=_order_key)
    items = []
    for s in sessions:
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
    threads = [t for item in items[-3:] for t in item["theories"]]
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
    return {"latest": items[-1] if items else None, "earlier": list(reversed(items[:-1])), "threads": threads, "quests": quests}


@router.get("/story")
def story(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    return templates.TemplateResponse(request, "story.html", {"user": user, **published_story(db)})
