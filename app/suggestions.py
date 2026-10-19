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
from app import access
from app.auth import can_moderate, current_user, is_dm, is_reviewer
from app.db import get_db
from app.extraction import session_label
from app.models import Campaign, Correction, Entity, Fact, GameSession, GlossaryTerm, Status, Suggestion
from app.templating import templates

router = APIRouter()

MAX_TEXT = 4000


def _thanks(message: str = "Thanks! The DM or a reviewer will take a look.") -> HTMLResponse:
    return HTMLResponse(f'<p class="all-clear suggest-thanks" role="status">✓ {escape(message)}</p>')


def _problem(message: str) -> HTMLResponse:
    return HTMLResponse(f'<p class="flash bad" role="alert">{escape(message)}</p>', status_code=200)


def _clean(text: str) -> str:
    return text.replace("\r\n", "\n").strip()[:MAX_TEXT]


def _kind(kind: str) -> str:
    return "addition" if kind == "addition" else "correction"


def _author(user: dict) -> dict:
    return {"author_name": (user.get("name") or user.get("email") or "")[:200], "author_email": (user.get("email") or "")[:320]}


def _answer(x: Suggestion) -> Correction:
    """Feed a session suggestion to the next redraft exactly like an answer to Claude's question."""
    who = "the DM" if x.from_dm else (x.author_name or "someone at the table")
    return Correction(campaign_id=x.campaign_id, session_id=x.target_id, kind="answer",
                      before=f"{x.kind.capitalize()} from {who}", after=x.text)


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
        entities.add_fact(db, entity, text, user, kind=_kind(kind), merged=is_dm(user))
    except entities.EntityError as e:
        return _problem(str(e))
    db.commit()
    return _thanks("Added to the page. Reload to see it.") if is_dm(user) else _thanks()


@router.post("/sessions/{session_id:int}/suggest")
def suggest_session(request: Request, session_id: int, text: str = Form(""), kind: str = Form("correction"), db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    s = db.get(GameSession, session_id)
    if s is None or not _clean(text):
        return _problem("Write what should change first.")
    x = Suggestion(campaign_id=s.campaign_id, target_type="session", target_id=s.id, kind=_kind(kind), text=_clean(text), **_author(user))
    db.add(x)
    if is_dm(user):  # no review: straight into the session's answers, and shown under the recap
        x.status, x.from_dm = "used", True
        db.add(_answer(x))
        db.commit()
        return _thanks("Saved. It shows under the recap now, and the next redraft of this session uses it.")
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
    return {"g": term, "can_edit": _can_edit_glossary(user)}


def _can_edit_glossary(user: dict | None) -> bool:
    return bool(user) and access.allows("story_extras", access.level(user.get("email")), access.is_dm(user.get("email")))


@router.post("/campaign/glossary/add")
def glossary_add(request: Request, term: str = Form(""), description: str = Form(""), db: Session = Depends(get_db)):
    """The DM (or a reviewer) adds a term directly, no review."""
    user = current_user(request)
    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    new_term = " ".join(term.split())[:200]
    if not _can_edit_glossary(user) or campaign is None:
        return _problem("Only the DM and reviewers can add terms directly.")
    if not new_term or db.scalar(select(GlossaryTerm).where(GlossaryTerm.campaign_id == campaign.id, GlossaryTerm.term == new_term)):
        return _problem("That term is empty or already in the glossary.")
    db.add(GlossaryTerm(campaign_id=campaign.id, term=new_term, description=description.strip()[:MAX_TEXT], misheard_as=[]))
    db.commit()
    return _thanks(f"Added {new_term} to the glossary. Reload the page to see it in the list.")


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
    if not _can_edit_glossary(user) or g is None:
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
    if _can_edit_glossary(user) and g is not None:
        db.delete(g)
        db.commit()
    return _thanks("Removed from the glossary. Reload the page to update the list.")


# --- The inbox (Manage > Suggestions): admins, reviewers and the DM -----------------


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
        select(Fact, Entity.name).join(Entity, Fact.entity_id == Entity.id)
        .where(Entity.campaign_id == campaign_id, Fact.status == "pending").order_by(Fact.id)
    ).all()
    return {"entries": items, "facts": [{"f": f, "name": n} for f, n in facts]}


def waiting_count(db: Session) -> int:
    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    if campaign is None:
        return 0
    t = from_the_table(db, campaign.id)
    return len(t["entries"]) + len(t["facts"])


@router.get("/suggestions")
def inbox(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_moderate(user):
        return templates.TemplateResponse(request, "message.html", {"title": "Not available",
                                          "message": "Suggestions go to the DM, admins and reviewers."}, status_code=403)
    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    return templates.TemplateResponse(request, "suggestions.html", {
        "table": from_the_table(db, campaign.id) if campaign else {"entries": [], "facts": []},
        "toast": request.session.pop("toast", None),
    })


@router.post("/suggestions/facts/{fact_id:int}/{action}")
def act_on_fact(request: Request, fact_id: int, action: str, db: Session = Depends(get_db)):
    user = current_user(request)
    fact = db.get(Fact, fact_id)
    if can_moderate(user) and fact is not None and fact.status == "pending" and action in ("merge", "reject"):
        (entities.merge_fact if action == "merge" else entities.reject_fact)(fact)
        db.commit()
        request.session["toast"] = "Added to the page" if action == "merge" else "Rejected"
    return RedirectResponse("/suggestions", status_code=303)


@router.post("/admin/suggestions/{suggestion_id:int}/{action}")
def act_on_suggestion(request: Request, suggestion_id: int, action: str, db: Session = Depends(get_db)):
    user = current_user(request)
    x = db.get(Suggestion, suggestion_id)
    if not can_moderate(user) or x is None or action not in ("use", "done", "dismiss"):
        return RedirectResponse("/suggestions", status_code=303)
    if action == "use" and x.target_type == "session":
        db.add(_answer(x))
        x.status = "used"
        request.session["toast"] = "Added to this session's answers; redraft to use it."
    else:
        x.status = "done" if action == "done" else "dismissed"
        request.session["toast"] = "Marked done" if action == "done" else "Dismissed"
    db.commit()
    return RedirectResponse("/suggestions", status_code=303)
