"""Admin: the Review list and the session review page.

Actions on the review page are HTMX requests: each returns the re-rendered
review body (plus a toast) so the page updates in place. Without HTMX they
fall back to a redirect.
"""

import json
import threading
from collections.abc import Callable

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import db as dbmod
from app import review
from app.admin import _reviewer_guard as _guard
from app.db import get_db
from app.extraction import (
    ExtractionError,
    Source,
    extract_session,
    latest_campaign_notes,
    notes_source_for,
    session_label,
    split_notes,
    timeline,
)
from app.models import NON_DRAFTING_SOURCES, Campaign, ExtractionRun, GameSession, Proposal
from app.linking import entity_linker
from app.render import markdown_to_html
from app.templating import templates

router = APIRouter(prefix="/admin")

_busy = threading.Lock()  # one drafting job at a time keeps costs and order predictable


def _running_ids(db: Session) -> set[int]:
    """Sessions with a draft in progress (conversation checks and entity runs don't count)."""
    return set(
        db.scalars(
            select(ExtractionRun.session_id).where(ExtractionRun.status == "running", ExtractionRun.source.notin_(NON_DRAFTING_SOURCES))
        )
    )


def source_for(db: Session, session: GameSession):
    """(Source, background text, background images) for drafting this session."""
    if session.source == "account":
        from app.conversation import conversation_text

        if not session.messages:
            raise ExtractionError("Write what happened first.")
        return Source("account", conversation_text(session)), "", []
    return notes_source_for(db, session)


def _draft_in_background(session_ids: list[int]) -> bool:
    """Draft sessions one after another (notes or written accounts), in a thread."""
    if not _busy.acquire(blocking=False):
        return False

    def work():
        try:
            for sid in session_ids:
                with dbmod.SessionLocal() as db:
                    session = db.get(GameSession, sid)
                    try:
                        source, background, bg_images = source_for(db, session)
                    except ExtractionError as e:
                        db.add(ExtractionRun(session_id=sid, source=session.source, status="error", error=str(e)))
                        db.commit()
                        continue
                    extract_session(db, session, source, background=background, background_images=bg_images)
        finally:
            _busy.release()

    threading.Thread(target=work, daemon=True).start()
    return True


def draft_transcript_in_background(session_id: int, text: str) -> bool:
    """Draft one session from a filtered transcript. The text lives only in this
    thread's memory for the Claude call; it is never written to the database."""
    if not _busy.acquire(blocking=False):
        return False

    def work():
        try:
            with dbmod.SessionLocal() as db:
                session = db.get(GameSession, session_id)
                extract_session(db, session, Source("transcript", text))
        finally:
            _busy.release()

    threading.Thread(target=work, daemon=True).start()
    return True


# --- Review list -------------------------------------------------------------


@router.get("/sessions")
def sessions_page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    sessions = timeline(db, campaign.id) if campaign else []
    running = _running_ids(db)
    snap = latest_campaign_notes(db, campaign.id) if campaign else None
    with_notes = set(split_notes(snap.text)[1]) if snap else set()
    spent = db.scalar(select(func.coalesce(func.sum(ExtractionRun.cost_usd), 0.0))) or 0.0
    rows = []
    for s in reversed(sessions):  # newest first
        last_run = db.scalar(
            select(ExtractionRun)
            .where(ExtractionRun.session_id == s.id, ExtractionRun.source.notin_(NON_DRAFTING_SOURCES))
            .order_by(ExtractionRun.id.desc())
        )
        rows.append({
            "s": s,
            "label": session_label(s),
            "status": review.review_status(s, s.id in running),
            "has_notes": s.number in with_notes,
            "last_run": last_run,
        })
    missing = [r["s"].id for r in reversed(rows) if r["has_notes"] and r["status"] == "no draft"]  # oldest first
    return templates.TemplateResponse(
        request,
        "admin_sessions.html",
        {
            "rows": rows,
            "missing": missing,
            "spent": spent,
            "running": bool(running),
            "notes_synced": snap is not None,
            "toast": request.session.pop("toast", None),
        },
    )


@router.post("/sessions/draft")
def draft(request: Request, session_ids: list[int] = Form(...)):
    user, denied = _guard(request)
    if denied:
        return denied
    started = _draft_in_background(session_ids)
    request.session["toast"] = (
        "Claude is drafting… about a minute per session" if started else "Claude is already drafting; try again when it finishes"
    )
    target = f"/admin/sessions/{session_ids[0]}" if len(session_ids) == 1 else "/admin/sessions"
    return RedirectResponse(target, status_code=303)


# --- Review page ---------------------------------------------------------------


def _next_session(db: Session, s: GameSession) -> dict | None:
    """The session after this one, and whether it can be drafted from notes."""
    ordered = timeline(db, s.campaign_id)
    later = ordered[ordered.index(s) + 1 :]
    if not later:
        return None
    nxt = later[0]
    snap = latest_campaign_notes(db, s.campaign_id)
    has_notes = bool(snap) and nxt.number in split_notes(snap.text)[1]
    return {"s": nxt, "label": session_label(nxt), "drafted": bool(nxt.recaps), "has_notes": has_notes}


def _body_context(db: Session, s: GameSession) -> dict:
    running = _running_ids(db)
    ctx = review.review_context(db, s, drafting=s.id in running)
    ctx.update(
        s=s,
        label=session_label(s),
        recap_html=markdown_to_html(ctx["latest"].body, lambda n: None) if ctx["latest"] else "",
        next_session=_next_session(db, s),
        ln=entity_linker(db, s.campaign_id, include_drafts=True),
        anything_drafting=bool(running),
    )
    return ctx


@router.get("/sessions/{session_id:int}")
def review_page(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    if s is None:
        return RedirectResponse("/admin/sessions", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin_review.html",
        {**_body_context(db, s), "toast": request.session.pop("toast", None), "auto_check": request.query_params.get("check") == "1"},
    )


@router.get("/sessions/{session_id:int}/body")
def review_body(request: Request, session_id: int, db: Session = Depends(get_db)):
    """Partial for polling while Claude drafts."""
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    if s is None:
        return RedirectResponse("/admin/sessions", status_code=303)
    return templates.TemplateResponse(request, "_review_body.html", _body_context(db, s))


def _act(request: Request, db: Session, session_id: int, action: Callable[[GameSession], str]):
    """Run a review action, commit, and answer with the updated review body."""
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    if s is None:
        return RedirectResponse("/admin/sessions", status_code=303)
    try:
        message = action(s)
        db.commit()
    except review.ReviewError as e:
        db.rollback()
        message = str(e)
    db.expire_all()
    s = db.get(GameSession, session_id)
    if request.headers.get("HX-Request"):
        response = templates.TemplateResponse(request, "_review_body.html", _body_context(db, s))
        response.headers["HX-Trigger"] = json.dumps({"toast": message})
        return response
    request.session["toast"] = message
    return RedirectResponse(f"/admin/sessions/{session_id}", status_code=303)


@router.post("/sessions/{session_id:int}/questions/answer")
def answer(
    request: Request,
    session_id: int,
    q: str = Form(...),
    answer: str = Form(""),
    remember: str = Form(""),
    on_behalf_of: str = Form(""),
    db: Session = Depends(get_db),
):
    def act(s):
        review.answer_question(db, s, q, answer, bool(remember), answered_by=on_behalf_of)
        return f"Saved {on_behalf_of}'s answer" if on_behalf_of.strip() else "Answer saved"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/questions/ask")
def ask(request: Request, session_id: int, q: str = Form(...), person: str = Form(""), note: str = Form(""), db: Session = Depends(get_db)):
    def act(s):
        user = request.session.get("user") or {}
        review.ask_question(db, s, q, person, note, asked_by=user.get("name") or user.get("email", ""))
        return f"Waiting on {' '.join(person.split())}"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/questions/skip")
def skip(request: Request, session_id: int, q: str = Form(...), db: Session = Depends(get_db)):
    def act(s):
        review.skip_question(db, s, q)
        return "Skipped"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/questions/reopen")
def reopen(request: Request, session_id: int, q: str = Form(...), db: Session = Depends(get_db)):
    def act(s):
        review.reopen_question(db, s, q)
        return "Question reopened"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/redraft")
def redraft(request: Request, session_id: int, db: Session = Depends(get_db)):
    def act(s):
        if s.source == "transcript":
            raise review.ReviewError("Transcript sessions are redrafted by sending them again from the Processor.")
        if not _draft_in_background([s.id]):
            raise review.ReviewError("Claude is busy; try again in a minute.")
        return "Claude is redrafting… about a minute"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/recap")
def save_recap(request: Request, session_id: int, body: str = Form(...), note: str = Form(""), standing: str = Form(""), db: Session = Depends(get_db)):
    def act(s):
        review.save_recap(db, s, body, note, bool(standing))
        return "Recap saved"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/publish")
def publish(request: Request, session_id: int, db: Session = Depends(get_db)):
    def act(s):
        review.publish(db, s)
        return "Published. The table can read it now."

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/events")
def save_event(request: Request, session_id: int, kind: str = Form(...), text: str = Form(...), event_id: str = Form(""), db: Session = Depends(get_db)):
    def act(s):
        review.save_event(db, s, int(event_id) if event_id else None, kind, text)
        return "Saved"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/events/{event_id}/delete")
def delete_event(request: Request, session_id: int, event_id: int, db: Session = Depends(get_db)):
    def act(s):
        review.delete_event(db, s, event_id)
        return "Deleted"

    return _act(request, db, session_id, act)


def _proposal_action(request: Request, db: Session, proposal_id: int, fn: Callable[[Proposal], str]):
    p = db.get(Proposal, proposal_id)
    if p is None:
        return RedirectResponse("/admin/sessions", status_code=303)
    return _act(request, db, p.session_id, lambda s: fn(p))


@router.post("/proposals/{proposal_id}/accept")
def accept(request: Request, proposal_id: int, summary: str = Form(""), db: Session = Depends(get_db)):
    def fn(p):
        review.accept_proposal(db, p, summary or None)
        return "Accepted"

    return _proposal_action(request, db, proposal_id, fn)


@router.post("/proposals/{proposal_id}/reject")
def reject(request: Request, proposal_id: int, db: Session = Depends(get_db)):
    def fn(p):
        review.reject_proposal(db, p)
        return "Rejected"

    return _proposal_action(request, db, proposal_id, fn)


@router.post("/proposals/{proposal_id}/undo")
def undo(request: Request, proposal_id: int, db: Session = Depends(get_db)):
    def fn(p):
        review.undo_proposal(db, p)
        return "Undone"

    return _proposal_action(request, db, proposal_id, fn)


@router.post("/proposals/{proposal_id}/edit")
def edit_accepted(request: Request, proposal_id: int, summary: str = Form(...), db: Session = Depends(get_db)):
    def fn(p):
        review.edit_accepted_proposal(db, p, summary)
        return "Updated"

    return _proposal_action(request, db, proposal_id, fn)


# --- Add Session (written account + conversation with Claude) -------------------


@router.get("/sessions/new")
def new_session_form(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    sessions = timeline(db, campaign.id) if campaign else []
    return templates.TemplateResponse(
        request, "admin_session_new.html", {"sessions": [(x, session_label(x)) for x in sessions], "error": request.session.pop("toast", None)}
    )


@router.post("/sessions/new")
def create_session(
    request: Request,
    played_on: str = Form(...),
    number: str = Form(""),
    title: str = Form(""),
    account: str = Form(...),
    db: Session = Depends(get_db),
):
    user, denied = _guard(request)
    if denied:
        return denied
    from datetime import date as date_type

    from app.models import SessionMessage

    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    try:
        played = date_type.fromisoformat(played_on)
        num = int(number) if number.strip() else None
    except ValueError:
        request.session["toast"] = "Check the date and session number."
        return RedirectResponse("/admin/sessions/new", status_code=303)
    if not account.strip():
        request.session["toast"] = "Write what happened first."
        return RedirectResponse("/admin/sessions/new", status_code=303)
    if num is not None and db.scalar(select(GameSession).where(GameSession.campaign_id == campaign.id, GameSession.number == num)):
        request.session["toast"] = f"Session {num} already exists. Leave the number blank or pick another."
        return RedirectResponse("/admin/sessions/new", status_code=303)
    s = GameSession(campaign_id=campaign.id, played_on=played, number=num, title=title.strip(), source="account")
    db.add(s)
    db.flush()
    db.add(SessionMessage(session_id=s.id, role="reviewer", author=user.get("name") or user["email"], body=account.strip()))
    db.commit()
    return RedirectResponse(f"/admin/sessions/{s.id}?check=1", status_code=303)


def _run_check(db: Session, s: GameSession) -> str:
    from app import conversation

    try:
        conversation.check(db, s)
        return "Claude replied"
    except ExtractionError as e:
        raise review.ReviewError(f"Claude couldn't reply: {e}") from e


@router.post("/sessions/{session_id:int}/check")
def check(request: Request, session_id: int, db: Session = Depends(get_db)):
    return _act(request, db, session_id, lambda s: _run_check(db, s))


@router.post("/sessions/{session_id:int}/messages")
def reply(request: Request, session_id: int, body: str = Form(...), db: Session = Depends(get_db)):
    from app.models import SessionMessage

    def act(s):
        user = request.session.get("user") or {}
        if not body.strip():
            raise review.ReviewError("Write something first.")
        db.add(SessionMessage(session_id=s.id, role="reviewer", author=user.get("name") or user.get("email", ""), body=body.strip()))
        db.commit()
        db.refresh(s)
        return _run_check(db, s)

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/draft-account")
def draft_account(request: Request, session_id: int, db: Session = Depends(get_db)):
    def act(s):
        if not _draft_in_background([s.id]):
            raise review.ReviewError("Claude is busy; try again in a minute.")
        return "Claude is drafting… about a minute"

    return _act(request, db, session_id, act)
