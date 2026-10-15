"""Admin: draft sessions with Claude, review and publish them."""

import threading

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import db as dbmod
from app.admin import _guard
from app.db import get_db
from app.extraction import (
    ExtractionError,
    _order_key,
    extract_session,
    latest_campaign_notes,
    notes_source_for,
    session_label,
    split_notes,
)
from app.models import (
    Campaign,
    Correction,
    Entity,
    EntityAlias,
    EntityKind,
    EventKind,
    ExtractionRun,
    GameSession,
    GlossaryTerm,
    Proposal,
    Recap,
    Status,
    StoryEvent,
)
from app.render import markdown_to_html
from app.templating import templates

router = APIRouter(prefix="/admin")

_busy = threading.Lock()  # one drafting job at a time keeps costs and order predictable


def _sessions(db: Session) -> list[GameSession]:
    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    if not campaign:
        return []
    return sorted(db.scalars(select(GameSession).where(GameSession.campaign_id == campaign.id)), key=_order_key)


def _status(s: GameSession, running: set[int]) -> str:
    if s.id in running:
        return "drafting"
    if any(r.status == Status.PUBLISHED for r in s.recaps):
        latest = s.recaps[-1]
        return "published" if latest.status == Status.PUBLISHED else "edited since publishing"
    return "draft ready" if s.recaps else "no draft"


def _running_ids(db: Session) -> set[int]:
    return set(db.scalars(select(ExtractionRun.session_id).where(ExtractionRun.status == "running")))


def _draft_in_background(session_ids: list[int]) -> bool:
    """Draft sessions one after another from the campaign notes, in a thread."""
    if not _busy.acquire(blocking=False):
        return False

    def work():
        try:
            for sid in session_ids:
                with dbmod.SessionLocal() as db:
                    session = db.get(GameSession, sid)
                    try:
                        source, background, bg_images = notes_source_for(db, session)
                    except ExtractionError as e:
                        db.add(ExtractionRun(session_id=sid, source="notes", status="error", error=str(e)))
                        db.commit()
                        continue
                    extract_session(db, session, source, background=background, background_images=bg_images)
        finally:
            _busy.release()

    threading.Thread(target=work, daemon=True).start()
    return True


@router.get("/sessions")
def sessions_page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    sessions = _sessions(db)
    running = _running_ids(db)
    snap = latest_campaign_notes(db, sessions[0].campaign_id) if sessions else None
    with_notes = set(split_notes(snap.text)[1]) if snap else set()
    spent = db.scalar(select(func.coalesce(func.sum(ExtractionRun.cost_usd), 0.0))) or 0.0
    rows = []
    for s in sessions:
        last_run = db.scalar(select(ExtractionRun).where(ExtractionRun.session_id == s.id).order_by(ExtractionRun.id.desc()))
        rows.append({"s": s, "label": session_label(s), "status": _status(s, running), "has_notes": s.number in with_notes, "last_run": last_run})
    missing = [r["s"].id for r in rows if r["has_notes"] and r["status"] == "no draft"]
    return templates.TemplateResponse(
        request,
        "admin_sessions.html",
        {"user": user, "rows": rows, "missing": missing, "spent": spent, "running": bool(running), "notes_synced": snap is not None, "message": request.session.pop("sessions_message", None)},
    )


@router.post("/sessions/draft")
def draft(request: Request, session_ids: list[int] = Form(...)):
    user, denied = _guard(request)
    if denied:
        return denied
    if not _draft_in_background(session_ids):
        request.session["sessions_message"] = "Claude is already drafting. Try again when it finishes."
    target = f"/admin/sessions/{session_ids[0]}" if len(session_ids) == 1 else "/admin/sessions"
    return RedirectResponse(target, status_code=303)


@router.get("/sessions/{session_id}")
def review_page(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    if s is None:
        return RedirectResponse("/admin/sessions", status_code=303)
    last_run = db.scalar(select(ExtractionRun).where(ExtractionRun.session_id == s.id).order_by(ExtractionRun.id.desc()))
    latest = s.recaps[-1] if s.recaps else None
    proposals = list(db.scalars(select(Proposal).where(Proposal.session_id == s.id, Proposal.status == "pending").order_by(Proposal.id)))
    answers = {
        c.before: c
        for c in db.scalars(select(Correction).where(Correction.session_id == s.id, Correction.kind == "answer"))
    }
    last_done = db.scalar(
        select(ExtractionRun)
        .where(ExtractionRun.session_id == s.id, ExtractionRun.status == "done")
        .order_by(ExtractionRun.id.desc())
    )
    questions = list(last_done.to_check) if last_done else []
    earlier_answers = [c for q, c in answers.items() if q not in questions]
    return templates.TemplateResponse(
        request,
        "admin_review.html",
        {
            "user": user,
            "s": s,
            "label": session_label(s),
            "status": _status(s, _running_ids(db)),
            "last_run": last_run,
            "latest": latest,
            "preview": markdown_to_html(latest.body, lambda n: None) if latest else "",
            "events": s.events,
            "event_kinds": [k.value for k in EventKind],
            "entity_proposals": [p for p in proposals if p.kind == "entity"],
            "glossary_proposals": [p for p in proposals if p.kind == "glossary"],
            "message": request.session.pop("review_message", None),
            "questions": questions,
            "answers": answers,
            "earlier_answers": earlier_answers,
            "can_redraft": s.source == "notes",
        },
    )


@router.post("/sessions/{session_id}/answers")
async def save_answers(request: Request, session_id: int, db: Session = Depends(get_db)):
    """Brett's answers to Claude's questions. Stored as corrections of kind
    "answer"; remembered ones feed every future draft."""
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    form = await request.form()
    saved = 0
    i = 0
    while f"q-{i}" in form:
        question = str(form[f"q-{i}"]).strip()
        answer = str(form.get(f"answer-{i}") or "").strip()
        remember = bool(form.get(f"remember-{i}"))
        existing = db.scalar(
            select(Correction).where(Correction.session_id == s.id, Correction.kind == "answer", Correction.before == question)
        )
        if answer:
            c = existing or Correction(campaign_id=s.campaign_id, session_id=s.id, kind="answer", before=question)
            c.after, c.standing_instruction, c.note = answer, remember, ""
            db.add(c)
            saved += 1
        elif existing:
            db.delete(existing)
        i += 1
    db.commit()
    if form.get("action") == "redraft" and s.source == "notes":
        started = _draft_in_background([s.id])
        request.session["review_message"] = (
            "Answers saved. Claude is redrafting with them…" if started else "Answers saved. Claude is busy; try Redraft in a minute."
        )
    else:
        request.session["review_message"] = f"Saved {saved} answer{'s' if saved != 1 else ''}."
    return RedirectResponse(f"/admin/sessions/{s.id}", status_code=303)


@router.post("/sessions/{session_id}/recap")
def save_recap(
    request: Request,
    session_id: int,
    body: str = Form(...),
    action: str = Form("save"),
    note: str = Form(""),
    standing: str = Form(""),
    db: Session = Depends(get_db),
):
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    body = body.replace("\r\n", "\n").strip()
    latest = s.recaps[-1] if s.recaps else None
    if latest is None or latest.body.strip() != body:
        version = (db.scalar(select(func.max(Recap.version)).where(Recap.session_id == s.id)) or 0) + 1
        latest = Recap(session_id=s.id, version=version, body=body, author="brett", status=Status.DRAFT)
        db.add(latest)
        db.flush()
    ai_draft = next((r for r in reversed(s.recaps) if r.author == "ai"), None)
    if ai_draft and (note.strip() or ai_draft.body.strip() != body):
        existing = db.scalar(
            select(Correction).where(
                Correction.session_id == s.id, Correction.kind == "edit", Correction.before == ai_draft.body
            )
        )
        correction = existing or Correction(campaign_id=s.campaign_id, session_id=s.id, kind="edit", before=ai_draft.body)
        correction.after = body
        if note.strip():  # a later save without a note keeps the earlier note and choice
            correction.note = note.strip()
            correction.standing_instruction = bool(standing)
        db.add(correction)
    if action == "publish":
        for r in s.recaps:
            if r.status == Status.PUBLISHED and r.id != latest.id:
                r.status = Status.DRAFT
        latest.status = Status.PUBLISHED
        for ev in s.events:
            ev.status = Status.PUBLISHED
        request.session["review_message"] = "Published. The table will see this recap."
    else:
        request.session["review_message"] = "Saved."
    db.commit()
    return RedirectResponse(f"/admin/sessions/{s.id}", status_code=303)


@router.post("/sessions/{session_id}/events")
async def save_events(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    form = await request.form()
    for ev in list(s.events):
        if form.get(f"delete-{ev.id}"):
            db.delete(ev)
            continue
        text = (form.get(f"text-{ev.id}") or "").strip()
        if text:
            ev.text = text
        kind = form.get(f"kind-{ev.id}")
        if kind in {k.value for k in EventKind}:
            ev.kind = EventKind(kind)
    new_text = (form.get("new-text") or "").strip()
    if new_text:
        position = max((e.position for e in s.events), default=0) + 1
        db.add(StoryEvent(session_id=s.id, position=position, kind=EventKind(form.get("new-kind") or "event"), text=new_text))
    db.commit()
    request.session["review_message"] = "Events saved."
    return RedirectResponse(f"/admin/sessions/{s.id}#events", status_code=303)


def apply_proposal(db: Session, p: Proposal) -> None:
    session = db.get(GameSession, p.session_id)
    data = p.payload
    if p.kind == "glossary":
        exists = db.scalar(
            select(GlossaryTerm).where(GlossaryTerm.campaign_id == session.campaign_id, GlossaryTerm.term == data["term"])
        )
        if not exists:
            db.add(GlossaryTerm(campaign_id=session.campaign_id, term=data["term"], description=data.get("description", ""), misheard_as=data.get("misheard_as", [])))
        return
    entity = db.get(Entity, data["entity_id"]) if data.get("entity_id") else None
    if entity is None:
        entity = Entity(campaign_id=session.campaign_id, kind=EntityKind(data["kind"]), name=data["name"])
        db.add(entity)
    entity.summary = data["summary"]
    if data.get("quest_open") is not None:
        entity.quest_open = data["quest_open"]
    have = {a.alias.casefold() for a in entity.aliases}
    for alias in data.get("new_aliases", []):
        if alias.casefold() not in have and alias.casefold() != entity.name.casefold():
            entity.aliases.append(EntityAlias(alias=alias))
    entity.status = Status.PUBLISHED


@router.post("/proposals/{proposal_id}")
def decide_proposal(request: Request, proposal_id: int, decision: str = Form(...), summary: str = Form(""), db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    p = db.get(Proposal, proposal_id)
    if p is None or p.status != "pending":
        return RedirectResponse("/admin/sessions", status_code=303)
    if decision == "accept":
        if p.kind == "entity" and summary.strip():
            p.payload = {**p.payload, "summary": summary.strip()}
        apply_proposal(db, p)
        p.status = "accepted"
    else:
        p.status = "rejected"
    db.commit()
    return RedirectResponse(f"/admin/sessions/{p.session_id}#proposals", status_code=303)
