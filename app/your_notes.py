"""Your notes (Brett, Nov 7, docs/mockups/your-notes/ Layout A and a badge): one page for what someone sent, in two
tabs that say who reads it.

- **About the story**: corrections and additions to a recap, an entry or the glossary (`Fact`, `Suggestion`), which
  the DM reads and decides on: Waiting, Added, Used, Not used (`suggestions.outcome`).
- **About askdnd**: notes sent with \\ (`Feedback`), which an admin reads first, then Claude: Waiting for an admin,
  With Claude, Planned, Fixed, Closed, with the replies meant for the sender and Add to it (app/feedback.py). Shown to
  anyone who can send one or has.

**Knowing something moved**: each note remembers what its author last saw (`seen`: the badge on their picture, More
on a phone and each tab's "new", cleared when they open that tab) and what they last had a corner card about (`told`:
one card per change, which doesn't clear the badge). News is a change only: a suggestion decided (added, used or not
used), a note sent to Claude, planned, fixed or closed, or a reply.
"""

import re

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, feedback, picks, view_as, web
from app.auth import current_user
from app.db import get_db
from app.extraction import session_label
from app.models import Entity, Fact, Feedback, GameSession, GlossaryTerm, Status, Suggestion
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

TITLE_MOST = 90


def title_of(text: str) -> str:
    """A note's title: its first sentence (or line), cut at a word to about one line, so a list of notes is a list of
    different things (the row clips it further to its width; the note beside it shows it whole)."""
    first = re.split(r"(?<=[.!?])\s|\n", (text or "").strip(), maxsplit=1)[0].strip() or "A note"
    if len(first) <= TITLE_MOST:
        return first
    cut = first[:TITLE_MOST].rsplit(" ", 1)[0] if " " in first[:TITLE_MOST] else first[:TITLE_MOST - 1]
    return cut.rstrip(" ,;:") + "…"


ASKDND_STEPS = ("Sent", "Approved", "Planned", "Fixed")
ASKDND_REACHED = {"review": 0, "new": 1, "question": 1, "planned": 2, "done": 3}
ASKDND_DOT = {"review": "wait", "new": "claude", "question": "claude", "planned": "planned", "done": "done", "deleted": "closed"}
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


def askdnd_note(fb) -> dict:
    """A note about askdnd as its sender sees it, in the shape both tabs share."""
    n = {**feedback.for_sender(fb), "new": _feedback_new(fb, "seen")}
    replies = [m for m in n["thread"] if not m["mine"]]
    answer = replies[-1] if replies else None
    page = n["page"] or ""
    closed = fb.status == "deleted"
    return {"key": f"f{fb.id}", "id": fb.id, "kind": "askdnd", "title": title_of(fb.text), "text": fb.text, "at": fb.created_at,
            "where": page, "href": n["url"], "from": page.rsplit(" · ", 1)[-1] if page else "Another page",
            "label": n["label"], "dot": ASKDND_DOT.get(fb.status, "claude"), "open": fb.status not in ("done", "deleted"),
            "answer": answer, "says": n["says"], "landed": None, "earlier": [m for m in n["thread"] if m is not answer],
            "track": track(ASKDND_STEPS, ASKDND_REACHED.get(fb.status, 0), "Closed" if closed else ""),
            "new": n["new"], "can_add": n["can_add"]}


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
    steps = ("Sent", "With the DM", o if o in ("Added", "Used") else "Added or used")
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


# ------------------------------------------------------------------ about askdnd (an admin, then Claude)


def _feedback_new(fb, field: str) -> bool:
    return fb.status != "review" and getattr(fb, field) != feedback.marker(fb)


def notes_of(db: Session, user: dict | None) -> list[Feedback]:
    """The notes about askdnd this person sent: the page's person, so an admin viewing as Mark sees Mark's (Brett, Nov 7)."""
    me = picks.user_row(db, user) if user else None
    if me is None:
        return []
    return list(db.scalars(select(Feedback).where(Feedback.user_id == me.id).order_by(Feedback.id.desc()).limit(200)))


def shows_askdnd(user: dict, notes: list) -> bool:
    return bool(notes) or access.sends_feedback(user.get("email"))


def _looking(request: Request) -> bool:
    """An admin viewing as someone: they see that person's page, and nothing about it changes (nothing marked seen)."""
    return view_as.viewing(request.session) is not None


# ------------------------------------------------------------------ the page


@router.get("/your-notes")
def page(request: Request, tab: str = "", note: str = "", db: Session = Depends(get_db)):
    """Your notes: About the story and About askdnd, the tab with news first."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    rows = story(db, user)
    notes = notes_of(db, user)
    askdnd = shows_askdnd(user, notes)
    news = {"story": sum(r["new"] for r in rows), "askdnd": sum(_feedback_new(fb, "seen") for fb in notes)}
    if tab not in TABS or (tab == "askdnd" and not askdnd):
        tab = "askdnd" if askdnd and news["askdnd"] and not news["story"] else "story" if rows or not askdnd else "askdnd"
    lists = {"story": ranked([story_note(r) for r in rows]), "askdnd": ranked([askdnd_note(fb) for fb in notes])}
    if not _looking(request):  # (the tab it opens on is seen; the other when it's opened, `seen`)
        _mark(rows, notes, tab)
        news[tab] = 0
        db.commit()
    return templates.TemplateResponse(request, "your_notes.html", {
        "tab": tab, "lists": lists, "note": note, "askdnd": askdnd, "news": news, "toast": request.session.pop("toast", None)})


def _mark(rows: list[dict], notes: list, tab: str) -> None:
    """A tab opened: its notes are seen (the badge) and need no card."""
    if tab == "story":
        for r in rows:
            r["x"].seen = r["x"].told = r["x"].status
    else:
        for fb in notes:
            fb.seen = fb.told = feedback.marker(fb)


@router.get("/your-notes/seen")
def seen(request: Request, tab: str = "", db: Session = Depends(get_db)):
    """Another tab opened on the page (app.js "your notes"): its notes are seen. The badge's new count comes back. A
    read under View as: an admin viewing as someone changes nothing for them."""
    user = current_user(request)
    if not user or tab not in TABS:
        return JSONResponse({"count": 0}, headers={"Cache-Control": "no-store"})
    rows, notes = story(db, user), notes_of(db, user)
    if not _looking(request):
        _mark(rows, notes, tab)
        db.commit()
    count = sum(_story_new(r["x"], "seen") for r in rows) + sum(_feedback_new(fb, "seen") for fb in notes)
    return JSONResponse({"count": count}, headers={"Cache-Control": "no-store"})


@router.post("/your-notes/feedback/{feedback_id:int}")
def add_to(request: Request, feedback_id: int, text: str = Form(""), db: Session = Depends(get_db)):
    """Add to your own note about askdnd. From a player it goes to an admin first, as a new note does (Brett, Nov 6)."""
    user = current_user(request)
    fb = next((x for x in notes_of(db, user) if x.id == feedback_id), None)
    if fb is None or fb.status == "deleted":
        raise HTTPException(404)
    if not text.strip():
        raise HTTPException(400, "Write what you'd add first.")
    fb.thread = [*(fb.thread or []), {"who": "sender", "text": text.strip()[:feedback.MAX_TEXT], "at": feedback.now_iso()}]
    admin = access.level((user or {}).get("email")) == access.ADMIN
    fb.status = ("planned" if fb.status == "planned" else "new") if admin else "review"
    fb.seen = fb.told = feedback.marker(fb)
    db.commit()
    request.session["toast"] = web.notice("Added: an admin reads it first" if not admin else "Added: it's with Claude")
    return RedirectResponse(f"/your-notes?tab=askdnd&note=f{fb.id}", status_code=303)


STORY_NEWS = {"Added": "The DM added your note", "Used": "The DM used your note", "Not used": "The DM didn't use your note"}
ASKDND_NEWS = {"new": "Sent to Claude", "planned": "Planned", "done": "Fixed", "deleted": "Closed"}


@router.get("/your-notes/news")
def news(request: Request, db: Session = Depends(get_db)):
    """The badge's count (what you haven't seen, by tab) and the corner cards for what moved since your last card (each
    once), asked once a page by app.js "your notes". A read (View as passes it; an admin viewing as someone gets the
    count and no cards, and nothing is marked told)."""
    user = current_user(request)
    if not user:
        return JSONResponse({"count": 0, "tabs": {}, "cards": []})
    rows = story(db, user)
    notes = notes_of(db, user)
    tabs = {"story": sum(r["new"] for r in rows), "askdnd": sum(_feedback_new(fb, "seen") for fb in notes)}
    cards, tab_of = [], []
    if _looking(request):
        return JSONResponse({"count": sum(tabs.values()), "tabs": tabs, "cards": []}, headers={"Cache-Control": "no-store"})
    for r in rows:
        x = r["x"]
        if _story_new(x, "told"):
            cards.append(f"{STORY_NEWS.get(outcome(x.status)['label'], 'Your note moved')}: “{_short(x.text)}”")
            tab_of.append("story")
            x.told = x.status
    for fb in notes:
        if _feedback_new(fb, "told"):
            was = (fb.told or "review:0").split(":")[0]
            now = feedback.marker(fb)
            cards.append(f"{ASKDND_NEWS.get(fb.status, 'Moved') if now.split(':')[0] != was else 'A reply'}: “{_short(fb.text)}”")
            tab_of.append("askdnd")
            fb.told = now
    if cards:
        db.commit()
    if len(cards) > MOST_CARDS:
        cards, tab_of = [f"{len(cards)} of your notes moved on"], [max(set(tab_of), key=tab_of.count)]
    return JSONResponse({"count": sum(tabs.values()), "tabs": tabs,
                         "cards": [{"text": c, "href": f"/your-notes?tab={t}"} for c, t in zip(cards, tab_of, strict=True)]},
                        headers={"Cache-Control": "no-store"})
