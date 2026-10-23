"""Corrections and additions from anyone at the table.

- About a person, place, faction, item or creature: becomes a Fact (kind
  "correction" or "addition") in the entity page's merge flow.
- About a session or the glossary: a Suggestion.
Both wait in the inbox (Manage > Inbox) for the DM, a reviewer or an admin.
Glossary terms also get a side panel, with editing for reviewers.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from markupsafe import escape
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import web
from app import entities
from app import access
from app.auth import can_moderate, current_user, is_dm, is_reviewer
from app.db import get_db
from app.extraction import ExtractionError, session_label
from app.models import Correction, Entity, Fact, GameSession, GlossaryTerm, Status, Suggestion
from app.templating import templates

router = APIRouter()

MAX_TEXT = 4000
REDRAFTABLE = ("notes", "account")  # sessions Claude can redraft: transcripts aren't kept; hand-written ones are the DM's words


def _thanks(message: str = "Thanks! The DM or a reviewer will take a look.", follow: bool = False) -> HTMLResponse:
    more = ' <a href="/your-suggestions">See what happens to it</a>' if follow else ""
    return HTMLResponse(f'<p class="all-clear suggest-thanks" role="status">✓ {escape(message)}{more}</p>')


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
    return _thanks("Added to the page.") if is_dm(user) else _thanks(follow=True)


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
    return _thanks(follow=True)


@router.post("/campaign/glossary/suggest")
@router.post("/campaign/glossary/{term_id:int}/suggest")
def suggest_glossary(request: Request, term_id: int | None = None, text: str = Form(""), kind: str = Form("correction"), db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    campaign = web.campaign(db)
    term = db.get(GlossaryTerm, term_id) if term_id else None
    if campaign is None or (term_id and term is None) or not _clean(text):
        return _problem("Write what should change first.")
    db.add(Suggestion(
        campaign_id=campaign.id, target_type="glossary", target_id=term.id if term else None,
        kind="addition" if term is None else _kind(kind), text=_clean(text), **_author(user),
    ))
    db.commit()
    return _thanks(follow=True)


# --- Glossary side panel and editing ---------------------------------------------


def _glossary_context(request: Request, db: Session, term_id: int) -> dict | None:
    user = current_user(request)
    term = db.get(GlossaryTerm, term_id)
    if not user or term is None:
        return None
    return {"g": term, "can_edit": _can_edit_glossary(user)}


def _can_edit_glossary(user: dict | None) -> bool:
    return bool(user) and access.allows("story_extras", access.level(user.get("email")), access.role(user.get("email")))


@router.post("/campaign/glossary/add")
def glossary_add(request: Request, term: str = Form(""), description: str = Form(""), db: Session = Depends(get_db)):
    """The DM (or a reviewer) adds a term directly, no review."""
    user = current_user(request)
    campaign = web.campaign(db)
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


# --- The inbox (Manage > Inbox): the DM, reviewers and admins -----------------------
# One place for everything waiting for an OK (content workflows step 2, Brett 2026-10-22): the table's suggestions
# with the same actions everywhere (Accept · Edit · Ask Claude to work it in · Dismiss), Claude's description
# drafts, and session drafts waiting for review (those keep their own page). Players see what happened to theirs.

# A suggestion's status in the words its author sees (on the entry, and on Your suggestions; no notifications)
OUTCOME = {"pending": "Waiting", "merged": "Added", "added": "Added", "done": "Used", "used": "Used",
           "rejected": "Not used", "dismissed": "Not used"}
OUTCOME_TAG = {"Waiting": "draft", "Added": "new", "Used": "done", "Not used": "faint"}


def outcome(status: str) -> dict:
    label = OUTCOME.get(status, "Waiting")
    return {"label": label, "tag": OUTCOME_TAG[label]}


def from_the_table(db: Session, campaign_id: int) -> list[dict]:
    """Every suggestion waiting for a decision, oldest first: facts on entries, and session or glossary suggestions."""
    items = [
        {"type": "fact", "x": f, "label": e.name, "href": f"{web.base()}/campaign?open={e.id}", "entity": e}
        for f, e in db.execute(select(Fact, Entity).join(Entity, Fact.entity_id == Entity.id)
                               .where(Entity.campaign_id == campaign_id, Fact.status == "pending"))
    ]
    pending = list(db.scalars(select(Suggestion).where(Suggestion.campaign_id == campaign_id, Suggestion.status == "pending")))
    sessions = {s.id: s for s in db.scalars(select(GameSession).where(GameSession.id.in_({x.target_id for x in pending if x.target_type == "session"})))}
    terms = {t.id: t for t in db.scalars(select(GlossaryTerm).where(GlossaryTerm.id.in_({x.target_id for x in pending if x.target_type == "glossary"})))}
    for x in pending:
        if x.target_type == "session" and x.target_id in sessions:
            s = sessions[x.target_id]
            items.append({"type": "session", "x": x, "label": session_label(s), "href": f"{web.base()}/manage/sessions/{s.id}",
                          "redraft": s.source in REDRAFTABLE})
        elif x.target_type == "glossary":
            t = terms.get(x.target_id)
            items.append({"type": "glossary", "x": x, "label": f"Glossary: {t.term}" if t else "Glossary: new term",
                          "href": f"/campaign/glossary/{t.id}" if t else "/campaign#glossary", "term": t})
    return sorted(items, key=lambda it: (it["x"].created_at, it["x"].id))


def description_drafts(db: Session, campaign_id: int) -> list[Entity]:
    """Descriptions Claude drafted (Regenerate, or Ask Claude to work it in) that nobody has accepted or discarded."""
    return list(db.scalars(select(Entity).where(Entity.campaign_id == campaign_id, Entity.draft_summary.is_not(None)).order_by(Entity.name)))


def sessions_to_review(db: Session, campaign_id: int) -> list[dict]:
    from app import review
    from app.extraction import timeline

    out = []
    for s in timeline(db, campaign_id):
        status = review.review_status(s, False)
        if status in ("draft", "edited"):
            out.append({"s": s, "label": session_label(s), "status": status})
    return out


def waiting_count(db: Session) -> int:
    """Suggestions from the table plus Claude's drafts waiting for an OK (session reviews count on Recaps)."""
    campaign = web.campaign(db)
    if campaign is None:
        return 0
    return len(from_the_table(db, campaign.id)) + len(description_drafts(db, campaign.id))


@router.get("/manage/inbox")  # under the campaign: /c/<campaign>/manage/inbox
def inbox(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_moderate(user):
        return RedirectResponse("/your-suggestions", status_code=303)
    campaign = web.campaign(db)
    return templates.TemplateResponse(request, "suggestions.html", {
        "items": from_the_table(db, campaign.id) if campaign else [],
        "drafts": description_drafts(db, campaign.id) if campaign else [],
        "reviews": sessions_to_review(db, campaign.id) if campaign else [],
        "toast": request.session.pop("toast", None),
    })


@router.get("/your-suggestions")
def mine(request: Request, db: Session = Depends(get_db)):
    """Your suggestions and what happened to each: Waiting, Added, Used or Not used."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    email = (user.get("email") or "").lower()
    rows = [{"x": f, "label": e.name, "href": f"{web.base()}/campaign?open={e.id}"}
            for f, e in db.execute(select(Fact, Entity).join(Entity, Fact.entity_id == Entity.id)
                                   .where(func.lower(Fact.author_email) == email, Entity.status == Status.PUBLISHED))]
    for x in db.scalars(select(Suggestion).where(func.lower(Suggestion.author_email) == email)):
        if x.target_type == "session":
            s = db.get(GameSession, x.target_id)
            rows.append({"x": x, "label": session_label(s) if s else "A session", "href": f"{web.base()}/?tab=sessions#s{s.id}" if s else f"{web.base()}/?tab=sessions"})
        else:
            t = db.get(GlossaryTerm, x.target_id) if x.target_id else None
            rows.append({"x": x, "label": f"Glossary: {t.term}" if t else "Glossary: new term", "href": "/campaign#glossary"})
    rows.sort(key=lambda r: (r["x"].created_at, r["x"].id), reverse=True)
    return templates.TemplateResponse(request, "suggestions_mine.html", {"rows": rows})


def _done(request: Request, message: str) -> RedirectResponse:
    request.session["toast"] = message
    return RedirectResponse(f"{web.base()}/manage/inbox", status_code=303)


@router.post("/suggestions/facts/{fact_id:int}/{action}")
def act_on_fact(request: Request, fact_id: int, action: str, text: str = Form(""), db: Session = Depends(get_db)):
    """Accept (on the page as written), Edit then accept, Ask Claude to work it in (accept, then Claude drafts a
    new description using it, for you to check), or Dismiss. "merge" and "reject" are the old names."""
    user = current_user(request)
    fact = db.get(Fact, fact_id)
    action = {"merge": "accept", "reject": "dismiss"}.get(action, action)
    if not can_moderate(user) or fact is None or fact.status != "pending" or action not in ("accept", "edit", "claude", "dismiss"):
        return RedirectResponse(f"{web.base()}/manage/inbox", status_code=303)
    entity = db.get(Entity, fact.entity_id)
    if action == "dismiss":
        entities.reject_fact(fact)
        db.commit()
        return _done(request, "Dismissed. Whoever sent it sees Not used.")
    if action == "edit":
        if not _clean(text):
            return _done(request, "Write the fact first.")
        fact.text = _clean(text)
    entities.merge_fact(fact)
    db.commit()
    if action != "claude":
        return _done(request, f"Added to {entity.name}.")
    try:
        entities.regenerate(db, entity)
    except ExtractionError as e:
        return _done(request, f"Added to {entity.name}, but Claude couldn't draft a description: {e}")
    return _done(request, f"Added to {entity.name}, and Claude drafted a new description with it. Check it under Claude's drafts.")


@router.post("/admin/suggestions/{suggestion_id:int}/glossary")
def accept_glossary(request: Request, suggestion_id: int, term: str = Form(""), description: str = Form(""), misheard_as: str = Form(""),
                    db: Session = Depends(get_db)):
    """Edit then accept a glossary suggestion: fix the term it's about, or add the new term it suggests."""
    user = current_user(request)
    x = db.get(Suggestion, suggestion_id)
    if not _can_edit_glossary(user) or x is None or x.status != "pending" or x.target_type != "glossary":
        return RedirectResponse(f"{web.base()}/manage/inbox", status_code=303)
    g = db.get(GlossaryTerm, x.target_id) if x.target_id else None
    new_term = " ".join(term.split())[:200]
    clash = db.scalar(select(GlossaryTerm).where(GlossaryTerm.campaign_id == x.campaign_id, GlossaryTerm.term == new_term,
                                                 GlossaryTerm.id != (g.id if g else -1)))
    if not new_term or clash:
        return _done(request, "That spelling is empty or already in the glossary.")
    misheard = [m.strip() for m in misheard_as.split(",") if m.strip()]
    if g is None:
        db.add(GlossaryTerm(campaign_id=x.campaign_id, term=new_term, description=description.strip()[:MAX_TEXT], misheard_as=misheard))
        x.status = "added"
    else:
        g.term, g.description, g.misheard_as = new_term, description.strip()[:MAX_TEXT], misheard
        x.status = "used"
    db.commit()
    return _done(request, f"{'Added' if g is None else 'Updated'} {new_term} in the glossary.")


@router.post("/admin/suggestions/{suggestion_id:int}/{action}")
def act_on_suggestion(request: Request, suggestion_id: int, action: str, db: Session = Depends(get_db)):
    """A session or glossary suggestion: Ask Claude to work it in (redraft the session with it), I fixed it (you
    edited the recap or term yourself), or Dismiss. "use" (into the next redraft, no redraft now) still works."""
    user = current_user(request)
    x = db.get(Suggestion, suggestion_id)
    if not can_moderate(user) or x is None or x.status != "pending" or action not in ("use", "claude", "done", "dismiss"):
        return RedirectResponse(f"{web.base()}/manage/inbox", status_code=303)
    if action in ("use", "claude") and x.target_type == "session":
        s = db.get(GameSession, x.target_id)
        if action == "claude" and (s is None or s.source not in REDRAFTABLE):
            return _done(request, "Claude can't redraft this session; edit the recap yourself, then press I fixed it.")
        answer = _answer(x)
        db.add(answer)
        x.status = "used"
        db.commit()  # before the redraft starts, so it reads the answer
        if action == "use":
            return _done(request, "Added to this session's answers; redraft to use it.")
        from app import admin_sessions

        if not admin_sessions._draft_in_background([s.id]):
            db.delete(answer)
            x.status = "pending"
            db.commit()
            return _done(request, "Claude is busy drafting; try again in a minute.")
        return _done(request, f"Claude is redrafting {session_label(s)} with it (about a minute). Review and publish it from Sessions to review.")
    x.status = "done" if action == "done" else "dismissed"
    db.commit()
    return _done(request, "Marked used." if action == "done" else "Dismissed. Whoever sent it sees Not used.")
