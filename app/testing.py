"""Testing in askdnd (Brett's idea and picks 1A, 2A, 3A, 4A, 5B, 6C, Nov 16; docs/mockups/testing/).

A **check** (models.Check) is something for an admin to try: what to do and what to expect, on which page and through
whose eyes, how long it takes, and why it exists (the note it came from, the change it checks). Claude writes them
(`scripts/feedback.py check …`, through `/api/checks` with the feedback key); the admin marks them:

- **Manage › askdnd › Testing** (`/manage/testing`): the Reader (1A): the checks on the left, grouped by what they need
  open (`SETUPS`), each with its minutes and where it came from; the chosen one on the right with its story, Go,
  Passed, Failed… and Skip.
- **A round** (▶ Start round): the checks in order, each on its own page, with the step card at the bottom right of
  every askdnd page (2A, `_check_card.html`, loaded by base.html while a round is open); Passed or Skip moves on.
- **Failed…** opens the feedback window (3A) with Something's broken picked and the check named; the note it sends
  marks the check failed and is tied to it (`failed`), so a failure is a feedback note like any other.

It's kept to itself so it can go to another project with Feedback (Board 5 of the mockup): its own table, its own
routes, and askdnd's people and pages only through `web`, `auth.is_admin` and the feedback key.
"""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, web
from app.auth import is_admin
from app.db import get_db
from app.models import Check, Feedback
from app.templating import templates

router = APIRouter()

# What a check needs open, in the order a round takes them (the Reader's groups)
SETUPS = {"laptop": "On your laptop, as you", "view_as": "Through View as", "iphone": "On your iPhone", "mac": "On your Mac",
          "player": "With a player", "claude": "Claude runs these"}
STATUSES = ("ready", "again", "failed", "fixed", "passed", "skipped", "claude")
SAYS = {"ready": "Ready", "again": "Fixed · try again", "failed": "Failed", "fixed": "Fix on its way", "passed": "Passed", "skipped": "Skipped", "claude": "Claude ran it"}
# The Reader's chips: which statuses each shows
SHOWS = {"ready": ("ready", "again"), "again": ("again",), "player": (), "failed": ("failed", "fixed"), "claude": ("claude",), "done": ("passed", "skipped")}
SHOW_OF = {"passed": "done", "skipped": "done", "ready": "ready", "failed": "failed"}  # (where a check marked so is listed)
SHOW_SAYS = {"ready": "Ready", "again": "Try again", "player": "With a player", "failed": "Failed", "claude": "Claude's", "done": "Done"}
TO_DO = ("ready", "again")  # what waits for the admin (the Manage menu's count)
PLAYER_DAYS = 3  # a check on a player's note is theirs to confirm first; yours after this many days (Brett's 6C)
DENIED = "Testing is for admins."
ROUND = "check_round"  # the session's open round: {"ids": [...], "i": n}


# ------------------------------------------------------------------ the engine's side


def _with_player(c: Check) -> bool:
    """A check on a player's note, still theirs to confirm (asked fewer than PLAYER_DAYS days ago)."""
    asked = c.asked_at or c.updated_at or datetime.now(UTC)
    return c.setup == "player" and c.status in TO_DO and (datetime.now(UTC) - asked).days < PLAYER_DAYS


def _for_admin(rows: list[Check]) -> list[Check]:
    """What's the admin's to try: not a player's still theirs, not one Claude runs on the Mac Mini's seats."""
    return [c for c in rows if not _with_player(c) and c.setup != "claude"]


def waiting(db: Session) -> int:
    """How many checks wait for an admin (ready, or fixed and ready to try again; a player's, once it has waited)."""
    return len(_for_admin(list(db.scalars(select(Check).where(Check.status.in_(TO_DO))))))


def for_note(db: Session, fb: Feedback, do: str = "", expect: str = "", admin_sent: bool = True) -> Check | None:
    """The check a broken note's fix comes with (Brett, Nov 16: every broken note gets its check), made when Claude marks
    it done with its PR: Fix on its way until the fix is live (`feedback.py check live`). One per note. A player's note
    is theirs to confirm (6C: setup "player"); an admin's goes to the queue."""
    if fb.kind == "idea" and not admin_sent:
        return None  # (a built idea isn't a fix for its sender to confirm)
    pr = fb.pr if fb.pr.startswith("https://") else ""
    said = next((m.get("text", "") for m in reversed(fb.thread or []) if m.get("to") == "sender"), "")
    known = db.scalars(select(Check).where((Check.feedback_id == fb.id) | (Check.failed_id == fb.id))).all()
    if known:  # (fixed again: the check that failed comes back, never a second one; the code review, Nov 16)
        for c in known:
            if c.status == "failed":
                c.pr, c.said = pr or c.pr, said or c.said
                mark(db, c, "fixed", who="claude")
        return None
    from urllib.parse import urlsplit

    page = urlsplit(fb.url or "")
    path = page.path + (f"?{page.query}" if page.query else "")
    path = path if local_path(path) else ""
    c = Check(title=(fb.title or (fb.text or "").split(".")[0])[:160] or f"Note {fb.id}", area=str((fb.context or {}).get("page") or "")[:80],
              setup="laptop" if admin_sent else "player", path=path[:500], do=do or "Try what your note was about, where you saw it.",
              expect=expect or "It works now.", minutes=2, feedback_id=fb.id, pr=pr, said=said,
              status="fixed", history=[])
    _note(c, "Fix on its way", "claude")
    db.add(c)
    return c


def player_check(db: Session, fb: Feedback) -> Check | None:
    """The check a player is asked about on their own note (Does it work now?), when its fix is live."""
    c = db.scalar(select(Check).where(Check.feedback_id == fb.id, Check.setup == "player"))
    return c if c is not None and c.status == "again" else None


def answered(db: Session, c: Check, works: bool, words: str = "") -> None:
    """The player's answer (6C): Yes passes it; Still broken fails it, and their words go to the note."""
    mark(db, c, "passed" if works else "failed", who="sender", said=words[:160])


def _note(c: Check, what: str, who: str) -> None:
    c.history = [*(c.history or []), {"at": datetime.now(UTC).isoformat(timespec="seconds"), "what": what, "who": who}]


def mark(db: Session, c: Check, status: str, who: str = "you", said: str = "") -> None:
    if status not in STATUSES:
        raise HTTPException(400, "Passed, failed, skipped or ready.")
    if status == "again" and c.status != "again":
        c.asked_at = datetime.now(UTC)  # (when it came back to be tried: a player's three days and their email count from it)
    c.status = status
    _note(c, SAYS[status] + (f": {said}" if said else ""), who)


def failed(request: Request, db: Session, check_id: int, fb: Feedback | None, prod_note: int | None = None) -> Check | None:
    """The note an admin sent with Failed… on a check: the check is failed and tied to it (3A), and a round moves on.
    On staging the note goes to askdnd.ai's queue: the check here says which (`prod_note`)."""
    c = db.get(Check, check_id)
    if c is None:
        return None
    c.failed_id = fb.id if fb is not None else None
    mark(db, c, "failed", said=f"note {fb.id}" if fb is not None else f"note {prod_note} on askdnd.ai")
    db.commit()
    return c


def on_round(request: Request, check_id: int) -> bool:
    """Whether this check is the round's current one (only then does marking it follow the round)."""
    r = _round(request)
    return bool(r) and r["i"] < len(r["ids"]) and r["ids"][r["i"]] == check_id


def local_path(p: str) -> bool:
    """An address on askdnd itself: starts with one /, never //, a backslash (browsers read /\\ as //) or a control
    character (the code review, Nov 16: a note's address made a check's link that left askdnd)."""
    return bool(p) and p.startswith("/") and not p.startswith("//") and "\\" not in p and not any(ord(ch) < 32 or ord(ch) == 127 for ch in p)


def ordered(rows: list[Check]) -> list[Check]:
    keys = list(SETUPS)
    return sorted(rows, key=lambda c: (keys.index(c.setup) if c.setup in keys else len(keys), c.place, c.id))


def view(c: Check) -> dict:
    """A check as the Reader and the card show it."""
    return {"id": c.id, "title": c.title, "area": c.area, "setup": c.setup, "group": SETUPS.get(c.setup, c.setup), "as_who": c.as_who, "as_character": c.as_character,
            "path": c.path, "do": [line for line in (c.do or "").splitlines() if line.strip()], "expect": c.expect, "minutes": c.minutes,
            "status": c.status, "says": SAYS.get(c.status, c.status), "feedback_id": c.feedback_id, "failed_id": c.failed_id, "pr": c.pr,
            "said": c.said, "history": c.history or []}


# ------------------------------------------------------------------ the round


def _round(request: Request) -> dict | None:
    r = request.session.get(ROUND)
    return r if isinstance(r, dict) and r.get("ids") else None


def _advance(request: Request, check_id: int) -> None:
    """The round moves past a check that was just marked (Passed, Skip, or the note Failed… sent)."""
    r = _round(request)
    if r and r["i"] < len(r["ids"]) and r["ids"][r["i"]] == check_id:
        r["i"] += 1
        request.session[ROUND] = r if r["i"] < len(r["ids"]) else None


def current(request: Request, db: Session) -> dict | None:
    """The round's check now ({check, n, of}), or None when there's no round open."""
    r = _round(request)
    if not r or r["i"] >= len(r["ids"]):
        request.session[ROUND] = None
        return None
    request.session[ROUND] = r
    c = db.get(Check, r["ids"][r["i"]])
    if c is None:
        request.session[ROUND] = None
        return None
    return {"check": view(c), "n": r["i"] + 1, "of": len(r["ids"])}


# ------------------------------------------------------------------ pages


@router.get("/manage/testing", response_class=HTMLResponse)
def page(request: Request, show: str = "ready", check: int = 0, db: Session = Depends(get_db)):
    """Manage › askdnd › Testing: the Reader of checks (1A)."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    show = show if show in SHOWS else "ready"
    counts = dict(db.execute(select(Check.status, func.count()).group_by(Check.status)).all())
    waiting_players = [c for c in db.scalars(select(Check).where(Check.setup == "player", Check.status.in_(TO_DO))) if _with_player(c)]
    players, players_again = len(waiting_players), sum(1 for c in waiting_players if c.status == "again")
    claudes = dict(db.execute(select(Check.status, func.count()).where(Check.setup == "claude").group_by(Check.status)).all())
    if show == "claude":  # (Claude's: the ones it runs on the Mac Mini, to run and run)
        rows = ordered(list(db.scalars(select(Check).where(Check.setup == "claude", Check.status.in_(("ready", "again", "claude"))))))
    else:
        rows = ordered(list(db.scalars(select(Check).where(Check.status.in_(SHOWS[show] if show != "player" else TO_DO)))))
        rows = [c for c in rows if _with_player(c)] if show == "player" else _for_admin(rows) if show in ("ready", "again") else rows
    items = [view(c) for c in rows]
    groups: dict[str, list[dict]] = {}
    for i in items:
        groups.setdefault(i["group"], []).append(i)
    picked = next((i for i in items if i["id"] == check), items[0] if items else None)
    notes = {f.id: f for f in db.scalars(select(Feedback).where(Feedback.id.in_({x for i in items for x in (i["feedback_id"], i["failed_id"]) if x})))}
    return templates.TemplateResponse(request, "testing.html", {
        "user": user, "show": show, "groups": groups, "picked": picked, "notes": notes,
        "chips": [(k, SHOW_SAYS[k], players if k == "player" else sum(claudes.get(s, 0) for s in ("ready", "again", "claude")) if k == "claude"
                   else sum(counts.get(s, 0) for s in SHOWS[k]) - (players if k == "ready" else players_again if k == "again" else 0)
                   - (sum(claudes.get(s, 0) for s in SHOWS[k]) if k in ("ready", "again") else 0)) for k in SHOWS],
        "ready_minutes": sum(i["minutes"] for i in items) if show == "ready" else 0, "round": current(request, db),
        "toast": request.session.pop("toast", None)})


@router.post("/manage/testing/round")
def start_round(request: Request, form=web.FormBody, db: Session = Depends(get_db)):
    """▶ Start round: the ready checks (or one group's), in order; opens the first one's page with its card."""
    _, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    group = str(form.get("setup") or "")
    rows = _for_admin(ordered(list(db.scalars(select(Check).where(Check.status.in_(TO_DO))))))
    ids = [c.id for c in rows if c.setup != "claude" and (not group or c.setup == group)]
    if not ids:
        request.session["toast"] = web.notice("Nothing ready to try.")
        return RedirectResponse("/manage/testing", status_code=303)
    request.session[ROUND] = {"ids": ids, "i": 0}
    return RedirectResponse(enter(request, db, db.get(Check, ids[0])), status_code=303)


@router.post("/manage/testing/{check_id:int}/go")
def go(request: Request, check_id: int, db: Session = Depends(get_db)):
    """Go (Brett, Nov 16: the card should come with it): this one check's page with its card, a round of one; marking it
    comes back to it in the Reader."""
    _, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    c = db.get(Check, check_id)
    if c is None:
        return web.not_found(request, "There's no such check.")
    request.session[ROUND] = {"ids": [c.id], "i": 0, "back": c.id}
    return RedirectResponse(enter(request, db, c), status_code=303)


@router.post("/manage/testing/round/stop")
def stop_round(request: Request):
    _, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    request.session[ROUND] = None
    return RedirectResponse(leave(request, "/manage/testing"), status_code=303)


def next_page(request: Request, db: Session, after: int, followed: bool = True) -> str:
    """Where to go once a check is marked: the round's next check's page when it was the round's, else back to that
    check in the Reader (a check marked from the list leaves a round where it was; the code review, Nov 16)."""
    if not followed:
        return f"/manage/testing?show=failed&check={after}"
    _advance(request, after)
    now = current(request, db)
    return enter(request, db, db.get(Check, now["check"]["id"])) if now else leave(request, f"/manage/testing?show=failed&check={after}")


def enter(request: Request, db: Session, c: Check | None) -> str:
    """A check's page, seen through its eyes (Brett's Board 1: Go turns on View as for that person first): View as for
    its character's player, or your own view. Who may be viewed as is View as's own rule (`view_as.refusal`: never
    yourself, never a player you're the DM of); refused, the page opens as you, with why."""
    from app import view_as
    from app.models import Character, User

    target = None
    if c is not None and c.as_character:
        ch = db.get(Character, c.as_character)
        owner = db.get(User, ch.owner_id) if ch is not None and ch.owner_id else None
        real = ((request.session.get("user") or {}).get("email") or "").lower()
        if owner is None:
            request.session["toast"] = web.notice("Its character has no player in askdnd, so it opens as you.", "warn")
        elif why := view_as.refusal(real, owner.email):
            request.session["toast"] = web.notice(f"{why} It opens as you.", "warn")
        else:
            target = {"email": owner.email.lower(), "name": (owner.name if owner.name and owner.name != owner.email else None) or owner.email}
    if target:
        request.session["view_as"] = target
        request.session["view_as_back"] = "/manage/testing"
        request.session["view_as_testing"] = True  # (Testing's own: leave() ends it, never one started from Accounts)
    else:
        leave(request, "")
    return _page_of(c)


def leave(request: Request, back: str) -> str:
    """Back to your own view, at `back` (a round's end, or Go's one check marked): a View as Testing turned on ends; one
    the admin started from Accounts stays."""
    if request.session.pop("view_as_testing", None):
        request.session.pop("view_as", None)
    return back


def _page_of(c: Check | None) -> str:
    return c.path if c is not None and local_path(c.path) else "/manage/testing"


@router.post("/manage/testing/{check_id:int}")
def result(request: Request, check_id: int, form=web.FormBody, db: Session = Depends(get_db)):
    """Passed, Skip or Ready again on a check (from the Reader or the card). In a round, Passed and Skip go on to the
    next check's page; the last one comes back here."""
    _, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    c = db.get(Check, check_id)
    if c is None:
        return web.not_found(request, "There's no such check.")
    status = str(form.get("result") or "")
    if status not in ("passed", "skipped", "ready"):
        raise HTTPException(400, "Passed, skipped or ready.")
    mark(db, c, status)
    db.commit()
    back = f"/manage/testing?show={SHOW_OF.get(status, 'ready')}&check={c.id}"  # (back to it, where it now is: the code review)
    if not on_round(request, c.id):  # (marked from the list: a round stays where it was)
        request.session["toast"] = web.notice(f"{SAYS[status]}: {c.title}")
        return RedirectResponse(back, status_code=303)
    single = bool(_round(request).get("back"))  # (Go: a round of one)
    _advance(request, c.id)
    now = current(request, db)
    if now:
        return RedirectResponse(enter(request, db, db.get(Check, now["check"]["id"])), status_code=303)
    request.session["toast"] = web.notice(f"{SAYS[status]}: {c.title}" if single else "That's the round done.")
    return RedirectResponse(leave(request, back if single else "/manage/testing"), status_code=303)


@router.get("/manage/testing/card", response_class=HTMLResponse)
def card(request: Request, db: Session = Depends(get_db)):
    """The step card (2A) for the round's check, loaded on every page while a round is open."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    now = current(request, db)
    if now is None:
        return HTMLResponse("", status_code=204)
    return templates.TemplateResponse(request, "_check_card.html", {"user": user, **now})


# ------------------------------------------------------------------ Claude's side (the feedback key)


def _claude(key: str | None) -> None:
    if not config.FEEDBACK_KEY or not key or not secrets.compare_digest(key, config.FEEDBACK_KEY):
        raise HTTPException(404)


FIELDS = {"title": 160, "area": 80, "setup": 20, "as_who": 120, "path": 500, "do": 4000, "expect": 4000, "pr": 300, "said": 4000}


def _fill(db: Session, c: Check, body: dict) -> None:
    for k, n in FIELDS.items():
        if k in body:
            setattr(c, k, str(body.get(k) or "")[:n])
    if c.setup not in SETUPS:
        raise HTTPException(400, f"setup: one of {', '.join(SETUPS)}")
    if c.path and not local_path(c.path):
        raise HTTPException(400, "path: an askdnd page, starting with /")  # (it's Go's link and a round's redirect)
    if c.pr and not c.pr.startswith("https://"):
        raise HTTPException(400, "pr: an https:// link")
    for k in ("minutes", "place"):
        if k in body:
            try:
                setattr(c, k, max(0, min(240, int(body[k]))))
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k}: a number") from None
    if "as_character" in body:
        from app.models import Character

        cid = int(body["as_character"]) if str(body.get("as_character") or "").isdigit() else None
        if cid is not None and db.get(Character, cid) is None:
            raise HTTPException(400, f"There's no character {cid}.")
        c.as_character = cid
    if "feedback_id" in body:
        fid = int(body["feedback_id"]) if str(body.get("feedback_id") or "").isdigit() else None
        if fid is not None and db.get(Feedback, fid) is None:
            raise HTTPException(400, f"There's no note {fid}.")
        c.feedback_id = fid


@router.get("/api/checks")
def api_list(status: str = ",".join(STATUSES), x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    _claude(x_feedback_key)
    wanted = [s for s in status.split(",") if s in STATUSES] or list(STATUSES)
    return JSONResponse({"items": [view(c) for c in ordered(list(db.scalars(select(Check).where(Check.status.in_(wanted)))))]},
                        headers={"Cache-Control": "no-store"})


@router.post("/api/checks")
def api_add(body=web.JsonBody, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude adds a check: title, area, setup, as_who, path, do (a line a step), expect, minutes, place, feedback_id, pr."""
    _claude(x_feedback_key)
    body = body if isinstance(body, dict) else {}
    if not str(body.get("title") or "").strip():
        raise HTTPException(400, "A check needs its title.")
    c = Check(title="", setup="laptop", status="ready", history=[])
    _fill(db, c, body)
    _note(c, "Ready", "claude")
    db.add(c)
    db.commit()
    return JSONResponse(view(c))


@router.post("/api/checks/{check_id:int}")
def api_change(check_id: int, body=web.JsonBody, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude changes a check (any field above), or moves it on (`status`, with `said`): again once a fix is live,
    claude with what a Mac Mini run found."""
    _claude(x_feedback_key)
    body = body if isinstance(body, dict) else {}
    c = db.get(Check, check_id)
    if c is None:
        raise HTTPException(404)
    _fill(db, c, body)
    if body.get("status"):
        mark(db, c, str(body["status"]), who="claude", said=str(body.get("said") or "")[:300])
    db.commit()
    return JSONResponse(view(c))
