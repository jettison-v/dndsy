"""Feedback for Claude (Brett, 2026-11-03; docs/mockups/feedback-queue/): a note from any askdnd page, kept in a queue
until Brett says "review the feedback", so nothing small goes unrecorded and nothing interrupts the work in progress.

- **Sending** (app.js "feedback for Claude", `_feedback_window.html`): `\\` on any page, for admins and the accounts
  switched on for it on Manage › Accounts (Brett's test accounts: `User.feedback`, `access.sends_feedback`); admins also
  have the account menu's item (More on a phone), a test account three taps on the askdnd logo, so its menus stay a
  player's. The page sends the note, where it was pointed at, its picture as the window opened, a pasted screenshot,
  the page as drawn and where, when, the screen, the browser and the extension's version (`context`). While an admin
  views as someone (app/view_as.py), the note is still theirs, saying whom they were viewing as.
- **Its kind** (Brett, Nov 16), picked when it's sent, never picked for you: something broken (Claude fixes it in the
  next round), an idea (it goes onto the Roadmap's Ideas from feedback, built only once Brett moves it up) or a question
  (answered in its thread). An admin or Claude can change it, saying why in its thread.
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

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, config, files, picks, view_as, web
from app.auth import current_user, is_admin
from app.db import get_db
from app.models import Feedback, FeedbackPicture, User
from app.templating import templates

router = APIRouter()
# "review": a note from someone at the table (not an admin) waits for an admin to approve it before Claude sees it
# (Brett, Nov 6); approved, it's "new". Claude's queue (OPEN, /api/feedback) never holds a note waiting for approval.
STATUSES = ("review", "new", "question", "planned", "done", "deleted")
LABELS = {"review": "To approve", "new": "With Claude", "question": "Claude asks", "planned": "Planned", "done": "Done", "deleted": "Closed"}  # (the tabs, in the state words: Readers, Rebuilt)
OPEN = ("new", "question", "planned")
# Readers, Rebuilt (Brett's picks, Nov 17, docs/mockups/readers/ Board 3): a note's state as a word and what it means
WORD = {"review": ("To approve", "ask"), "new": ("With Claude", "claude"), "question": ("Claude asks", "ask"), "planned": ("Planned", "ready"),
        "done": ("Done", "passed"), "deleted": ("Closed", "quiet")}
SENTENCE = {"review": "From the table: it reaches Claude once you approve it.", "new": "With Claude: it's in Claude's inbox.",
            "question": "Claude asks you something: answer below.", "planned": "Planned: on the Roadmap or in its area, waiting its turn.",
            "done": "Done.", "deleted": "Closed."}
# What a note is (Brett, Nov 16): how it's said in the window, and its short tag on the queue. A note sent before then
# has "" until it's sorted (`feedback.py kind`).
KINDS = {"broken": ("Something's broken", "Broken", "What's wrong?"), "idea": ("An idea", "Idea", "What would be better?"),
         "question": ("A question", "Question", "What would you like to know?")}  # (in the window, its short tag, its box's ask)
MAX_TEXT, MAX_HTML, MAX_CONTEXT, MAX_TITLE = 4000, 3_000_000, 50_000, 120
MAX_PICS, MAX_PIC_BYTES = 4, 8_000_000  # screenshots added with Add to it, at most, each (feedback 64)
MAX_CHOICES = 4  # answers to tap on Claude's question (Working with Claude, Brett's 5A, Nov 17)
PIC_TYPES = ("image/png", "image/jpeg", "image/webp")
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
templates.env.globals["feedback_kinds"] = KINDS


def _image(value) -> tuple[bytes, str] | None:
    m = IMAGE.match(value) if isinstance(value, str) else None
    if not m:
        return None
    try:
        return base64.b64decode(m.group(2), validate=True), m.group(1)
    except ValueError:
        return None


def add_pictures(db: Session, fb: Feedback, uploads: list[UploadFile] | None) -> list[int]:
    """Screenshots added to a note with Add to it (feedback 64, Nov 16): kept in file storage, each a row of its own
    (so the nightly sweep keeps the file), named by the thread entry they came with. PNG, JPEG or WebP, 8 MB each."""
    ups = [u for u in uploads or [] if u is not None and u.filename]
    if len(ups) > MAX_PICS:
        raise HTTPException(400, f"{MAX_PICS} screenshots at most, at a time.")
    campaign, ids = web.campaign(db), []
    for up in ups:
        if up.content_type not in PIC_TYPES:
            raise HTTPException(400, "A screenshot as PNG, JPEG or WebP, please.")
        data = up.file.read(MAX_PIC_BYTES + 1)
        if len(data) > MAX_PIC_BYTES:
            raise HTTPException(400, "A screenshot is over 8 MB.")
        if campaign is None:
            raise HTTPException(400, "There's no campaign to keep it in.")
        try:
            key = files.put(db, campaign.id, data, up.content_type)
        except (files.FileError, files.StorageNotReady) as e:
            raise HTTPException(400, str(e)) from e
        pic = FeedbackPicture(feedback_id=fb.id, key=key)
        db.add(pic)
        db.flush()
        ids.append(pic.id)
    return ids


def picture_of(db: Session, fb: Feedback, pic_id: int):
    """One of a note's added screenshots, served."""
    pic = db.get(FeedbackPicture, pic_id)
    if pic is None or pic.feedback_id != fb.id:
        raise HTTPException(404)
    content_type = next((t for t, (ext, _) in files.TYPES.items() if pic.key.endswith(ext)), "image/png")
    return files.serve(pic.key, content_type, release=db)


def waiting(db: Session) -> int:
    """Notes with Claude, not yet taken up."""
    return db.scalar(select(func.count()).select_from(Feedback).where(Feedback.status == "new")) or 0


def for_you(db: Session) -> int:
    """Notes waiting for an admin to approve (the table's). Claude's questions are Testing's For you (Brett's 1A, Nov 17:
    one place for what needs you), counted there."""
    return db.scalar(select(func.count()).select_from(Feedback).where(Feedback.status == "review")) or 0


def asks(db: Session) -> list[Feedback]:
    """Notes Claude has asked a question on, waiting for an admin's answer, oldest first."""
    return list(db.scalars(select(Feedback).where(Feedback.status == "question").order_by(Feedback.id)))


def question_of(fb: Feedback) -> dict | None:
    """Claude's latest question on a note: {text, at, ask: {choices: [{label, detail, pic}], mine} or None, n (its place
    in the thread)}, or None when it's asked none."""
    for n in range(len(fb.thread or []) - 1, -1, -1):
        m = fb.thread[n]
        if m.get("who") == "claude" and m.get("to") != "sender" and not m.get("kind"):
            return {"text": m.get("text", ""), "at": m.get("at", ""), "ask": m.get("ask"), "n": n}
    return None


def _asking(db: Session, fb: Feedback, body: dict) -> dict | None:
    """Claude's question as answers to tap (Brett's 5A): `choices` [{label, detail, pic: a data: URL}] (2 to 4) and
    `mine`, the one Claude would pick. A question whose answers are pictures is a design pick (Board 3)."""
    raw = body.get("choices")
    if raw is None:
        return None
    if not isinstance(raw, list) or not 2 <= len(raw) <= MAX_CHOICES or not all(isinstance(c, dict) for c in raw):
        raise HTTPException(400, f"choices: 2 to {MAX_CHOICES}, each {{label, detail, pic}}.")
    out = []
    for c in raw:
        label = " ".join(str(c.get("label") or "").split())[:120]
        if not label:
            raise HTTPException(400, "Each choice needs its label.")
        pic = None
        if c.get("pic"):
            img = _image(c["pic"])
            if img is None or len(img[0]) > MAX_PIC_BYTES:
                raise HTTPException(400, "A choice's picture is a PNG, JPEG or WebP data: URL, 8 MB at most.")
            campaign = web.campaign(db)
            if campaign is None:
                raise HTTPException(400, "There's no campaign to keep it in.")
            try:
                key = files.put(db, campaign.id, *img)
            except (files.FileError, files.StorageNotReady) as e:
                raise HTTPException(400, str(e)) from e
            row = FeedbackPicture(feedback_id=fb.id, key=key)
            db.add(row)
            db.flush()
            pic = row.id
        out.append({"label": label, "detail": " ".join(str(c.get("detail") or "").split())[:300], "pic": pic})
    mine = body.get("mine")
    if mine is not None and (type(mine) is not int or not 0 <= mine < len(out)):
        raise HTTPException(400, "mine: the index of Claude's pick.")
    return {"choices": out, "mine": mine}


@router.post("/feedback")
def send(request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    """A note for Claude, with what the page was at that moment. On staging it goes to prod's queue, marked Staging
    (Brett, Nov 6: one queue, and nothing lost when staging's data is refreshed); kept here only if prod can't be reached."""
    user = _real(request)
    if not user or not access.sends_feedback(user.get("email")):
        raise HTTPException(404)
    body = body if isinstance(body, dict) else {}
    text = str(body.get("text") or "").strip()[:MAX_TEXT]
    if not text:
        raise HTTPException(400, "Say what it's about first.")
    kind = body.get("kind")
    if not isinstance(kind, str) or kind not in KINDS:
        raise HTTPException(400, "Pick what it is first: something broken, an idea or a question.")
    context = body.get("context") if isinstance(body.get("context"), dict) else {}
    if len(json.dumps(context)) > MAX_CONTEXT:
        context = {"left_out": "The page's details were too long to keep."}
    viewing = view_as.viewing(request.session)
    if viewing:
        context |= {"viewing_as": viewing.get("name") or viewing["email"], "viewing_as_email": viewing["email"].lower()}
    note = {"email": user["email"].lower(), "name": user.get("name") or "", "text": text, "kind": kind, "url": str(body.get("url") or "")[:1000],
            "context": context, "html": str(body.get("html") or "")[:MAX_HTML], "shot": body.get("shot"), "pasted": body.get("pasted")}
    # Failed… or + Issue on a check (Testing, 3A and 2A): tied to it; the card stays on the check for the next issue
    check = body.get("check") if type(body.get("check")) is int and is_admin(user) else None
    fail = body.get("fail") is not False  # (+ Issue sends False: it doesn't fail the check)
    if check is not None:
        from app import testing

        note["context"] = {**note["context"], "check": check}
    if config.STAGING:
        sent = to_prod(note)
        if "id" in sent:
            if check is not None and testing.failed(request, db, check, None, prod_note=sent["id"], fail=fail):  # (staging's check, askdnd.ai's note)
                return JSONResponse({"ok": True, "id": sent["id"], "waiting": waiting(db), "review": False, "to_prod": True, "check": check})
            return JSONResponse({"ok": True, "id": sent["id"], "waiting": waiting(db), "review": sent.get("review", True), "to_prod": True})
        note["context"] = {**note["context"], "not_sent_to_prod": sent.get("error", "")[:300]}
    fb = _store(db, note, tell=check is None)
    if check is not None and testing.failed(request, db, check, fb, fail=fail):
        return JSONResponse({"ok": True, "id": fb.id, "waiting": waiting(db), "review": False, "check": check})
    return JSONResponse({"ok": True, "id": fb.id, "waiting": waiting(db), "review": fb.status == "review"})


def _store(db: Session, note: dict, staging: bool = False, tell: bool = True) -> Feedback:
    """Keep a note in this askdnd's queue: who sent it (as what, here), its pictures in file storage, waiting for an
    admin unless an admin sent it."""
    campaign = web.campaign(db)
    email = note["email"]
    role = access.role(email, campaign.id if campaign else None)
    admin = access.level(email) == access.ADMIN
    sender = f"{note.get('name') or email} ({'admin' if admin else role or 'member'})"
    context = dict(note.get("context") or {}) | {"signed_in_as": sender, "server_at": datetime.now(UTC).isoformat(),
                                                **({"staging": True} if staging else {})}
    keys = {}
    for name in ("shot", "pasted"):
        img = _image(note.get(name))
        if img and campaign:
            try:
                keys[name] = files.put(db, campaign.id, *img)
            except (files.FileError, files.StorageNotReady) as e:
                context[f"{name}_left_out"] = str(e)
    me = picks.user_row(db, {"email": email})
    kind = note.get("kind") if isinstance(note.get("kind"), str) and note["kind"] in KINDS else ""  # (staging may run code from before kinds)
    fb = Feedback(user_id=me.id if me else None, sender=sender[:300], text=note["text"][:MAX_TEXT], kind=kind, url=str(note.get("url") or "")[:1000],
                  status="new" if admin else "review",  # (the table's notes wait for an admin's approval)
                  context=context, html=str(note.get("html") or "")[:MAX_HTML], shot_key=keys.get("shot"), pasted_key=keys.get("pasted"))
    fb.seen = fb.told = marker(fb)  # (its sender knows what they just did: no "Sent to Claude" card on their next page; feedback 78)
    db.add(fb)
    if fb.status == "new" and tell:  # (with Claude now; a player's waits for an admin's Approve: `change`; Failed…'s, its check tells)
        db.flush()
        tell_claude(db, fb, "note", "sent")
    db.commit()
    return fb


def tell_claude(db: Session, fb: Feedback, what: str, how: str) -> None:
    """Claude's inbox hears of it (app/for_claude.py): note 96 (broken) from Brett, sent: "…". First names only."""
    from app import for_claude

    who = (fb.sender or "").split(" (")[0].split(" ")[0] or "someone"
    words = ((fb.thread or [{}])[-1].get("text") if what in ("added", "answer") else fb.text) or ""
    for_claude.tell(db, what, f"Note {fb.id}" + (f" ({fb.kind})" if fb.kind else "") + f" from {who}, {how}: " + " ".join(words.split())[:280],
                    feedback_id=fb.id, area_id=fb.area_id)


SEND = None  # tests replace it: (url, payload, key) -> dict


def to_prod(note: dict) -> dict:
    """Staging's note, sent to prod's queue with the feedback key: {"id", "review"}, or {"error"}."""
    import urllib.error
    import urllib.request

    if not config.FEEDBACK_KEY:
        return {"error": "Staging has no FEEDBACK_KEY, so the note stays here."}
    url = f"{config.PROD_URL}/api/feedback/from-staging"
    if SEND is not None:
        return SEND(url, note, config.FEEDBACK_KEY)
    req = urllib.request.Request(url, data=json.dumps(note).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "X-Feedback-Key": config.FEEDBACK_KEY,
                                          "User-Agent": "askdnd-staging/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        return {"error": f"Prod didn't take it ({e})."}


@router.post("/api/feedback/from-staging")
def from_staging(body=web.JsonBody, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A note sent on staging, into this queue marked Staging (its sender as they are here)."""
    _claude(x_feedback_key)
    body = body if isinstance(body, dict) else {}
    if not str(body.get("text") or "").strip() or not str(body.get("email") or "").strip():
        raise HTTPException(400, "A note needs its words and who sent it.")
    fb = _store(db, {**body, "email": str(body["email"]).lower(), "text": str(body["text"]).strip()}, staging=True)
    return JSONResponse({"id": fb.id, "review": fb.status == "review"})


# ------------------------------------------------------------------ the queue (admins)


def _item(fb: Feedback, html: bool = False) -> dict:
    out = {"id": fb.id, "at": fb.created_at.isoformat() if fb.created_at else "", "sender": fb.sender, "text": fb.text,
           "kind": fb.kind or "", "title": fb.title or "", "status": fb.status, "url": fb.url, "context": fb.context or {}, "thread": fb.thread or [], "pr": fb.pr,
           "shots": [n for n, k in (("shot", fb.shot_key), ("pasted", fb.pasted_key)) if k], "html_size": len(fb.html or "")}
    return out | ({"html": fb.html} if html else {})


@router.get("/manage/feedback")
def queue(request: Request, tab: str = "", kind: str = "", open: int = 0, db: Session = Depends(get_db)):
    """Manage › askdnd › Feedback: every note, by where it stands, and by its kind (the chips above the list)."""
    user, denied = web.require(request, is_admin, "Feedback is for admins.")
    if denied:
        return denied
    counts = dict(db.execute(select(Feedback.status, func.count()).group_by(Feedback.status)).all())
    tab = tab if tab in ("review", *OPEN, "done", "all") else ("review" if counts.get("review") else "new")
    q = select(Feedback).order_by(Feedback.id.desc())
    q = q.where(Feedback.status != "deleted") if tab == "all" else q.where(Feedback.status == tab)
    in_tab = dict(db.execute(select(Feedback.kind, func.count()).where(q.whereclause).group_by(Feedback.kind)).all())
    kind = kind if kind in (*KINDS, "none") else ""
    if kind:
        q = q.where(Feedback.kind == ("" if kind == "none" else kind))
    items = list(db.scalars(q.limit(200)))
    me = user["email"]
    picked = next((f for f in items if f.id == open), items[0] if items else None)  # (the Reader: the note open beside the list)
    return templates.TemplateResponse(request, "manage_feedback.html", {"question_of": question_of, "picked": picked, "words": WORD, "sentences": SENTENCE,
        "items": items, "kept": {f.id for f in items if kept_from(db, f, me)}, "tab": tab, "open": open, "counts": counts, "labels": LABELS,
        "kind": kind, "kinds": KINDS, "kind_chips": [(k, v[1], in_tab.get(k, 0)) for k, v in KINDS.items()]
        + ([("none", "Not sorted", in_tab[""])] if in_tab.get("") and tab in ("review", *OPEN) else []),  # (an old note done is done)
        "tabs": [(t, LABELS.get(t, "All"), counts.get(t, 0) if t != "all" else None) for t in ("review", *OPEN, "done", "all")
                 if t != "review" or counts.get("review") or tab == "review"],
        "toast": request.session.pop("toast", None)})


@router.post("/manage/feedback/{feedback_id:int}")
def change(request: Request, feedback_id: int, to: str = Form(...), answer: str = Form(""), kind: str = Form(""), choice: str = Form(""),
           pics: list[UploadFile] = File(default=[]), db: Session = Depends(get_db)):
    """Answer Claude's question, or add to a note any time (feedback 18, Brett, Nov 5: something forgotten): it's new
    again for Claude, unless it's planned. Or move a note: planned, done, back to new, deleted. A note from the table
    waiting for approval: Approve sends it to Claude (new), Delete drops it; adding to it approves it too. Or change
    what it is (`kind`), with why in its thread."""
    _, denied = web.require(request, is_admin, "Feedback is for admins.")
    if denied:
        return denied
    fb = db.get(Feedback, feedback_id) or _missing()
    asked = approving = approved = False  # (what Claude's inbox hears, below)
    if to == "answer":
        added = add_pictures(db, fb, pics)
        asked, approving = fb.status == "question", fb.status == "review"
        q = question_of(fb) if asked else None
        choices = ((q or {}).get("ask") or {}).get("choices") or []
        picked = int(choice) if choice.isdigit() and int(choice) < len(choices) else None
        if choice and picked is None:
            raise HTTPException(400, "That isn't one of the answers.")
        if not answer.strip() and not added and picked is None:
            if request.query_params.get("back") == "testing":  # (For you: back to the question, saying what's missing)
                request.session["toast"] = web.notice("Pick an answer or write one first.", "warn")
                return RedirectResponse(f"/manage/testing?ask={fb.id}", status_code=303)
            raise HTTPException(400, "Write your answer first.")
        said_text = (f"Picked {'ABCD'[picked]}: {choices[picked]['label']}." if picked is not None else "") + (" " if picked is not None and answer.strip() else "") + answer.strip()
        fb.thread = [*(fb.thread or []), {"who": "you", "text": said_text[:MAX_TEXT], "at": datetime.now(UTC).isoformat(),
                                          **({"choice": picked} if picked is not None else {}), **({"pics": added} if added else {})}]
        if fb.status != "planned":
            fb.status = "new"
        said = ("Answered: it's back with Claude" if asked else "Added and approved: it's with Claude" if approving
                else "Added to the note" + ("" if fb.status == "planned" else ": it's back with Claude"))
    elif to == "tell":  # a reply its sender sees on Your notes (and hears about once)
        if not answer.strip():
            raise HTTPException(400, "Write your reply first.")
        fb.thread = [*(fb.thread or []), {"who": "you", "to": "sender", "text": answer.strip()[:MAX_TEXT], "at": datetime.now(UTC).isoformat()}]
        said = "Sent to " + (fb.sender.split(" (")[0] or "its sender")
    elif to == "kind":
        if kind not in KINDS:
            raise HTTPException(400, "Pick what it is.")
        said = _rekind(fb, kind, answer, "you")
    elif to in ("new", "planned", "done", "deleted"):
        approved = fb.status == "review" and to == "new"
        if to == "deleted" and answer.strip() and fb.user_id:  # why, for its sender (Your notes, round 2: optional)
            fb.thread = [*(fb.thread or []), {"who": "you", "to": "sender", "text": answer.strip()[:MAX_TEXT], "at": datetime.now(UTC).isoformat()}]
        fb.status, said = to, {"new": "Approved: it's with Claude" if approved else "Back to new", "planned": "Planned", "done": "Done",
                               "deleted": "Deleted"}[to]
    else:
        raise HTTPException(400)
    if to == "answer":
        tell_claude(db, fb, "answer" if asked else "note" if approving else "added", "answered" if asked else "approved" if approving else "added to")
    elif to == "new" and approved:
        tell_claude(db, fb, "note", "approved")
    elif to in ("done", "deleted"):
        tell_claude(db, fb, "closed", "marked " + to + " by Brett")
    elif to == "kind":
        tell_claude(db, fb, "added", f"changed to {fb.kind}")
    db.commit()
    request.session["toast"] = said
    if request.query_params.get("back") == "testing":  # (answered in Testing's For you: back there, at the next thing for you)
        return RedirectResponse("/manage/testing", status_code=303)
    back_kind = request.query_params.get("kind", "")
    return RedirectResponse(f"{BACK}?tab={request.query_params.get('tab', '')}&kind={back_kind if back_kind in (*KINDS, 'none') else ''}",
                            status_code=303)


def _rekind(fb: Feedback, kind: str, why: str, who: str) -> str:
    """A note is something else than its sender picked (a "bug" that's really a design change): its new kind, and
    the change in its thread with why, for the admins and Claude (never its sender's Your notes)."""
    if kind == fb.kind:
        return "Already " + KINDS[kind][1].lower()
    was = KINDS[fb.kind][1] if fb.kind in KINDS else "Not sorted"
    fb.kind = kind
    why = why.strip()[:MAX_TEXT]
    fb.thread = [*(fb.thread or []), {"who": who, "text": f"{was} → {KINDS[kind][1]}" + (f": {why}" if why else ""), "at": now_iso(),
                                      "kind": kind}]
    return f"Now {KINDS[kind][1].lower()}"


def _missing():
    raise HTTPException(404)


def kept_from(db: Session, fb: Feedback, viewer: str | None) -> bool:
    """A note's page and pictures are kept from an admin who is the DM of a campaign its sender (or whoever its sender
    was viewing as) plays in: the page can hold their character notes (the outside review's C9; CLAUDE.md ›
    Visibility, never the campaign's DM, even an admin). Its words stay: they're the sender's own."""
    sender = db.get(User, fb.user_id) if fb.user_id else None
    people = [sender.email if sender else None, (fb.context or {}).get("viewing_as_email")]
    return any(access.dm_over(viewer, p) for p in people if p)


def _shot(db: Session, feedback_id: int, which: str):
    fb = db.get(Feedback, feedback_id) or _missing()
    key = {"shot": fb.shot_key, "pasted": fb.pasted_key}.get(which) or _missing()
    content_type = next((t for t, (ext, _) in files.TYPES.items() if key.endswith(ext)), "image/png")
    return files.serve(key, content_type, release=db)


@router.get("/manage/feedback/{feedback_id:int}/pic/{pic_id:int}")
def added_picture(request: Request, feedback_id: int, pic_id: int, db: Session = Depends(get_db)):
    """A screenshot added to a note with Add to it; kept from an admin who is its sender's DM, as its page is."""
    user, denied = web.require(request, is_admin, "Feedback is for admins.")
    if denied:
        return denied
    fb = db.get(Feedback, feedback_id) or _missing()
    claudes = {c.get("pic") for m in fb.thread or [] if m.get("who") == "claude" for c in (m.get("ask") or {}).get("choices") or []}
    if pic_id not in claudes and kept_from(db, fb, user["email"]):  # (Claude's own drawings for a pick are never the sender's)
        raise HTTPException(404)
    return picture_of(db, fb, pic_id)


@router.get("/manage/feedback/{feedback_id:int}/{which}")
def picture(request: Request, feedback_id: int, which: str, db: Session = Depends(get_db)):
    """A note's picture (`shot`, `pasted`), or the page as drawn (`page`, as text: it never runs here)."""
    user, denied = web.require(request, is_admin, "Feedback is for admins.")
    if denied:
        return denied
    fb = db.get(Feedback, feedback_id) or _missing()
    if kept_from(db, fb, user["email"]):
        raise HTTPException(404)
    if which == "page":
        return Response(fb.html or "", media_type="text/plain; charset=utf-8", headers={"X-Content-Type-Options": "nosniff"})
    return _shot(db, feedback_id, which)


# ------------------------------------------------------------------ Claude's side (its key)


def _claude(key: str | None) -> None:
    if not config.FEEDBACK_KEY or not key or not secrets.compare_digest(key, config.FEEDBACK_KEY):
        raise HTTPException(404)


@router.get("/api/feedback")
def api_list(status: str = ",".join(OPEN), kind: str = "", x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """The queue for Claude: the notes in these states (default: new, question, planned), of these kinds (default
    any; "none" is a note not yet sorted), without their pages."""
    _claude(x_feedback_key)
    wanted = [s for s in status.split(",") if s in STATUSES] or list(OPEN)
    q = select(Feedback).where(Feedback.status.in_(wanted)).order_by(Feedback.id)
    kinds = ["" if k == "none" else k for k in kind.split(",") if k in (*KINDS, "none")]
    rows = db.scalars(q.where(Feedback.kind.in_(kinds)) if kinds else q)
    return JSONResponse({"items": [_item(fb) for fb in rows]}, headers={"Cache-Control": "no-store"})


@router.get("/api/feedback/{feedback_id:int}")
def api_one(feedback_id: int, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    _claude(x_feedback_key)
    return JSONResponse(_item(db.get(Feedback, feedback_id) or _missing(), html=True), headers={"Cache-Control": "no-store"})


@router.get("/api/feedback/{feedback_id:int}/pic/{pic_id:int}")
def api_added_picture(feedback_id: int, pic_id: int, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    _claude(x_feedback_key)
    return picture_of(db, db.get(Feedback, feedback_id) or _missing(), pic_id)


@router.get("/api/feedback/{feedback_id:int}/{which}")
def api_picture(feedback_id: int, which: str, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    _claude(x_feedback_key)
    return _shot(db, feedback_id, which)


@router.post("/api/feedback/{feedback_id:int}")
def api_change(feedback_id: int, body=web.JsonBody, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude moves a note on: a question for Brett (`note`, which makes it a question unless `status` says else), a
    status, the PR that fixed it, what it is (`kind`, with `why`), or its short title (`title`; Brett, Nov 16)."""
    _claude(x_feedback_key)
    body = body if isinstance(body, dict) else {}
    fb = db.get(Feedback, feedback_id) or _missing()
    if body.get("kind"):
        if not isinstance(body["kind"], str) or body["kind"] not in KINDS:
            raise HTTPException(400, f"A kind is one of {', '.join(KINDS)}.")
        _rekind(fb, body["kind"], str(body.get("why") or ""), "claude")
    if body.get("check_do"):  # (its check's steps follow the walkthrough's rules before anything changes: testing.step_problems)
        from app import testing

        if wrong := testing.step_problems(str(body["check_do"])):
            raise HTTPException(400, " ".join(wrong) + " (docs/testing-guide.md)")
    tell = str(body.get("tell") or "").strip()[:MAX_TEXT]
    if tell:  # (a reply its sender sees: `feedback.py tell`)
        fb.thread = [*(fb.thread or []), {"who": "claude", "to": "sender", "text": tell, "at": datetime.now(UTC).isoformat()}]
    note = str(body.get("note") or "").strip()[:MAX_TEXT]
    ask = _asking(db, fb, body)
    if ask and not note:
        raise HTTPException(400, "Choices come with the question (note).")
    if note:
        fb.thread = [*(fb.thread or []), {"who": "claude", "text": note, "at": datetime.now(UTC).isoformat(), **({"ask": ask} if ask else {})}]
    status = body.get("status") or ("question" if note else None)
    if status:
        if status not in STATUSES:
            raise HTTPException(400, f"A status is one of {', '.join(STATUSES)}.")
        fb.status = status
    if body.get("pr"):
        fb.pr = str(body["pr"])[:300]
    if isinstance(body.get("title"), str):
        fb.title = " ".join(body["title"].split())[:MAX_TITLE]
    if fb.status == "done" and fb.kind in ("broken", "idea") and fb.pr:  # (every fixed note gets its check: Testing, Brett Nov 16)
        from app import testing

        sent_by = db.get(User, fb.user_id) if fb.user_id else None
        testing.for_note(db, fb, str(body.get("check_do") or ""), str(body.get("check_expect") or ""),
                         admin_sent=bool(sent_by) and access.level(sent_by.email) == access.ADMIN)
    db.commit()
    return JSONResponse(_item(fb))


# ------------------------------------------------------------------ a sender's own notes (Your notes › About askdnd, app/your_notes.py)

SENDER_SAYS = {"review": ("Waiting for an admin", "An admin reads it first, then sends it to Claude."),
               "new": ("With Claude", "Claude has it and will look at it with the next batch."),
               "question": ("With Claude", "Claude has it and will look at it with the next batch."),
               "planned": ("Planned", "Claude is going to fix this."),
               "done": ("Fixed", "It's fixed on askdnd."),
               "deleted": ("Closed", "Not something askdnd will change for now.")}
# where an idea or a question stands, when it differs from something broken's (Brett, Nov 16)
SENDER_SAYS_KIND = {"idea": {"planned": ("On the Roadmap", "It's on askdnd's Roadmap as an idea; an admin picks when it's built."),
                             "done": ("Built", "It's on askdnd now.")},
                    "question": {"planned": ("With Claude", "Claude has it and will answer it with the next batch."),
                                 "done": ("Answered", "Claude answered it.")}}
# each kind's steps on its sender's status track (Your notes), and how far each status reaches along them
# (named for the states its sender sees, With Claude not "Approved": one set of words, the UI review, Nov 16)
STEPS = {"broken": ("Sent", "With Claude", "Planned", "Fixed"), "idea": ("Sent", "With Claude", "On the Roadmap", "Built"),
         "question": ("Sent", "With Claude", "Answered")}
REACHED = {"question": {"review": 0, "new": 1, "question": 1, "planned": 1, "done": 2}}


def says(fb: Feedback) -> tuple[str, str]:
    """Where a note stands for its sender, in its kind's words: (label, sentence)."""
    return SENDER_SAYS_KIND.get(fb.kind, {}).get(fb.status) or SENDER_SAYS.get(fb.status, ("", ""))


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def marker(fb: Feedback) -> str:
    """Where a note stands for its sender: its status and how many replies to them (what `told` remembers)."""
    to_them = sum(1 for m in fb.thread or [] if m.get("to") == "sender")
    return f"{'new' if fb.status == 'question' else fb.status}:{to_them}"


def for_sender(fb: Feedback) -> dict:
    """A note as its sender sees it: never the admin's or Claude's notes to each other, nor the page as drawn."""
    label, sentence = says(fb)
    shown = [{"who": "You" if m.get("who") == "sender" else "Claude" if m.get("who") == "claude" else "An admin",
              "mine": m.get("who") == "sender", "text": m.get("text", ""), "at": m.get("at", ""),
              "pics": m.get("pics", []) if m.get("who") == "sender" else []}
             for m in fb.thread or [] if m.get("who") == "sender" or m.get("to") == "sender"]
    return {"id": fb.id, "text": fb.text, "status": fb.status, "kind": fb.kind, "label": label, "says": sentence, "page": (fb.context or {}).get("page") or fb.url,
            "url": fb.url, "at": fb.created_at, "thread": shown, "can_add": fb.status != "deleted"}
