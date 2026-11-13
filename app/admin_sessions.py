"""Manage › Sessions: the campaign's sessions (drafting, review, publishing) and each session's review page.

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

from app import access, config, narration, review, session_story, web
from app import db as dbmod
from app.admin import _reviewer_guard as _guard
from app.auth import current_user, is_admin
from app.db import get_db
from app.extraction import (
    ExtractionError,
    Source,
    extract_session,
    latest_campaign_notes,
    notes_source_for,
    revise_suggestions,
    session_label,
    split_notes,
    timeline,
)
from app.linking import entity_linker
from app.models import NON_DRAFTING_SOURCES, Campaign, EntityKind, ExtractionRun, GameSession, Proposal
from app.render import markdown_to_html
from app.suggestions import waiting_count
from app.templating import templates

router = APIRouter(prefix="/manage")  # under the campaign: /c/<campaign>/manage/sessions/…

_busy = threading.Lock()  # one drafting job at a time keeps costs and order predictable


_starting: set[int] = set()  # sessions whose draft was started here but whose run isn't written yet (the page redraws first)


def _running_ids(db: Session) -> set[int]:
    """Sessions with a draft in progress (conversation checks and entity runs don't count)."""
    return set(
        db.scalars(
            select(ExtractionRun.session_id).where(ExtractionRun.status == "running", ExtractionRun.source.notin_(NON_DRAFTING_SOURCES))
        )
    ) | _starting


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


def busy() -> bool:
    return _busy.locked()


def read_transcript_in_background(session_id: int, text: str) -> bool:
    """A transcript's first read (Session Story, Brett Nov 7): Claude's questions and suggested World updates. The
    recap waits for Draft the recap, once they're settled."""
    return _in_background(session_id, lambda db, s: extract_session(db, s, Source("transcript", text), step="ask"))


def revise_in_background(session_id: int) -> bool:
    """Put the answers into the waiting suggestions (Brett, Nov 9): no transcript, cents, under a minute."""
    return _in_background(session_id, lambda db, s: revise_suggestions(db, s))


def revise_when_settled(db: Session, s: GameSession) -> str:
    """Once the last of Claude's questions is settled, answers given since the suggestions were written go into them by
    themselves. Call after the change is committed; says so, else nothing."""
    if s.source != "transcript" or review.questions_left(db, s) or not review.answers_since_suggestions(db, s):
        return ""
    if not db.scalar(select(func.count()).select_from(Proposal).where(Proposal.session_id == s.id, Proposal.status == "pending")):
        return ""
    return " · Claude is putting your answers into the suggestions" if revise_in_background(s.id) else ""


def draft_recap_in_background(session_id: int, update: bool = False) -> bool:
    """Draft the recap (and the full tale, key moments and awards) from the kept transcript, with the answers and the
    World as they are now; `update`: change the current draft instead of writing a new one."""
    def tell(db, s):
        words = session_story.text(s)
        if words is None:
            db.add(ExtractionRun(session_id=s.id, source="recap", status="error",
                                 error="askdnd doesn't have this session's transcript. Send it again from the Processor."))
            db.commit()
            return
        extract_session(db, s, Source("transcript", words), step="tell", update=update)

    return _in_background(session_id, tell)


def _in_background(session_id: int, work_on) -> bool:
    if not _busy.acquire(blocking=False):
        return False
    _starting.add(session_id)

    def work():
        try:
            with dbmod.SessionLocal() as db:
                work_on(db, db.get(GameSession, session_id))
        finally:
            _starting.discard(session_id)
            _busy.release()

    threading.Thread(target=work, daemon=True).start()
    return True


# --- Review list -------------------------------------------------------------


@router.get("/sessions")
def sessions_page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    campaign = web.campaign(db)
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
            "waiting": waiting_count(db),
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
    target = f"{web.base()}/manage/sessions/{session_ids[0]}" if len(session_ids) == 1 else f"{web.base()}/manage/sessions"
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


STEPS = ("questions", "suggestions", "recap", "tale", "moments", "awards", "numbers")


def _tab(request: Request) -> str:
    """The review step that's open: the address's ?tab=, or (an HTMX action or the page polling while Claude drafts)
    the one in the address of the page that asked, so a change keeps you where you were."""
    from urllib.parse import parse_qs, urlparse

    tab = request.query_params.get("tab") or (parse_qs(urlparse(request.headers.get("HX-Current-URL", "")).query).get("tab") or [""])[0]
    return tab if tab in STEPS else ""


def _steps(ctx: dict, s: GameSession, tab: str) -> tuple[list[dict], str]:
    """The review as a wizard (Brett, Nov 7): a tab per step, in the order they're done, each saying what's left; and the
    step to open (the one asked for, else the first with something left)."""
    latest = ctx["latest"]
    steps = [
        {"key": "questions", "label": "Questions", "left": len(ctx["open_questions"])},
        {"key": "suggestions", "label": "Suggestions", "left": len(ctx["open_proposals"])},
        {"key": "recap", "label": "Recap" if latest or s.source != "transcript" else "Draft the recap", "left": 0 if latest else 1},
    ]
    if latest:
        steps += [{"key": "tale", "label": "Full tale", "left": 0, "count": len(ctx["chapters"])}] if ctx["chapters"] else []
        steps += [{"key": "moments", "label": "Key moments", "left": 0, "count": len(ctx["events"])},
                  {"key": "awards", "label": "Awards", "left": 0, "count": len(ctx["awards"])},
                  {"key": "numbers", "label": "Numbers", "left": len(ctx["talked"]["unmatched"])}]
    keys = [x["key"] for x in steps]
    open_ = tab if tab in keys else next((x["key"] for x in steps[:3] if x["left"]), "recap")
    for i, x in enumerate(steps):
        x["n"], x["next"] = i + 1, steps[i + 1] if i + 1 < len(steps) else None
    return steps, open_


def _body_context(db: Session, s: GameSession, tab: str = "") -> dict:
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
    campaign = db.get(Campaign, s.campaign_id)
    rolled = session_story.dice(db, s)
    ctx.update(
        chapters=session_story.chapters(ctx["latest"]),
        awards=session_story.awards(db, s, ctx["latest"], rolled),
        rolled=rolled,
        night=session_story.night_numbers(db, rolled),
        talked=session_story.who_talked(db, s, campaign),
        people=sorted(session_story.table(db, campaign).values(), key=lambda p: (not p["dm"], p["name"].casefold())),
        mix=session_story.mix(s, ctx["latest"]),
        chapter_kinds=session_story.KINDS,
        told=review.last_told(db, s),
    )
    if ctx["latest"]:  # how long Listen would play it (Brett, Nov 9): the recorded length once it's been read, else an estimate
        ctx["listen"] = narration.length(s, ctx["latest"], campaign.name)
        ctx["listen_full"] = narration.length(s, ctx["latest"], campaign.name, "full") if ctx["latest"].tale else None
    session_story.pictured(db, ctx["awards"], ctx["talked"]["rows"])
    from app import drawing, pictures

    ctx["new_pictures"] = pictures.urls(db, {e.id for e in ctx["new_entries"]})
    ctx["can_draw"] = bool(ctx["new_entries"]) and not drawing.why_not(db, campaign)
    ctx["entity_kinds"] = [k.value for k in EntityKind if k.value != "pc"]
    ctx["steps"], ctx["tab"] = _steps(ctx, s, tab)
    ctx["step"] = {x["key"]: x for x in ctx["steps"]}
    return ctx


@router.get("/sessions/{session_id:int}")
def review_page(request: Request, session_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    if s is None:
        return RedirectResponse(f"{web.base()}/manage/sessions", status_code=303)
    here = web.campaign(db)
    if here is not None and s.campaign_id != here.id:  # a session of another campaign: open it at that campaign's address
        theirs = next((c for c in access.campaigns_for(user["email"]) if c["id"] == s.campaign_id), None)
        query = request.url.query
        return RedirectResponse(f"{web.base(theirs)}/manage/sessions/{s.id}" + (f"?{query}" if query else "") if theirs
                                else f"{web.base()}/manage/sessions", status_code=303)
    return templates.TemplateResponse(
        request,
        "admin_review.html",
        {**_body_context(db, s, _tab(request)), "toast": request.session.pop("toast", None), "auto_check": request.query_params.get("check") == "1"},
    )


@router.get("/sessions/{session_id:int}/body")
def review_body(request: Request, session_id: int, db: Session = Depends(get_db)):
    """Partial for polling while Claude drafts."""
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    if s is None:
        return RedirectResponse(f"{web.base()}/manage/sessions", status_code=303)
    return templates.TemplateResponse(request, "_review_body.html", _body_context(db, s, _tab(request)))


def _act(request: Request, db: Session, session_id: int, action: Callable[[GameSession], str]):
    """Run a review action, commit, and answer with the updated review body."""
    user, denied = _guard(request)
    if denied:
        return denied
    s = db.get(GameSession, session_id)
    if s is None:
        return RedirectResponse(f"{web.base()}/manage/sessions", status_code=303)
    try:
        message = action(s)
        db.commit()
    except review.ReviewError as e:
        db.rollback()
        message = web.notice(str(e), "warn")
    db.expire_all()
    s = db.get(GameSession, session_id)
    if request.headers.get("HX-Request"):
        response = templates.TemplateResponse(request, "_review_body.html", _body_context(db, s, _tab(request)))
        response.headers["HX-Trigger"] = json.dumps({"toast": message})
        return response
    request.session["toast"] = message
    return RedirectResponse(f"{web.base()}/manage/sessions/{session_id}", status_code=303)


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
        db.commit()
        said = f"Saved {on_behalf_of}'s answer" if on_behalf_of.strip() else "Answer saved"
        return said + revise_when_settled(db, s)

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/questions/ask")
def ask(request: Request, session_id: int, q: str = Form(...), person: str = Form(""), note: str = Form(""), db: Session = Depends(get_db)):
    def act(s):
        user = request.session.get("user") or {}
        review.ask_question(db, s, q, person, note, asked_by=user.get("name") or user.get("email", ""))
        db.commit()
        said = f"Waiting on {' '.join(person.split())}"
        return said + revise_when_settled(db, s)

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/questions/skip")
def skip(request: Request, session_id: int, q: str = Form(...), db: Session = Depends(get_db)):
    def act(s):
        review.skip_question(db, s, q)
        db.commit()
        said = "Skipped"
        return said + revise_when_settled(db, s)

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/questions/reopen")
def reopen(request: Request, session_id: int, q: str = Form(...), db: Session = Depends(get_db)):
    def act(s):
        review.reopen_question(db, s, q)
        return "Question reopened"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/suggestions/update")
def update_suggestions(request: Request, session_id: int, db: Session = Depends(get_db)):
    def act(s):
        if not review.answers_since_suggestions(db, s):
            raise review.ReviewError("No new answers since these suggestions were written.")
        if not revise_in_background(s.id):
            raise review.ReviewError("Claude is busy; try again in a minute.")
        return "Claude is putting your answers into the suggestions… under a minute"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/redraft")
def redraft(request: Request, session_id: int, fresh: str = Form(""), db: Session = Depends(get_db)):
    def act(s):
        if s.source == "transcript":
            if not s.transcript_key:
                raise review.ReviewError("askdnd doesn't have this session's transcript. Send it again from the Processor.")
            update = bool(s.recaps) and not fresh  # (Update the draft by default; Start over writes a new one, Nov 9)
            if not draft_recap_in_background(s.id, update=update):
                raise review.ReviewError("Claude is busy; try again in a minute.")
            return "Claude is updating the draft… a few minutes" if update else "Claude is drafting the recap… a few minutes"
        if s.source == "manual":
            raise review.ReviewError("You wrote this one by hand; edit the recap directly.")
        if not _draft_in_background([s.id]):
            raise review.ReviewError("Claude is busy; try again in a minute.")
        return "Claude is redrafting… about a minute"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/recap")
def save_recap(request: Request, session_id: int, body: str = Form(...), note: str = Form(""), standing: str = Form(""), db: Session = Depends(get_db)):
    def act(s):
        review.save_recap(db, s, body, note, bool(standing), by=web.person_name(current_user(request)))
        return "Recap saved"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/tale/{index:int}")
def save_chapter(request: Request, session_id: int, index: int, title: str = Form(""), text: str = Form(...), kind: str = Form(""),
                 db: Session = Depends(get_db)):
    def act(s):
        review.save_chapter(db, s, index, title, text, kind, by=web.person_name(current_user(request)))
        return "Chapter saved"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/awards/{index:int}")
def save_award(request: Request, session_id: int, index: int, character: str = Form(...), why: str = Form(""), quote: str = Form(""),
               db: Session = Depends(get_db)):
    def act(s):
        review.save_award(db, s, index, character, why, quote, by=web.person_name(current_user(request)))
        return "Award saved"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/awards/{index:int}/pick")
def pick_nominee(request: Request, session_id: int, index: int, nominee: int = Form(...), db: Session = Depends(get_db)):
    def act(s):
        return f"Goes to {review.pick_nominee(db, s, index, nominee, by=web.person_name(current_user(request)))}"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/awards/{index:int}/drop")
def drop_award(request: Request, session_id: int, index: int, db: Session = Depends(get_db)):
    def act(s):
        return f"{review.drop_award(db, s, index, by=web.person_name(current_user(request)))} taken away"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/speakers")
def match_speaker(request: Request, session_id: int, name: str = Form(...), user_id: int = Form(...), db: Session = Depends(get_db)):
    """Who a speaker name in the recording is (0: no one at the table), for this session and every later one."""
    def act(s):
        campaign = db.get(Campaign, s.campaign_id)
        if user_id and user_id not in session_story.table(db, campaign):
            raise review.ReviewError("They aren't at this table.")
        if name not in ((s.talk or {}).get("speakers") or {}):
            raise review.ReviewError("That name isn't in this recording.")
        session_story.set_speaker(campaign, name, user_id)
        return "Matched" if user_id else "Left out"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/start")
def recording_start(request: Request, session_id: int, start: str = Form(""), db: Session = Depends(get_db)):
    """When the recording began, for a session sent before the Processor asked (Brett, Nov 10): its numbers then count
    only the session's own rolls."""
    def act(s):
        try:
            session_story.set_start(s, start)
        except ValueError as e:
            raise review.ReviewError(str(e)) from e
        return f"The recording started at {start}" if start.strip() else "No start time: the numbers count that evening"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/transcript/forget")
def forget_transcript(request: Request, session_id: int, db: Session = Depends(get_db)):
    """An admin lets a session's kept transcript go (the nightly sweep deletes it once no backup needs it)."""
    def act(s):
        if not is_admin(current_user(request)):
            raise review.ReviewError("Only an admin can let a transcript go.")
        session_story.forget(s)
        return "The transcript is gone from askdnd. Send it again from the Processor to redraft."

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/recap/keep-mine")
def keep_mine(request: Request, session_id: int, db: Session = Depends(get_db)):
    def act(s):
        mine = review.keep_person_version(db, s)
        return f"Back to {mine.author_name or 'your'}'s version" if mine.author_name else "Back to your version"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/publish")
def publish(request: Request, session_id: int, db: Session = Depends(get_db)):
    def act(s):
        review.publish(db, s)
        nxt = _next_to_draft(db, s)
        if nxt is not None and not config.AUTO_DRAFT:
            return f"Published. Automatic drafting is off here, so draft {session_label(nxt)} from Recaps when you want it."
        if nxt is not None and _draft_in_background([nxt.id]):
            return f"Published. Claude is drafting {session_label(nxt)} next, so it's ready when you are."
        return "Published. The table can read it now."

    return _act(request, db, session_id, act)


def _next_to_draft(db: Session, s: GameSession) -> GameSession | None:
    """The backlog goes one at a time (Brett, 2026-10-22): after publishing, the next session in story order that
    has notes and no draft yet. Drafting each after the one before is reviewed means it knows the people and
    places accepted there, and doesn't suggest them again."""
    order = timeline(db, s.campaign_id)
    after = order[order.index(s) + 1:] if s in order else []
    return next((x for x in after if x.source == "notes" and review.review_status(x, False) == "no draft"), None)


@router.post("/sessions/{session_id:int}/events")
def save_event(request: Request, session_id: int, kind: str = Form(...), text: str = Form(...), event_id: str = Form(""), db: Session = Depends(get_db)):
    def act(s):
        review.save_event(db, s, int(event_id) if event_id else None, kind, text)
        return "Saved"

    return _act(request, db, session_id, act)


@router.post("/sessions/{session_id:int}/events/{event_id:int}/major")
def major_event(request: Request, session_id: int, event_id: int, db: Session = Depends(get_db)):
    """★ on a key moment: Story shows the major ones first (feedback 40, Nov 7)."""
    def act(s):
        return "Marked major: Story shows it first" if review.toggle_major(db, s, event_id) else "Not major: it's behind Show the other"

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
        return RedirectResponse(f"{web.base()}/manage/sessions", status_code=303)
    return _act(request, db, p.session_id, lambda s: fn(p))


@router.post("/proposals/{proposal_id}/accept")
def accept(request: Request, proposal_id: int, summary: str = Form(""), name: str = Form(""), kind: str = Form(""),
           race: str | None = Form(None), class_: str | None = Form(None, alias="class"), db: Session = Depends(get_db)):
    def fn(p):
        review.accept_proposal(db, p, summary or None, by=web.person_name(current_user(request)), name=name, kind=kind, race=race, class_=class_)
        if p.kind == "entity" and not p.payload.get("entity_id"):
            return f"Added {p.payload['name']}: give them a picture under New in the World"
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
        review.edit_accepted_proposal(db, p, summary, by=web.person_name(current_user(request)))
        return "Updated"

    return _proposal_action(request, db, proposal_id, fn)


# --- Add Session (written account + conversation with Claude) -------------------


@router.get("/sessions/new")
def new_session_form(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    campaign = web.campaign(db)
    sessions = timeline(db, campaign.id) if campaign else []
    error = request.session.pop("toast", None)  # (web.notice: shown on the form, not as a card)
    return templates.TemplateResponse(
        request, "admin_session_new.html",
        {"sessions": [(x, session_label(x)) for x in sessions], "error": error.get("text") if isinstance(error, dict) else error}
    )


@router.post("/sessions/new")
def create_session(
    request: Request,
    played_on: str = Form(...),
    number: str = Form(""),
    title: str = Form(""),
    account: str = Form(...),
    mode: str = Form("ask"),
    db: Session = Depends(get_db),
):
    user, denied = _guard(request)
    if denied:
        return denied
    from datetime import date as date_type

    from app.models import SessionMessage

    campaign = web.campaign(db)
    try:
        played = date_type.fromisoformat(played_on)
        num = int(number) if number.strip() else None
    except ValueError:
        request.session["toast"] = web.notice("Check the date and session number.", "warn")
        return RedirectResponse(f"{web.base()}/manage/sessions/new", status_code=303)
    if not account.strip():
        request.session["toast"] = web.notice("Write what happened first.", "warn")
        return RedirectResponse(f"{web.base()}/manage/sessions/new", status_code=303)
    if num is not None and db.scalar(select(GameSession).where(GameSession.campaign_id == campaign.id, GameSession.number == num)):
        request.session["toast"] = web.notice(f"Session {num} already exists. Leave the number blank or pick another.", "warn")
        return RedirectResponse(f"{web.base()}/manage/sessions/new", status_code=303)
    if mode == "manual":  # the DM's own recap, no Claude (content workflows step 1): review it, add key moments, publish
        s = GameSession(campaign_id=campaign.id, played_on=played, number=num, title=title.strip(), source="manual")
        db.add(s)
        db.flush()
        review.save_recap(db, s, account, by=web.person_name(user))
        db.commit()
        request.session["toast"] = "Saved as the recap. Add key moments if you like, then publish."
        return RedirectResponse(f"{web.base()}/manage/sessions/{s.id}", status_code=303)
    s = GameSession(campaign_id=campaign.id, played_on=played, number=num, title=title.strip(), source="account")
    db.add(s)
    db.flush()
    db.add(SessionMessage(session_id=s.id, role="reviewer", author=user.get("name") or user["email"], body=account.strip()))
    db.commit()
    return RedirectResponse(f"{web.base()}/manage/sessions/{s.id}?check=1", status_code=303)


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
