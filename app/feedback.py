"""Feedback for Claude (Brett, 2026-11-03; docs/mockups/feedback-queue/): a note from any askdnd page, kept in a queue
until Brett says "review the feedback", so nothing small goes unrecorded and nothing interrupts the work in progress.

- **Sending** (app.js "feedback for Claude", `_feedback_window.html`): `\\` on any page, for admins and the accounts
  switched on for it on Manage › Accounts (Brett's test accounts: `User.feedback`, `access.sends_feedback`); admins also
  have the account menu's item (More on a phone), a test account three taps on the askdnd logo, so its menus stay a
  player's. The page sends the note, where it was pointed at, its picture as the window opened, a pasted screenshot,
  the page as drawn and where, when, the screen, the browser and the extension's version (`context`). While an admin
  views as someone (app/view_as.py), the note is still theirs, saying whom they were viewing as.
- **The queue** (admins: Manage › askdnd › Feedback): new → question (Claude asked, in `thread`; Brett answers under
  it, which makes it new again) → planned → done (with the PR that fixed it), or deleted.
- **Your notes › About askdnd** (app/your_notes.py; Brett, Nov 7: a feedback workflow for the players who send it):
  each sender's own notes, where each stands in their words (`SENDER_SAYS`), the replies meant for them (thread
  entries with `"to": "sender"`, from an admin on the queue or from Claude with `feedback.py tell`), and Add to it,
  which goes back to an admin first (a player's words reach Claude only once approved).
- **Claude** reads and updates it with its own key (`config.FEEDBACK_KEY`, header X-Feedback-Key) through `/api/feedback`
  (scripts/feedback.py pulls it into private/feedback/, never committed), since it can't sign in to beta.

Kept like the rest of askdnd: in its database and file storage, admins only, never in git or Sentry (a note holds the
page as its sender saw it).
"""

import base64
import json
import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, config, files, picks, view_as, web
from app.auth import current_user, is_admin
from app.db import get_db
from app.models import Feedback
from app.templating import templates

router = APIRouter()
# "review": a note from someone at the table (not an admin) waits for an admin to approve it before Claude sees it
# (Brett, Nov 6); approved, it's "new". Claude's queue (OPEN, /api/feedback) never holds a note waiting for approval.
STATUSES = ("review", "new", "question", "planned", "done", "deleted")
LABELS = {"review": "Waiting for you", "new": "New", "question": "Question for you", "planned": "Planned", "done": "Done", "deleted": "Deleted"}
OPEN = ("new", "question", "planned")
MAX_TEXT, MAX_HTML, MAX_CONTEXT = 4000, 3_000_000, 50_000
IMAGE = re.compile(r"^data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)$")
BACK = "/manage/feedback"


# ------------------------------------------------------------------ who sends


def _real(request: Request) -> dict | None:
    """The person really signed in (an admin viewing as someone is still themself here)."""
    real = request.session.get("real_user")
    return real if real and access.level(real.get("email")) else current_user(request)


def can_send(request: Request) -> bool:
    """`\\` sends a note: admins, and accounts switched on for it (the page's body carries it, app.js)."""
    user = _real(request)
    return bool(user and access.sends_feedback(user.get("email")))


def shows_menu(request: Request) -> bool:
    """The account menu's item, and More's on a phone: admins only, as the page is seen (viewing as a player, a
    player's menus)."""
    return is_admin(current_user(request))


templates.env.globals["feedback_send"] = can_send
templates.env.globals["feedback_menu"] = shows_menu


def _image(value) -> tuple[bytes, str] | None:
    m = IMAGE.match(value) if isinstance(value, str) else None
    if not m:
        return None
    try:
        return base64.b64decode(m.group(2), validate=True), m.group(1)
    except ValueError:
        return None


def waiting(db: Session) -> int:
    """Notes with Claude, not yet taken up."""
    return db.scalar(select(func.count()).select_from(Feedback).where(Feedback.status == "new")) or 0


def for_you(db: Session) -> int:
    """Notes waiting for an admin: the table's to approve, and Claude's questions."""
    return db.scalar(select(func.count()).select_from(Feedback).where(Feedback.status.in_(("review", "question")))) or 0


@router.post("/feedback")
def send(request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    """A note for Claude, with what the page was at that moment."""
    user = _real(request)
    if not user or not access.sends_feedback(user.get("email")):
        raise HTTPException(404)
    body = body if isinstance(body, dict) else {}
    text = str(body.get("text") or "").strip()[:MAX_TEXT]
    if not text:
        raise HTTPException(400, "Say what it's about first.")
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    if len(json.dumps(context)) > MAX_CONTEXT:
        context = {"left_out": "The page's details were too long to keep."}
    campaign = web.campaign(db)
    email = user["email"].lower()
    role = access.role(email, campaign.id if campaign else None)
    sender = f"{user.get('name') or email} ({'admin' if access.level(email) == access.ADMIN else role or 'member'})"
    viewing = view_as.viewing(request.session)
    context |= {"signed_in_as": sender, "server_at": datetime.now(UTC).isoformat(),
                **({"viewing_as": viewing.get("name") or viewing["email"]} if viewing else {})}
    keys = {}
    for name in ("shot", "pasted"):
        img = _image(body.get(name))
        if img and campaign:
            try:
                keys[name] = files.put(db, campaign.id, *img)
            except (files.FileError, files.StorageNotReady) as e:
                context[f"{name}_left_out"] = str(e)
    me = picks.user_row(db, user)
    admin = access.level(email) == access.ADMIN
    fb = Feedback(user_id=me.id if me else None, sender=sender[:300], text=text, url=str(body.get("url") or "")[:1000],
                  status="new" if admin else "review",  # (the table's notes wait for an admin's approval)
                  context=context, html=str(body.get("html") or "")[:MAX_HTML], shot_key=keys.get("shot"), pasted_key=keys.get("pasted"))
    db.add(fb)
    db.commit()
    return JSONResponse({"ok": True, "id": fb.id, "waiting": waiting(db), "review": not admin})


# ------------------------------------------------------------------ the queue (admins)


def _item(fb: Feedback, html: bool = False) -> dict:
    out = {"id": fb.id, "at": fb.created_at.isoformat() if fb.created_at else "", "sender": fb.sender, "text": fb.text,
           "status": fb.status, "url": fb.url, "context": fb.context or {}, "thread": fb.thread or [], "pr": fb.pr,
           "shots": [n for n, k in (("shot", fb.shot_key), ("pasted", fb.pasted_key)) if k], "html_size": len(fb.html or "")}
    return out | ({"html": fb.html} if html else {})


@router.get("/manage/feedback")
def queue(request: Request, tab: str = "", open: int = 0, db: Session = Depends(get_db)):  # noqa: A002 (the address's word)
    """Manage › askdnd › Feedback: every note, by where it stands."""
    _, denied = web.require(request, is_admin, "Feedback is for admins.")
    if denied:
        return denied
    counts = dict(db.execute(select(Feedback.status, func.count()).group_by(Feedback.status)).all())
    tab = tab if tab in ("review", *OPEN, "done", "all") else ("review" if counts.get("review") else "new")
    q = select(Feedback).order_by(Feedback.id.desc())
    q = q.where(Feedback.status != "deleted") if tab == "all" else q.where(Feedback.status == tab)
    return templates.TemplateResponse(request, "manage_feedback.html", {
        "items": list(db.scalars(q.limit(200))), "tab": tab, "open": open, "counts": counts, "labels": LABELS,
        "tabs": [(t, LABELS.get(t, "All"), counts.get(t, 0) if t != "all" else None) for t in ("review", *OPEN, "done", "all")
                 if t != "review" or counts.get("review") or tab == "review"],
        "toast": request.session.pop("toast", None)})


@router.post("/manage/feedback/{feedback_id:int}")
def change(request: Request, feedback_id: int, to: str = Form(...), answer: str = Form(""), db: Session = Depends(get_db)):
    """Answer Claude's question, or add to a note any time (feedback 18, Brett, Nov 5: something forgotten): it's new
    again for Claude, unless it's planned. Or move a note: planned, done, back to new, deleted. A note from the table
    waiting for approval: Approve sends it to Claude (new), Delete drops it; adding to it approves it too."""
    _, denied = web.require(request, is_admin, "Feedback is for admins.")
    if denied:
        return denied
    fb = db.get(Feedback, feedback_id) or _missing()
    if to == "answer":
        if not answer.strip():
            raise HTTPException(400, "Write your answer first.")
        asked, approving = fb.status == "question", fb.status == "review"
        fb.thread = [*(fb.thread or []), {"who": "you", "text": answer.strip()[:MAX_TEXT], "at": datetime.now(UTC).isoformat()}]
        if fb.status != "planned":
            fb.status = "new"
        said = ("Answered: it's back with Claude" if asked else "Added and approved: it's with Claude" if approving
                else "Added to the note" + ("" if fb.status == "planned" else ": it's back with Claude"))
    elif to == "tell":  # a reply its sender sees on Your notes (and hears about once)
        if not answer.strip():
            raise HTTPException(400, "Write your reply first.")
        fb.thread = [*(fb.thread or []), {"who": "you", "to": "sender", "text": answer.strip()[:MAX_TEXT], "at": datetime.now(UTC).isoformat()}]
        said = "Sent to " + (fb.sender.split(" (")[0] or "its sender")
    elif to in ("new", "planned", "done", "deleted"):
        approved = fb.status == "review" and to == "new"
        fb.status, said = to, {"new": "Approved: it's with Claude" if approved else "Back to new", "planned": "Planned", "done": "Done",
                               "deleted": "Deleted"}[to]
    else:
        raise HTTPException(400)
    db.commit()
    request.session["toast"] = said
    return RedirectResponse(f"{BACK}?tab={request.query_params.get('tab', '')}", status_code=303)


def _missing():
    raise HTTPException(404)


def _shot(db: Session, feedback_id: int, which: str):
    fb = db.get(Feedback, feedback_id) or _missing()
    key = {"shot": fb.shot_key, "pasted": fb.pasted_key}.get(which) or _missing()
    content_type = next((t for t, (ext, _) in files.TYPES.items() if key.endswith(ext)), "image/png")
    return files.serve(key, content_type, release=db)


@router.get("/manage/feedback/{feedback_id:int}/{which}")
def picture(request: Request, feedback_id: int, which: str, db: Session = Depends(get_db)):
    """A note's picture (`shot`, `pasted`), or the page as drawn (`page`, as text: it never runs here)."""
    _, denied = web.require(request, is_admin, "Feedback is for admins.")
    if denied:
        return denied
    if which == "page":
        fb = db.get(Feedback, feedback_id) or _missing()
        return Response(fb.html or "", media_type="text/plain; charset=utf-8", headers={"X-Content-Type-Options": "nosniff"})
    return _shot(db, feedback_id, which)


# ------------------------------------------------------------------ Claude's side (its key)


def _claude(key: str | None) -> None:
    if not config.FEEDBACK_KEY or not key or not secrets.compare_digest(key, config.FEEDBACK_KEY):
        raise HTTPException(404)


@router.get("/api/feedback")
def api_list(status: str = ",".join(OPEN), x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """The queue for Claude: the notes in these states (default: new, question, planned), without their pages."""
    _claude(x_feedback_key)
    wanted = [s for s in status.split(",") if s in STATUSES] or list(OPEN)
    rows = db.scalars(select(Feedback).where(Feedback.status.in_(wanted)).order_by(Feedback.id))
    return JSONResponse({"items": [_item(fb) for fb in rows]}, headers={"Cache-Control": "no-store"})


@router.get("/api/feedback/{feedback_id:int}")
def api_one(feedback_id: int, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    _claude(x_feedback_key)
    return JSONResponse(_item(db.get(Feedback, feedback_id) or _missing(), html=True), headers={"Cache-Control": "no-store"})


@router.get("/api/feedback/{feedback_id:int}/{which}")
def api_picture(feedback_id: int, which: str, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    _claude(x_feedback_key)
    return _shot(db, feedback_id, which)


@router.post("/api/feedback/{feedback_id:int}")
def api_change(feedback_id: int, body=web.JsonBody, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude moves a note on: a question for Brett (`note`, which makes it a question unless `status` says else), a
    status, the PR that fixed it."""
    _claude(x_feedback_key)
    body = body if isinstance(body, dict) else {}
    fb = db.get(Feedback, feedback_id) or _missing()
    tell = str(body.get("tell") or "").strip()[:MAX_TEXT]
    if tell:  # (a reply its sender sees: `feedback.py tell`)
        fb.thread = [*(fb.thread or []), {"who": "claude", "to": "sender", "text": tell, "at": datetime.now(UTC).isoformat()}]
    note = str(body.get("note") or "").strip()[:MAX_TEXT]
    if note:
        fb.thread = [*(fb.thread or []), {"who": "claude", "text": note, "at": datetime.now(UTC).isoformat()}]
    status = body.get("status") or ("question" if note else None)
    if status:
        if status not in STATUSES:
            raise HTTPException(400, f"A status is one of {', '.join(STATUSES)}.")
        fb.status = status
    if body.get("pr"):
        fb.pr = str(body["pr"])[:300]
    db.commit()
    return JSONResponse(_item(fb))


# ------------------------------------------------------------------ a sender's own notes (Your notes › About askdnd, app/your_notes.py)

SENDER_SAYS = {"review": ("Waiting for an admin", "An admin reads it first, then sends it to Claude."),
               "new": ("With Claude", "Claude has it and will look at it with the next batch."),
               "question": ("With Claude", "Claude has it and will look at it with the next batch."),
               "planned": ("Planned", "Claude is going to fix this."),
               "done": ("Fixed", "It's fixed on askdnd."),
               "deleted": ("Closed", "Not something askdnd will change for now.")}


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def marker(fb: Feedback) -> str:
    """Where a note stands for its sender: its status and how many replies to them (what `told` remembers)."""
    to_them = sum(1 for m in fb.thread or [] if m.get("to") == "sender")
    return f"{'new' if fb.status == 'question' else fb.status}:{to_them}"


def _mine(db: Session, request: Request) -> tuple[dict | None, list[Feedback]]:
    user = _real(request)
    me = picks.user_row(db, user) if user else None
    if me is None:
        return user, []
    return user, list(db.scalars(select(Feedback).where(Feedback.user_id == me.id).order_by(Feedback.id.desc()).limit(200)))


def for_sender(fb: Feedback) -> dict:
    """A note as its sender sees it: never the admin's or Claude's notes to each other, nor the page as drawn."""
    label, says = SENDER_SAYS.get(fb.status, ("", ""))
    shown = [{"who": "You" if m.get("who") == "sender" else "Claude" if m.get("who") == "claude" else "An admin",
              "mine": m.get("who") == "sender", "text": m.get("text", ""), "at": m.get("at", "")}
             for m in fb.thread or [] if m.get("who") == "sender" or m.get("to") == "sender"]
    return {"id": fb.id, "text": fb.text, "status": fb.status, "label": label, "says": says, "page": (fb.context or {}).get("page") or fb.url,
            "url": fb.url, "at": fb.created_at, "thread": shown, "can_add": fb.status != "deleted"}
