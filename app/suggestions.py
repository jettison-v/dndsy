"""Corrections and additions from anyone at the table.

- About a person, place, faction, item or creature: becomes a Fact (kind
  "correction" or "addition") in the entity page's merge flow.
- About a session or the glossary: a Suggestion that reviewers handle from
  Manage > Review ("From the table").
Glossary terms also get a side panel, with editing for reviewers.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markupsafe import escape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import entities
from app.auth import current_user, is_reviewer
from app.db import get_db
from app.extraction import session_label
from app.models import Campaign, Correction, Entity, Fact, GameSession, GlossaryTerm, Status, Suggestion
from app.templating import templates

router = APIRouter()

MAX_TEXT = 4000


def _thanks(message: str = "Thanks! A reviewer will take a look.") -> HTMLResponse:
    return HTMLResponse(f'<p class="all-clear suggest-thanks" role="status">✓ {escape(message)}</p>')


def _problem(message: str) -> HTMLResponse:
    return HTMLResponse(f'<p class="flash bad" role="alert">{escape(message)}</p>', status_code=200)


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").strip()[:MAX_TEXT]


def _kind(kind: str) -> str:
    return "addition" if kind == "addition" else "correction"


def _author(user: dict) -> dict:
    return {"author_name": (user.get("name") or user.get("email") or "")[:200], "author_email": (user.get("email") or "")[:320]}


# --- Submitting ---------------------------------------------------------------


@router.post("/campaign/{entity_id:int}/suggest")
def suggest_entity(request: Request, entity_id: int, text: str = Form(""), kind: str = Form("correction"), db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    entity = db.get(Entity, entity_id)
    if entity is None or (entity.status != Status.PUBLISHED and not is_reviewer(user)):
        return _problem("That entry isn't in the campaign record.")
    try:
        entities.add_fact(db, entity, text, user, kind=_kind(kind))
    except entities.EntityError as e:
        return _problem(str(e))
    db.commit()
    return _thanks()


@router.post("/sessions/{session_id:int}/suggest")
def suggest_session(request: Request, session_id: int, text: str = Form(""), kind: str = Form("correction"), db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    s = db.get(GameSession, session_id)
    if s is None or not _clean(text):
        return _problem("Write what should change first.")
    db.add(Suggestion(campaign_id=s.campaign_id, target_type="session", target_id=s.id, kind=_kind(kind), text=_clean(text), **_author(user)))
    db.commit()
    return _thanks()


@router.post("/campaign/glossary/suggest")
@router.post("/campaign/glossary/{term_id:int}/suggest")
def suggest_glossary(request: Request, term_id: int | None = None, text: str = Form(""), kind: str = Form("correction"), db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    term = db.get(GlossaryTerm, term_id) if term_id else None
    if campaign is None or (term_id and term is None) or not _clean(text):
        return _problem("Write what should change first.")
    db.add(Suggestion(
        campaign_id=campaign.id, target_type="glossary", target_id=term.id if term else None,
        kind="addition" if term is None else _kind(kind), text=_clean(text), **_author(user),
    ))
    db.commit()
    return _thanks()


# --- Glossary side panel and editing ---------------------------------------------


def _glossary_context(request: Request, db: Session, term_id: int) -> dict | None:
    user = current_user(request)
    term = db.get(GlossaryTerm, term_id)
    if not user or term is None:
        return None
    return {"g": term, "can_edit": is_reviewer(user)}


@router.get("/campaign/glossary/{term_id:int}/peek")
def glossary_peek(request: Request, term_id: int, db: Session = Depends(get_db)):
    ctx = _glossary_context(request, db, term_id)
    if ctx is None:
        return RedirectResponse("/campaign", status_code=303)
    return templates.TemplateResponse(request, "_glossary_peek.html", ctx)


@router.get("/campaign/glossary/{term_id:int}")
def glossary_page(request: Request, term_id: int, db: Session = Depends(get_db)):
    ctx = _glossary_context(request, db, term_id)
    if ctx is None:
        return RedirectResponse("/campaign", status_code=303)
    return templates.TemplateResponse(request, "glossary_term.html", ctx)


@router.post("/campaign/glossary/{term_id:int}/edit")
def glossary_edit(
    request: Request, term_id: int, term: str = Form(...), description: str = Form(""), misheard_as: str = Form(""), db: Session = Depends(get_db)
):
    user = current_user(request)
    g = db.get(GlossaryTerm, term_id)
    if not is_reviewer(user) or g is None:
        return RedirectResponse("/campaign", status_code=303)
    new_term = " ".join(term.split())
    clash = db.scalar(select(GlossaryTerm).where(GlossaryTerm.campaign_id == g.campaign_id, GlossaryTerm.term == new_term, GlossaryTerm.id != g.id))
    if not new_term or clash:
        return _problem("That spelling is empty or already in the glossary.")
    g.term, g.description = new_term, description.strip()
    g.misheard_as = [m.strip() for m in misheard_as.split(",") if m.strip()]
    db.commit()
    return templates.TemplateResponse(request, "_glossary_peek.html", {"g": g, "can_edit": True, "saved": True})


@router.post("/campaign/glossary/{term_id:int}/delete")
def glossary_delete(request: Request, term_id: int, db: Session = Depends(get_db)):
    user = current_user(request)
    g = db.get(GlossaryTerm, term_id)
    if is_reviewer(user) and g is not None:
        db.delete(g)
        db.commit()
    return _thanks("Removed from the glossary. Reload the page to update the list.")


# --- Reviewer queue ("From the table" on Manage > Review) --------------------------


def from_the_table(db: Session, campaign_id: int) -> dict:
    pending = list(
        db.scalars(select(Suggestion).where(Suggestion.campaign_id == campaign_id, Suggestion.status == "pending").order_by(Suggestion.id))
    )
    sessions = {s.id: s for s in db.scalars(select(GameSession).where(GameSession.id.in_({x.target_id for x in pending if x.target_type == "session"})))}
    terms = {t.id: t for t in db.scalars(select(GlossaryTerm).where(GlossaryTerm.id.in_({x.target_id for x in pending if x.target_type == "glossary"})))}
    items = []
    for x in pending:
        if x.target_type == "session" and x.target_id in sessions:
            s = sessions[x.target_id]
            items.append({"x": x, "label": session_label(s), "href": f"/admin/sessions/{s.id}"})
        elif x.target_type == "glossary":
            t = terms.get(x.target_id)
            items.append({"x": x, "label": f"Glossary: {t.term}" if t else "Glossary: new term", "href": f"/campaign/glossary/{t.id}" if t else "/campaign#glossary"})
    facts = db.execute(
        select(Entity.id, Entity.name, func.count(Fact.id))
        .join(Fact, Fact.entity_id == Entity.id)
        .where(Entity.campaign_id == campaign_id, Fact.status == "pending")
        .group_by(Entity.id, Entity.name)
        .order_by(Entity.name)
    ).all()
    return {"entries": items, "facts": [{"id": i, "name": n, "count": c} for i, n, c in facts]}


@router.post("/admin/suggestions/{suggestion_id:int}/{action}")
def act_on_suggestion(request: Request, suggestion_id: int, action: str, db: Session = Depends(get_db)):
    user = current_user(request)
    x = db.get(Suggestion, suggestion_id)
    if not is_reviewer(user) or x is None or action not in ("use", "done", "dismiss"):
        return RedirectResponse("/admin/sessions", status_code=303)
    if action == "use" and x.target_type == "session":
        # Feed it to the next redraft exactly like an answer to Claude's question.
        db.add(Correction(
            campaign_id=x.campaign_id, session_id=x.target_id, kind="answer",
            before=f"{x.kind.capitalize()} from {x.author_name or 'someone at the table'}", after=x.text,
        ))
        x.status = "used"
        request.session["toast"] = "Added to this session's answers; redraft to use it."
    else:
        x.status = "done" if action == "done" else "dismissed"
        request.session["toast"] = "Marked done" if action == "done" else "Dismissed"
    db.commit()
    return RedirectResponse("/admin/sessions#from-the-table", status_code=303)
