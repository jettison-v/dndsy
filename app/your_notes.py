"""Your notes (Brett, Nov 7, docs/mockups/your-notes/ Layout A and a badge): one page for what someone sent, in two
tabs that say who reads it.

- **About the story**: corrections and additions to a recap, an entry or the glossary (`Fact`, `Suggestion`), which
  the DM reads and decides on: Waiting, Added, Used, Not used (`suggestions.outcome`).
- **Product Feedback**: notes sent with \\ (Found, Fixed, Tried: app/fft; screen 15), which an admin reads first, then
  Claude. Each says whose turn it is and what that means (`fft.views.sender_says`), its conversation (only the lines
  meant for its sender: never another sender's words or the issue's title, R2), Add to it (a player's waits for an
  admin, T1) and, for a fix it prompted, Does it work now? (R5). Counted: what's still open. Shown to anyone who can send
  one or has.

**Knowing something moved**: each note remembers what its author last saw (`seen`: the badge on their picture, More
on a phone and each tab's "new", cleared when they open that tab) and what they last had a corner card about (`told`:
one card per change, which doesn't clear the badge). News is a change only: a suggestion decided (added, used or not
used), a note sent to Claude, planned, fixed or closed, or a reply.
"""

import base64

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import access, files, picks, view_as, web
from app.auth import current_user
from app.db import get_db
from app.extraction import session_label
from app.fft import rules, sending
from app.fft import views as fft_views
from app.fft.models import FftCheck, FftCheckIssue, FftCheckVersion, FftIssue, FftLine, FftNote, FftPicture, FftQuestion
from app.models import Entity, Fact, GameSession, GlossaryTerm, Status, Suggestion
from app.suggestions import outcome
from app.templating import templates

router = APIRouter()
TABS = ("story", "askdnd")
MOST_CARDS = 3  # (more at once: one card that says how many)


def _short(text: str) -> str:
    return text if len(text) <= 60 else text[:57].rstrip() + "…"


# ------------------------------------------------------------------ one shape for every note (round 2, feedback 54)
# Brett chose Layout B, Nov 7 (docs/mockups/your-notes-2/): a list beside the note, the same in both tabs. Every note has
# three parts: what you asked (a title, its first sentence), what happened (the answer: Claude's, an admin's or the
# DM's words, else what its status means) and where it stands (a track of steps, the one it's at lit).

title_of = fft_views.title_of  # (a note's title: its first sentence; one way for both tabs)

STORY_DOT = {"Waiting": "wait", "Added": "done", "Used": "used", "Not used": "closed"}


def track(steps: tuple, reached: int, stop: str = "") -> list[dict]:
    """The steps with where the note is: each done up to `reached`, the next one under way; with `stop`, it ended there
    instead (turned down) and the rest are struck through."""
    if stop:
        return [{"label": steps[0], "state": "done"}, *([{"label": steps[1], "state": "done"}] if reached >= 1 else []),
                {"label": stop, "state": "stop"}, *({"label": x, "state": "skip"} for x in steps[reached + 2:] if x != stop)]
    return [{"label": x, "state": "done" if i <= reached else "now" if i == reached + 1 else "todo"} for i, x in enumerate(steps)]


def _when(at) -> float:
    return at.timestamp() if at else 0.0


def story_note(r: dict) -> dict:
    """A correction or addition about the story, in the shape both tabs share."""
    x, o = r["x"], outcome(r["x"].status)["label"]
    fact = isinstance(x, Fact)
    about = "An entry" if fact else "A recap" if x.target_type == "session" else "The glossary"
    landed = {"Added": f"On {r['label']}'s page" if fact else "In the glossary",
              "Used": f"Worked into {r['label']}" if not fact else f"On {r['label']}'s page"}.get(o)
    says = {"Waiting": "The DM hasn't decided yet.", "Added": "The DM added it as you wrote it.",
            "Used": "The DM worked it in.", "Not used": "The DM decided not to use it."}[o]
    answer = {"who": "The DM", "text": x.reply, "mine": False} if getattr(x, "reply", "") else None
    steps = ("Sent", "Waiting", o if o in ("Added", "Used") else "Added or used")  # (the states' own words: the UI review)
    return {"key": f"{'x' if fact else 's'}{x.id}", "id": x.id, "kind": "story", "title": title_of(x.text), "text": x.text,
            "at": x.created_at, "where": r["label"], "href": r["href"], "from": about,
            "label": o, "dot": STORY_DOT[o], "open": o == "Waiting", "answer": answer, "says": says,
            "landed": {"text": landed, "href": r["href"]} if landed else None, "earlier": [],
            "track": track(steps, 1, "Not used") if o == "Not used" else track(steps, 0 if o == "Waiting" else 2),
            "new": r["new"], "can_add": False}


def ranked(notes: list[dict]) -> list[dict]:
    """Open first, then done; each note's place for Newest first and Oldest first (app.js "Lists" sorts by it)."""
    for order, key in (("newest", lambda n: (not n["open"], -_when(n["at"]))), ("oldest", lambda n: (not n["open"], _when(n["at"])))):
        for i, n in enumerate(sorted(notes, key=key)):
            n[f"rank_{order}"] = i
    return sorted(notes, key=lambda n: n["rank_newest"])


# ------------------------------------------------------------------ about the story (the DM reads them)


def story(db: Session, user: dict) -> list[dict]:
    """Every correction or addition this person sent, newest first, with where it is and how it stands."""
    email = (user.get("email") or "").lower()
    rows = [{"x": f, "label": e.name, "href": f"{web.base()}/campaign?open={e.id}"}
            for f, e in db.execute(select(Fact, Entity).join(Entity, Fact.entity_id == Entity.id)
                                   .where(func.lower(Fact.author_email) == email, Entity.status == Status.PUBLISHED))]
    for x in db.scalars(select(Suggestion).where(func.lower(Suggestion.author_email) == email)):
        if x.target_type == "session":
            s = db.get(GameSession, x.target_id)
            rows.append({"x": x, "label": session_label(s) if s else "A session",
                         "href": f"{web.base()}/campaign?tab=sessions#s{s.id}" if s else f"{web.base()}/campaign?tab=sessions"})
        else:
            t = db.get(GlossaryTerm, x.target_id) if x.target_id else None
            rows.append({"x": x, "label": f"Glossary: {t.term}" if t else "Glossary: new term", "href": f"{web.base()}/campaign?tab=glossary"})
    for r in rows:
        r["new"] = _story_new(r["x"], "seen")
    rows.sort(key=lambda r: (r["x"].created_at, r["x"].id), reverse=True)
    return rows


def _story_new(x, field: str) -> bool:
    """Decided since its author last saw it (the badge) or had a card about it."""
    return x.status != "pending" and getattr(x, field) != x.status




# ------------------------------------------------------------------ Product Feedback (an admin, then Claude: app/fft)


def _me(db: Session, user: dict | None):
    """The page's person (an admin viewing as Mark sees Mark's notes, Brett, Nov 7)."""
    return picks.user_row(db, user) if user else None


def fft_note(db: Session, note: FftNote, me_id: int | None) -> dict:
    """A note about askdnd as its sender reads it."""
    says = fft_views.sender_says(db, note, me_id)
    issue = db.get(FftIssue, note.issue_id) if note.issue_id else None
    lines = fft_views.sender_lines(db, note)
    pics = list(db.scalars(select(FftPicture).where(or_(FftPicture.note_id == note.id, FftPicture.line_id.in_([x.id for x in lines] or [0])))
                           .order_by(FftPicture.id)))
    trying = None
    if issue is not None and issue.state == "ready" and issue.confirm_by and issue.confirm_by == me_id:
        v = db.execute(select(FftCheckVersion).join(FftCheckIssue, FftCheckIssue.check_id == FftCheckVersion.check_id)
                       .join(FftCheck, FftCheck.id == FftCheckVersion.check_id)
                       .where(FftCheckIssue.issue_id == issue.id, FftCheck.version == FftCheckVersion.version, FftCheck.retired.is_(False))).scalars().first()
        trying = {"issue": issue.id, "steps": v.steps if v else [], "expect": v.expect if v else ""}
    return {"key": f"f{note.id}", "id": note.id, "title": title_of(note.text), "text": note.text, "at": note.created_at,
            "where": note.page, "href": fft_views.local_href(note.url), "says": says,
            "open": says["open"], "new": note.seen != fft_views.marker(db, note, me_id), "lines": lines,
            "pics": [p for p in pics if p.note_id == note.id], "line_pics": {p.line_id: p for p in pics if p.line_id},
            "kind_said": fft_views.KIND_SAID.get(note.kind, ""), "trying": trying, "admin": note.role == "admin",
            "closed_words": issue.close_words if issue is not None and issue.state == "closed" else "", "can_add": says["open"] or note.state == "waiting"}


def shows_askdnd(user: dict, notes: list) -> bool:
    return bool(notes) or access.sends_feedback(user.get("email"))


def _looking(request: Request) -> bool:
    """An admin viewing as someone: they see that person's page, and nothing about it changes (nothing marked seen)."""
    return view_as.viewing(request.session) is not None


# ------------------------------------------------------------------ the page


@router.get("/your-notes")
def page(request: Request, tab: str = "", note: str = "", db: Session = Depends(get_db)):
    """Notes you sent: The Story and Product Feedback, the tab with news first."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    me = _me(db, user)
    rows = story(db, user)
    notes = fft_views.notes_of(db, me.id if me else None)
    askdnd = shows_askdnd(user, notes)
    shaped = [fft_note(db, n, me.id if me else None) for n in notes]
    news = {"story": sum(r["new"] for r in rows), "askdnd": sum(n["new"] for n in shaped)}
    if tab not in TABS or (tab == "askdnd" and not askdnd):
        tab = "askdnd" if askdnd and news["askdnd"] and not news["story"] else "story" if rows or not askdnd else "askdnd"
    lists = {"story": ranked([story_note(r) for r in rows]), "askdnd": ranked(shaped)}
    if not _looking(request):  # (the tab it opens on is seen; the other when it's opened, `seen`)
        _mark(db, rows, notes, tab, me.id if me else None)
        db.commit()
    return templates.TemplateResponse(request, "your_notes.html", {
        "tab": tab, "lists": lists, "note": note, "askdnd": askdnd, "news": news, "toast": request.session.pop("toast", None),
        "open_count": sum(1 for n in shaped if n["open"]), "looking": _looking(request)})


def _mark(db: Session, rows: list[dict], notes: list, tab: str, me_id: int | None) -> None:
    """A tab opened: its notes are seen (the badge) and need no card."""
    if tab == "story":
        for r in rows:
            r["x"].seen = r["x"].told = r["x"].status
    else:
        marks = fft_views.markers(db, notes, me_id)
        for n in notes:
            n.seen = n.told = marks[n.id]


def _own(db: Session, request: Request, note_id: int) -> tuple[FftNote, int]:
    me = _me(db, current_user(request))
    note = db.get(FftNote, note_id)
    if me is None or note is None or note.user_id != me.id:
        raise HTTPException(404)
    return note, me.id


@router.get("/your-notes/pictures/{pic_id:int}")
def own_picture(request: Request, pic_id: int, db: Session = Depends(get_db)):
    """A picture you sent: the full copy, yours alone (T5). An admin viewing as you sees its safe copy."""
    pic = db.get(FftPicture, pic_id)
    if pic is None:
        raise HTTPException(404)
    line = db.get(FftLine, pic.line_id) if pic.line_id else None
    _own(db, request, pic.note_id or (line.note_id if line else 0))
    key = pic.safe_key if _looking(request) else pic.key
    return files.serve(key, next((t for t, (ext, _) in files.TYPES.items() if key.endswith(ext)), "image/png"), cache_control="private, no-store", release=db)


@router.get("/your-notes/seen")
def seen(request: Request, tab: str = "", db: Session = Depends(get_db)):
    """Another tab opened on the page (app.js "your notes"): its notes are seen. The badge's new count comes back. A
    read under View as: an admin viewing as someone changes nothing for them."""
    user = current_user(request)
    if not user or tab not in TABS:
        return JSONResponse({"count": 0}, headers={"Cache-Control": "no-store"})
    me = _me(db, user)
    me_id = me.id if me else None
    rows, notes = story(db, user), fft_views.notes_of(db, me_id)
    if not _looking(request):
        _mark(db, rows, notes, tab, me_id)
        db.commit()
    marks = fft_views.markers(db, notes, me_id)
    count = sum(_story_new(r["x"], "seen") for r in rows) + sum(n.seen != marks[n.id] for n in notes)
    return JSONResponse({"count": count}, headers={"Cache-Control": "no-store"})


def _uploads(db: Session, pics: list[UploadFile] | None) -> list[dict]:
    """Screenshots added with Add to it, as the sending window's pictures (a picture you add is yours to share)."""
    out = []
    for up in [u for u in pics or [] if u is not None and u.filename]:
        if up.content_type not in ("image/png", "image/jpeg", "image/webp"):
            raise HTTPException(400, "A screenshot as PNG, JPEG or WebP, please.")
        data = up.file.read(sending.MAX_PIC_BYTES + 1)
        if len(data) > sending.MAX_PIC_BYTES:
            raise HTTPException(400, "A screenshot is over 8 MB.")
        url = f"data:{up.content_type};base64," + base64.b64encode(data).decode()
        out.append({"full": url, "safe": url, "kind": "added"})
    if len(out) > sending.MAX_PICS:
        raise HTTPException(400, f"{sending.MAX_PICS} screenshots at most, at a time.")
    return out


@router.post("/your-notes/notes/{note_id:int}")
def add_to(request: Request, note_id: int, text: str = Form(""), pics: list[UploadFile] = File(default=[]), db: Session = Depends(get_db)):
    """Add to your own note, words and screenshots (feedback 64). A player's goes to an admin first, as a note does (T1)."""
    note, me_id = _own(db, request, note_id)
    if _looking(request):
        raise HTTPException(403, "Viewing as someone changes nothing for them.")
    added = _uploads(db, pics)
    if not text.strip() and not added:
        raise HTTPException(400, "Write what you'd add first.")
    admin = note.role == "admin"
    line = rules.add_line(db, f"user:{me_id}", text.strip() or "(a picture)", note=note, who="sender", user_id=me_id,
                          approved=admin or note.state == "waiting")  # (on a waiting note it waits with the note)
    sending.keep_pictures(db, added, line_id=line.id)
    note.seen = note.told = fft_views.marker(db, note, me_id)
    db.commit()
    request.session["toast"] = web.notice("Added: it's with Claude" if admin else "Added: an admin reads it first")
    return RedirectResponse(f"/your-notes?tab=askdnd&note=f{note.id}", status_code=303)


@router.post("/your-notes/notes/{note_id:int}/works")
def works(request: Request, note_id: int, answer: str = Form(""), text: str = Form(""), db: Session = Depends(get_db)):
    """Does it work now? (R5): the player whose note prompted a fix says. Yes closes it as working; Still broken makes it
    Claude's again, their words waiting for an admin (T1)."""
    note, me_id = _own(db, request, note_id)
    issue = db.get(FftIssue, note.issue_id) if note.issue_id else None
    if _looking(request) or issue is None or answer not in ("yes", "no"):
        raise HTTPException(404)
    try:
        rules.player_confirms(db, f"user:{me_id}", issue, answer == "yes", text.strip(), user_id=me_id)
    except rules.RuleError as e:
        raise HTTPException(409, e.words) from e
    note.seen = note.told = fft_views.marker(db, note, me_id)
    db.commit()
    request.session["toast"] = web.notice("Thanks: it's marked working" if answer == "yes" else "Sent back: it's not fixed yet")
    return RedirectResponse(f"/your-notes?tab=askdnd&note=f{note.id}", status_code=303)


STORY_NEWS = {"Added": "The DM added your note", "Used": "The DM used your note", "Not used": "The DM didn't use your note"}


@router.get("/your-notes/news")
def news(request: Request, db: Session = Depends(get_db)):
    """The badge's count (what you haven't seen, by tab) and the corner cards for what moved since your last card (each
    once), asked once a page by app.js "your notes". A read (View as passes it; an admin viewing as someone gets the
    count and no cards, and nothing is marked told)."""
    user = current_user(request)
    if not user:
        return JSONResponse({"count": 0, "tabs": {}, "cards": []})
    me = _me(db, user)
    me_id = me.id if me else None
    rows = story(db, user)
    notes = fft_views.notes_of(db, me_id)
    markers = fft_views.markers(db, notes, me_id)
    tabs = {"story": sum(r["new"] for r in rows), "askdnd": sum(n.seen != markers[n.id] for n in notes)}
    if _looking(request):
        return JSONResponse({"count": sum(tabs.values()), "tabs": tabs, "cards": []}, headers={"Cache-Control": "no-store"})
    cards, tab_of = [], []
    for r in rows:
        x = r["x"]
        if _story_new(x, "told"):
            cards.append(f"{STORY_NEWS.get(outcome(x.status)['label'], 'Your note moved')}: “{_short(x.text)}”")
            tab_of.append("story")
            x.told = x.status
    for n in notes:
        if n.told != markers[n.id]:
            was, now = (n.told or ":").split(":")[0], markers[n.id].split(":")[0]
            cards.append(f"{now if now != was else 'A reply'}: “{_short(n.text)}”")
            tab_of.append("askdnd")
            n.told = markers[n.id]
    if cards:
        db.commit()
    if len(cards) > MOST_CARDS:
        cards, tab_of = [f"{len(cards)} of your notes moved on"], [max(set(tab_of), key=tab_of.count)]
    shown = [{"text": c, "href": f"/your-notes?tab={t}"} for c, t in zip(cards, tab_of, strict=True)]
    if access.level((user or {}).get("email")) == access.ADMIN and (asked := _new_asks(request, db)):  # (Working with Claude, 5A)
        shown.append({"text": f"Claude asked you {asked} question{'s' if asked != 1 else ''}", "href": "/manage/testing"})
    return JSONResponse({"count": sum(tabs.values()), "tabs": tabs, "cards": shown}, headers={"Cache-Control": "no-store"})


ASKS_SEEN = "fft_asks_seen"  # (the newest of Claude's questions an admin had a card about, on this device's session)


def _new_asks(request: Request, db: Session) -> int:
    """Claude's questions asked since this admin's last card about them (one card, then quiet until another comes)."""
    ids = list(db.scalars(select(FftQuestion.id).where(FftQuestion.answered_at.is_(None))))
    seen = request.session.get(ASKS_SEEN) or 0
    fresh = [i for i in ids if i > seen]
    if fresh:
        request.session[ASKS_SEEN] = max(ids)
    return len(fresh)
