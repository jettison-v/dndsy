"""Routes for entity pages (/campaign/<id>) and @-mention suggestions.

Like the review page, actions are HTMX requests that return the re-rendered
entity body plus a toast; without HTMX they redirect back to the page.
"""

import json
from collections.abc import Callable

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import entities, relations
from app.auth import current_user, is_reviewer
from app.db import get_db
from app.extraction import ExtractionError
from app.models import Campaign, Entity, Fact, Status
from app.templating import templates

router = APIRouter(prefix="/campaign")


def _visible(entity: Entity | None, user: dict | None) -> bool:
    return entity is not None and (entity.status == Status.PUBLISHED or is_reviewer(user))


def _not_found(request: Request):
    return templates.TemplateResponse(
        request, "message.html", {"title": "Not found", "message": "That page isn't in the campaign record."}, status_code=404
    )


def entity_context(db: Session, entity: Entity, user: dict) -> dict:
    reviewer = is_reviewer(user)
    facts = list(db.scalars(select(Fact).where(Fact.entity_id == entity.id).order_by(Fact.id)))
    email = (user.get("email") or "").lower()
    others = [
        e
        for e in db.scalars(select(Entity).where(Entity.campaign_id == entity.campaign_id, Entity.id != entity.id).order_by(Entity.name))
        if e.status == Status.PUBLISHED or reviewer
    ]
    return {
        "e": entity,
        "kind_label": entities.KIND_LABELS.get(entity.kind, entity.kind.value),
        "merged": [f for f in facts if f.status == "merged"],
        "pending": [f for f in facts if f.status == "pending"] if reviewer else [],
        "mine_pending": [f for f in facts if f.status == "pending" and f.author_email.lower() == email] if not reviewer else [],
        "done_facts": sorted((f for f in facts if f.status != "pending"), key=lambda f: f.updated_at, reverse=True) if reviewer else [],
        "relations": relations.lines_for(db, entity),
        "rel_choices": relations.CHOICES,
        "others": others,
        "moments": entities.moments(db, entity),
    }


@router.get("/{entity_id:int}")
def entity_page(request: Request, entity_id: int, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entity = db.get(Entity, entity_id)
    if not _visible(entity, user):
        return _not_found(request)
    return templates.TemplateResponse(
        request, "entity.html", {**entity_context(db, entity, user), "toast": request.session.pop("toast", None)}
    )


def _act(request: Request, db: Session, entity_id: int, action: Callable[[Entity, dict], str], reviewer_only: bool = True):
    """Run an entity-page action, commit, and answer with the updated body."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if reviewer_only and not is_reviewer(user):
        return templates.TemplateResponse(
            request, "message.html", {"title": "Not available", "message": "Only reviewers can do that."}, status_code=403
        )
    entity = db.get(Entity, entity_id)
    if not _visible(entity, user):
        return _not_found(request)
    try:
        message = action(entity, user)
        db.commit()
    except (entities.EntityError, relations.RelationError, ExtractionError) as e:
        db.rollback()
        message = str(e)
    db.expire_all()
    entity = db.get(Entity, entity_id)
    if entity is None:  # e.g. removed while acting
        return RedirectResponse("/campaign", status_code=303)
    if request.headers.get("HX-Request"):
        response = templates.TemplateResponse(request, "_entity_body.html", entity_context(db, entity, user))
        response.headers["HX-Trigger"] = json.dumps({"toast": message})
        return response
    request.session["toast"] = message
    return RedirectResponse(f"/campaign/{entity_id}", status_code=303)


@router.post("/{entity_id:int}/facts")
def add_fact(request: Request, entity_id: int, text: str = Form(""), db: Session = Depends(get_db)):
    def act(entity, user):
        entities.add_fact(db, entity, text, user)
        return "Fact saved" if is_reviewer(user) else "Thanks! A reviewer will add it to the page."

    return _act(request, db, entity_id, act, reviewer_only=False)


def _fact_action(request: Request, db: Session, fact_id: int, fn: Callable[[Fact], str]):
    fact = db.get(Fact, fact_id)
    if fact is None:
        return RedirectResponse("/campaign", status_code=303)
    return _act(request, db, fact.entity_id, lambda entity, user: fn(fact))


@router.post("/facts/{fact_id:int}/merge")
def merge_fact(request: Request, fact_id: int, db: Session = Depends(get_db)):
    return _fact_action(request, db, fact_id, lambda f: entities.merge_fact(f) or "Merged onto the page")


@router.post("/facts/{fact_id:int}/reject")
def reject_fact(request: Request, fact_id: int, db: Session = Depends(get_db)):
    return _fact_action(request, db, fact_id, lambda f: entities.reject_fact(f) or "Rejected")


@router.post("/facts/{fact_id:int}/undo")
def undo_fact(request: Request, fact_id: int, db: Session = Depends(get_db)):
    return _fact_action(request, db, fact_id, lambda f: entities.undo_fact(f) or "Undone")


@router.post("/{entity_id:int}/description/regenerate")
def regenerate(request: Request, entity_id: int, db: Session = Depends(get_db)):
    def act(entity, user):
        entities.regenerate(db, entity)
        return "Claude drafted a new description"

    return _act(request, db, entity_id, act)


@router.post("/{entity_id:int}/description/accept")
def accept_description(request: Request, entity_id: int, summary: str | None = Form(None), db: Session = Depends(get_db)):
    def act(entity, user):
        entities.accept_description(entity, summary)
        return "Description updated"

    return _act(request, db, entity_id, act)


@router.post("/{entity_id:int}/description/discard")
def discard_description(request: Request, entity_id: int, db: Session = Depends(get_db)):
    return _act(request, db, entity_id, lambda entity, user: entities.discard_description(entity) or "Discarded")


@router.post("/{entity_id:int}/description/undo")
def undo_description(request: Request, entity_id: int, db: Session = Depends(get_db)):
    return _act(request, db, entity_id, lambda entity, user: entities.undo_description(entity) or "Restored the earlier description")


@router.post("/{entity_id:int}/relationships")
def add_relationship(
    request: Request, entity_id: int, type: str = Form(...), other_id: int = Form(...), note: str = Form(""), db: Session = Depends(get_db)
):
    def act(entity, user):
        other = db.get(Entity, other_id)
        if other is None:
            raise relations.RelationError("Pick who or what it's related to.")
        _, created = relations.add(db, entity, type, other, note)
        return "Relationship added" if created else "That relationship is already there"

    return _act(request, db, entity_id, act)


@router.post("/{entity_id:int}/relationships/{rel_id:int}/delete")
def delete_relationship(request: Request, entity_id: int, rel_id: int, db: Session = Depends(get_db)):
    from app.models import EntityRelation

    def act(entity, user):
        rel = db.get(EntityRelation, rel_id)
        if rel and entity.id in (rel.from_entity_id, rel.to_entity_id):
            db.delete(rel)
        return "Relationship removed"

    return _act(request, db, entity_id, act)


@router.get("/mentions")
def mentions(request: Request, q: str = "", db: Session = Depends(get_db)):
    """Name suggestions for "@" in text boxes: [{name, kind, via}]."""
    user = current_user(request)
    if not user:
        return JSONResponse([], status_code=401)
    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    if campaign is None:
        return JSONResponse([])
    return JSONResponse(entities.mention_suggestions(db, campaign.id, q[:60], include_drafts=is_reviewer(user)))
