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

**Areas** (Working with Claude, Brett's picks Nov 17, docs/mockups/working-together/): Claude sorts what a round sent
into areas (`/api/areas`, `feedback.py area`), the notes and checks fixed and tried together; Brett drags them into his
order on **Where it stands**, which shows where each is (`stage`) and whether Claude is listening (app/for_claude.py).
One area at a time is in Claude's hands (`fixing`). For you lists the checks by area, in that order, and a round
takes them so (4A); what a check needs open is a tag on it.

It's kept to itself so it can go to another project with Feedback (Board 5 of the mockup): its own table, its own
routes, and askdnd's people and pages only through `web`, `auth.is_admin` and the feedback key.
"""

import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, for_claude, web
from app.auth import is_admin
from app.db import get_db
from app.models import Area, Check, Feedback
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
FOR_YOU = ("ready", "again", "player", "failed")  # (For you's chips; Claude ran and Done are tabs of their own, as is Where it stands)
TABS = {"ready": "For you", "areas": "Where it stands", "claude": "Claude ran", "done": "Done"}
NEEDS = {"view_as": "View as", "iphone": "iPhone", "mac": "Mac", "player": "A player"}  # (what a check needs open, as its tag)
STAGES = ("Found", "Questions", "Claude fixing", "Ready for you", "Done")  # (where an area is: `stage`)
NOTE_OPEN = ("review", "new", "question", "planned")
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
              status="fixed", history=[], area_id=fb.area_id)
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
    if fb is not None and fb.area_id is None:
        fb.area_id = c.area_id  # (a failure is about its check's area)
    for_claude.tell(db, "check", f"Check {c.id} ({c.title}): Failed, " + (f"note {fb.id}: " + " ".join((fb.text or "").split())[:240] if fb is not None
                                                                         else f"note {prod_note} on askdnd.ai"),
                    feedback_id=fb.id if fb is not None else None, check_id=c.id, area_id=c.area_id)
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


def area_order(db: Session) -> list[Area]:
    """The areas in the order they run: the one in Claude's hands, then Brett's order (`place`)."""
    return sorted(db.scalars(select(Area)), key=lambda a: (not a.fixing, a.place, a.id))


def ordered(db: Session, rows: list[Check]) -> list[Check]:
    """Checks in the order a round takes them (Brett's 4A): by area, in the areas' order, then each area's own order
    (`place`, the page order Claude gives them); checks in no area after."""
    at = {a.id: i for i, a in enumerate(area_order(db))}
    return sorted(rows, key=lambda c: (at.get(c.area_id, len(at)), c.place, c.id))


def view(c: Check, areas: dict[int, str] | None = None) -> dict:
    """A check as the Reader and the card show it; `group` is its area's title (`areas`), else what it needs open."""
    group = (areas or {}).get(c.area_id) or ("Claude runs these" if c.setup == "claude" else "Not in an area yet")
    return {"id": c.id, "title": c.title, "area": c.area, "area_id": c.area_id, "setup": c.setup, "group": group,
            "needs": NEEDS.get(c.setup, ""), "as_who": c.as_who, "as_character": c.as_character,
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


def stage(a: Area, notes: list[Feedback], checks: list[Check]) -> int:
    """Where an area is (STAGES), worked out from its notes and checks: in Claude's hands while `fixing` (or a fix of
    it on its way to askdnd.ai); Questions while Claude waits on an answer; Ready for you while a check waits for you;
    Done once every note is closed and every check passed or skipped; else Found, waiting its turn."""
    if a.fixing:
        return 2
    if any(f.status == "question" for f in notes):
        return 1
    if _for_admin([c for c in checks if c.status in TO_DO]):
        return 3
    if any(c.status == "fixed" for c in checks):
        return 2
    if (notes or checks) and all(f.status not in NOTE_OPEN for f in notes) and all(c.status in ("passed", "skipped", "claude") for c in checks):
        return 4
    return 0


def areas_view(db: Session) -> list[dict]:
    """Every area with its notes and checks and where it is, in the order they run (Where it stands, `/api/areas`)."""
    out = []
    from sqlalchemy.orm import load_only

    notes = db.scalars(select(Feedback).options(load_only(Feedback.id, Feedback.title, Feedback.text, Feedback.status, Feedback.kind, Feedback.area_id))
                       .where(Feedback.area_id.is_not(None))).all()  # (never a note's page or context: only what the rows show)
    checks = db.scalars(select(Check).where(Check.area_id.is_not(None))).all()
    for a in area_order(db):
        ns, cs = [f for f in notes if f.area_id == a.id], [c for c in checks if c.area_id == a.id]
        i = stage(a, ns, cs)
        asked, ready = sum(1 for f in ns if f.status == "question"), len(_for_admin([c for c in cs if c.status in TO_DO]))
        nxt = ("Claude's on it" if a.fixing else "On its way to askdnd.ai") if i == 2 else \
            f"{asked} question{'s' if asked != 1 else ''} for you" if i == 1 else f"{ready} check{'s' if ready != 1 else ''} for you" if i == 3 else \
            "Done" if i == 4 else "Waits its turn"
        out.append({"id": a.id, "title": a.title, "place": a.place, "fixing": a.fixing, "stage": i, "says": STAGES[i], "next": nxt,
                    "yours": i in (1, 3), "track": [{"label": x, "state": "done" if j < i or i == 4 else ("you" if i in (1, 3) else "now") if j == i else "todo"}
                                                    for j, x in enumerate(STAGES)],
                    "notes": [{"id": f.id, "title": f.title or (f.text or "")[:60], "status": f.status, "kind": f.kind} for f in sorted(ns, key=lambda f: f.id)],
                    "checks": [{"id": c.id, "title": c.title, "status": c.status} for c in sorted(cs, key=lambda c: (c.place, c.id))]})
    return out


def unsorted(db: Session) -> list[Feedback]:
    """Notes with Claude in no area yet (Claude sorts them after a round): not a player's still waiting for an admin, nor
    an idea planned on the Roadmap."""
    return list(db.scalars(select(Feedback).where(Feedback.area_id.is_(None), Feedback.status.in_(("new", "question"))).order_by(Feedback.id)))


@router.get("/manage/testing", response_class=HTMLResponse)
def page(request: Request, show: str = "ready", check: int = 0, db: Session = Depends(get_db)):
    """Manage › askdnd › Testing: For you, the Reader of checks by area (1A, 4A); Where it stands, every area; Claude
    ran; Done."""
    user, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    show = show if show in SHOWS or show == "areas" else "ready"
    titles = {a.id: a.title for a in db.scalars(select(Area))}
    base = {"user": user, "show": show, "tab": show if show in TABS else "ready", "tabs": TABS, "round": current(request, db),
            "toast": request.session.pop("toast", None), "listening": for_claude.listening(db), "for_you": waiting(db)}
    if show == "areas":
        return templates.TemplateResponse(request, "testing.html", {**base, "areas": areas_view(db), "unsorted": unsorted(db),
                                                                    "groups": {}, "picked": None, "notes": {}, "chips": []})
    counts = dict(db.execute(select(Check.status, func.count()).group_by(Check.status)).all())
    waiting_players = [c for c in db.scalars(select(Check).where(Check.setup == "player", Check.status.in_(TO_DO))) if _with_player(c)]
    players, players_again = len(waiting_players), sum(1 for c in waiting_players if c.status == "again")
    claudes = dict(db.execute(select(Check.status, func.count()).where(Check.setup == "claude").group_by(Check.status)).all())
    if show == "claude":  # (Claude's: the ones it runs on the Mac Mini, to run and run)
        rows = ordered(db, list(db.scalars(select(Check).where(Check.setup == "claude", Check.status.in_(("ready", "again", "claude"))))))
    else:
        rows = ordered(db, list(db.scalars(select(Check).where(Check.status.in_(SHOWS[show] if show != "player" else TO_DO)))))
        rows = [c for c in rows if _with_player(c)] if show == "player" else _for_admin(rows) if show in ("ready", "again") else rows
    items = [view(c, titles) for c in rows]
    groups: dict[str, dict] = {}  # (by area id, never by its title: two areas may share one)
    for i in items:
        groups.setdefault(f"a{i['area_id']}" if i["area_id"] else i["group"], {"title": i["group"], "area": i["area_id"], "rows": []})["rows"].append(i)
    picked = next((i for i in items if i["id"] == check), items[0] if items else None)
    notes = {f.id: f for f in db.scalars(select(Feedback).where(Feedback.id.in_({x for i in items for x in (i["feedback_id"], i["failed_id"]) if x})))}
    return templates.TemplateResponse(request, "testing.html", {**base, "groups": groups, "picked": picked, "notes": notes,
        "chips": [(k, SHOW_SAYS[k], players if k == "player"
                   else sum(counts.get(s, 0) for s in SHOWS[k]) - (players if k == "ready" else players_again if k == "again" else 0)
                   - (sum(claudes.get(s, 0) for s in SHOWS[k]) if k in ("ready", "again") else 0)) for k in FOR_YOU],
        "ready_minutes": sum(i["minutes"] for i in items) if show == "ready" else 0})


@router.post("/manage/testing/round")
def start_round(request: Request, form=web.FormBody, db: Session = Depends(get_db)):
    """▶ Start round: the ready checks in order, area by area (or one area's: ▶ Just this area); opens the first one's
    page with its card."""
    _, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    area = int(form.get("area")) if str(form.get("area") or "").isdigit() else None
    rows = _for_admin(ordered(db, list(db.scalars(select(Check).where(Check.status.in_(TO_DO))))))
    ids = [c.id for c in rows if area is None or c.area_id == area]
    if not ids:
        request.session["toast"] = web.notice("Nothing ready to try.")
        return RedirectResponse("/manage/testing", status_code=303)
    request.session[ROUND] = {"ids": ids, "i": 0}
    return RedirectResponse(enter(request, db, db.get(Check, ids[0])), status_code=303)


@router.post("/manage/testing/areas/order")
def area_order_set(request: Request, form=web.FormBody, db: Session = Depends(get_db)):
    """Brett drags the areas into his order on Where it stands (7A): the order goes to Claude's inbox."""
    _, denied = web.require(request, is_admin, DENIED)
    if denied:
        return denied
    ids = [int(k) for k in form.getlist("keys") if str(k).isdigit()]
    known = {a.id: a for a in db.scalars(select(Area).where(Area.id.in_(ids)))} if ids else {}
    order = [known[i] for i in dict.fromkeys(ids) if i in known]
    if not order:
        raise HTTPException(400, "Which areas, in order.")
    for n, a in enumerate(order):
        a.place = n
    for_claude.tell(db, "order", "Brett put the areas in this order: " + ", ".join(a.title for a in order))
    db.commit()
    return JSONResponse({"ok": True})


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
    for_claude.tell(db, "check", f"Check {c.id} ({c.title}): {SAYS[status] if status != 'ready' else 'back to try again'}", check_id=c.id, area_id=c.area_id)
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
    if "area_id" in body:
        aid = int(body["area_id"]) if str(body.get("area_id") or "").isdigit() else None
        if aid is not None and db.get(Area, aid) is None:
            raise HTTPException(400, f"There's no area {aid}.")
        c.area_id = aid
    if "feedback_id" in body:
        fid = int(body["feedback_id"]) if str(body.get("feedback_id") or "").isdigit() else None
        if fid is not None and db.get(Feedback, fid) is None:
            raise HTTPException(400, f"There's no note {fid}.")
        c.feedback_id = fid


@router.get("/api/checks")
def api_list(status: str = ",".join(STATUSES), x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    _claude(x_feedback_key)
    wanted = [s for s in status.split(",") if s in STATUSES] or list(STATUSES)
    titles = {a.id: a.title for a in db.scalars(select(Area))}
    return JSONResponse({"items": [view(c, titles) for c in ordered(db, list(db.scalars(select(Check).where(Check.status.in_(wanted)))))]},
                        headers={"Cache-Control": "no-store"})


@router.post("/api/checks")
def api_add(body=web.JsonBody, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude adds a check: title, area (where on askdnd), area_id (its area), setup, as_who, path, do (a line a step),
    expect, minutes, place (its order in the area), feedback_id, pr."""
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


def _ids(body: dict, key: str) -> list[int]:
    v = body.get(key) or []
    if not isinstance(v, list) or not all(type(x) is int for x in v):
        raise HTTPException(400, f"{key}: a list of ids")
    return v


def _place_in(db: Session, a: Area, body: dict) -> None:
    """Notes and checks into (or out of) an area: notes, checks add them; drop_notes, drop_checks take them out."""
    for key, model in (("notes", Feedback), ("checks", Check)):
        ids = _ids(body, key)
        rows = db.scalars(select(model).where(model.id.in_(ids))).all() if ids else []
        if len(rows) != len(set(ids)):
            raise HTTPException(400, f"{key}: no such " + ", ".join(str(i) for i in set(ids) - {r.id for r in rows}))
        for r in rows:
            r.area_id = a.id
        for r in db.scalars(select(model).where(model.id.in_(_ids(body, "drop_" + key)), model.area_id == a.id)) if body.get("drop_" + key) else []:
            r.area_id = None


@router.get("/api/areas")
def api_areas(x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Every area with its notes, checks and where it is, in the order they run; and the open notes in none yet."""
    _claude(x_feedback_key)
    return JSONResponse({"areas": areas_view(db), "unsorted": [{"id": f.id, "title": f.title or (f.text or "")[:60], "kind": f.kind, "status": f.status}
                                                                for f in unsorted(db)]}, headers={"Cache-Control": "no-store"})


@router.post("/api/areas")
def api_area_add(body=web.JsonBody, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude makes an area: title, and the notes and checks in it; it goes last in Brett's order."""
    _claude(x_feedback_key)
    body = body if isinstance(body, dict) else {}
    title = str(body.get("title") or "").strip()[:80]
    if not title:
        raise HTTPException(400, "An area needs its title.")
    a = Area(title=title, place=(db.scalar(select(func.max(Area.place))) or 0) + 1, fixing=False)
    db.add(a)
    db.flush()
    _place_in(db, a, body)
    db.commit()
    return JSONResponse(next(x for x in areas_view(db) if x["id"] == a.id))


@router.post("/api/areas/{area_id:int}")
def api_area_change(area_id: int, body=web.JsonBody, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude changes an area: title, place, notes/checks in or out, and `fixing` (true when it takes the area up, false
    when it's merged and live). One area at a time is in Claude's hands: taking up a second is refused (409)."""
    _claude(x_feedback_key)
    body = body if isinstance(body, dict) else {}
    a = db.get(Area, area_id)
    if a is None:
        raise HTTPException(404)
    if "title" in body and str(body["title"] or "").strip():
        a.title = str(body["title"]).strip()[:80]
    if "place" in body:
        if type(body["place"]) is not int:
            raise HTTPException(400, "place: a number")
        a.place = body["place"]
    if "fixing" in body:
        if body["fixing"] is True:
            other = db.scalar(select(Area).where(Area.fixing.is_(True), Area.id != a.id))
            if other is not None:
                raise HTTPException(409, f"Area {other.id} ({other.title}) is in Claude's hands: finish it first (fixing false).")
        a.fixing = body["fixing"] is True
    _place_in(db, a, body)
    db.commit()
    return JSONResponse(next(x for x in areas_view(db) if x["id"] == a.id))
