"""Found, Fixed, Tried for Claude, the staging relay and the Mac Mini (`/api/fft`), each with its own key (keys.py).

What Claude reads keeps the table's rules (brief v2 §6): nothing a player wrote until an admin approves it (T1); first
names only and never an email (T2); every text says who wrote it and comes quoted, as evidence never instructions
(T3); the page as drawn only when asked for (T4); a read mark per listener (T8). Every change goes through rules.py."""

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, web
from app.db import get_db
from app.fft import keys, rules, sending, steps, taxonomy, views
from app.fft.models import (
    FftArea,
    FftCheck,
    FftCheckIssue,
    FftCheckVersion,
    FftIssue,
    FftItem,
    FftLine,
    FftNote,
    FftPicture,
    FftPull,
    FftQuestion,
    FftTry,
)
from app.models import Character

router = APIRouter(prefix="/api/fft")
NO_STORE = {"Cache-Control": "no-store"}


def _ok(data) -> JSONResponse:
    return JSONResponse(data, headers=NO_STORE)


def _rule(e: rules.RuleError):
    raise HTTPException(409 if e.code in ("stale", "busy", "late") else 400, e.words) from e


def _int(v, what: str) -> int:
    if type(v) is not int:
        raise HTTPException(400, f"{what}: a number")
    return v


def _str(body: dict, k: str, n: int = 4000, need: bool = False) -> str:
    v = body.get(k, "")
    if not isinstance(v, str):
        raise HTTPException(400, f"{k}: words")
    if need and not v.strip():
        raise HTTPException(400, f"{k}: needed")
    return v[:n]


def _steps(body: dict) -> list[str]:
    v = body.get("steps")
    if isinstance(v, str):
        v = [s for s in v.splitlines() if s.strip()]
    if not isinstance(v, list) or not v or not all(isinstance(s, str) and s.strip() for s in v):
        raise HTTPException(400, "steps: a list of steps")
    wrong = steps.step_problems("\n".join(v))
    if wrong:
        raise HTTPException(400, " ".join(wrong) + " (docs/testing-guide.md)")
    return [s.strip()[:500] for s in v]


# ------------------------------------------------------------------ what Claude reads (T1–T4)


def _by(note: FftNote) -> str:
    return f"{note.first_name or 'Someone'} ({note.role})"


def _quoted(text: str, by: str) -> dict:
    return {"by": by, "quoted": text}


def _line(line: FftLine, note: FftNote | None) -> dict:
    by = {"claude": "Claude", "admin": "An admin", "askdnd": "askdnd"}.get(line.who) or (_by(note) if note else "Its sender")
    return {"id": line.id, "at": line.created_at.isoformat() if line.created_at else "", "to": line.to, **_quoted(line.text, by)}


def note_view(db: Session, note: FftNote, page: bool = False) -> dict:
    lines = db.scalars(select(FftLine).where(FftLine.note_id == note.id, FftLine.approved.is_(True)).order_by(FftLine.id))
    pics = db.scalars(select(FftPicture.id).where(FftPicture.note_id == note.id, FftPicture.safe_key.isnot(None)))
    out = {"id": note.id, "kind": note.kind, "state": note.state, "filed_as": note.filed_as, "issue_id": note.issue_id,
           "idea_id": note.idea_id, "page": note.page, "url": note.url, "at": note.created_at.isoformat() if note.created_at else "",
           "text": _quoted(note.text, _by(note)), "context": note.context or {}, "lines": [_line(x, note) for x in lines],
           "pictures": list(pics), "html_size": len(note.html or "")}
    return out | ({"html": note.html} if page else {})


def _approved_note(db: Session, note_id: int) -> FftNote:
    """T1: a note an admin hasn't filed (waiting, or declined) isn't there for Claude."""
    note = db.get(FftNote, note_id)
    if note is None or note.state != "filed":
        raise HTTPException(404, "No such note, or no admin has approved it.")
    return note


def issue_view(db: Session, issue: FftIssue, full: bool = True) -> dict:
    out = {"id": issue.id, "title": issue.title, "state": issue.state, "turn": rules.ISSUE_TURN[issue.state], "area_id": issue.area_id,
           "feature": issue.feature, "feature_path": taxonomy.path(issue.feature), "kind": issue.kind, "pr": issue.pr, "reopened": issue.reopened, "close_reason": issue.close_reason, "from_player": issue.from_player,
           "confirm_by_player": bool(issue.confirm_by)}
    if full:
        notes = db.scalars(select(FftNote).where(rules.on_issue(issue.id), FftNote.state == "filed").order_by(FftNote.id))
        lines = db.scalars(select(FftLine).where(FftLine.issue_id == issue.id, FftLine.approved.is_(True)).order_by(FftLine.id))
        out |= {"notes": [note_view(db, n) for n in notes], "lines": [_line(x, None) for x in lines],
                "checks": list(db.scalars(select(FftCheckIssue.check_id).where(FftCheckIssue.issue_id == issue.id))),
                "may_merge": dict(zip(("ok", "why"), rules.may_merge(db, issue), strict=True))}
    return out


def check_view(db: Session, check: FftCheck) -> dict:
    v = db.scalar(select(FftCheckVersion).where(FftCheckVersion.check_id == check.id, FftCheckVersion.version == check.version))
    return {"id": check.id, "title": check.title, "area_id": check.area_id, "version": check.version, "devices": check.devices,
            "path": v.path if v else "", "steps": v.steps if v else [], "expect": v.expect if v else "", "why": v.why if v else "",
            "before": v.before if v else "", "now": v.now if v else "", "people": check.people,
            "preflight": check.preflight, "retired": check.retired, **rules.check_state(db, check),
            "issues": list(db.scalars(select(FftCheckIssue.issue_id).where(FftCheckIssue.check_id == check.id))),
            "tries": [{"id": t.id, "version": t.version, "result": t.result, "cant": t.cant_kind, "why": t.why, "device": t.device,
                       "where": t.where, "at": t.created_at.isoformat() if t.created_at else ""}  # (what was said with a mark reaches Claude:
                      for t in db.scalars(select(FftTry).where(FftTry.check_id == check.id).order_by(FftTry.id.desc()).limit(3))]}  # "the check is wrong" with why, Nov 24)


# ------------------------------------------------------------------ reading


@router.get("/inbox")
def inbox(listener: str = "main", peek: int = 0, area: int = 0, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """What this listener hasn't read (T8): each listener its own read mark; an area's own listener hears only it."""
    li = rules.listener(db, listener, area_id=area or None)
    actor = keys.require(db, x_fft_key, "read")
    rules.heartbeat(db, f"{actor.name}:{listener}")  # (the session's own listener is its check-in: its claim stays alive)
    rows = [e for e in rules.unread(db, li, peek=bool(peek)) if rules.heard(e, actor.name)]
    out = [{"id": e.id, "at": e.at.isoformat() if e.at else "", "kind": e.kind, "thing": e.thing, "thing_id": e.thing_id,
            "area_id": e.area_id, "says": views.event_words(e)} for e in rows]
    db.commit()
    return _ok({"items": out, "listening": True})


WAIT_MAX = 25  # seconds a wait is held open: under Railway's and urllib's limits, with room to spare


@router.get("/inbox/wait")
def inbox_wait(listener: str = "main", area: int = 0, seconds: int = WAIT_MAX, x_fft_key: str | None = Header(default=None),
               db: Session = Depends(get_db)):
    """The inbox's peek, held open until something is new (Brett, Nov 20: "is your communication ... very efficient?"):
    Claude's `feedback.py wait` hears a change within moments instead of on its next 30-second ask. A plain route, on a
    worker thread: it waits on the same live messages pages hear (app/fft/live.py, `realtime.heard`), holding no
    database connection meanwhile (each read commits), then lets the change settle (rules.SETTLE) before reading."""
    import time

    from app import realtime, timing

    actor = keys.require(db, x_fft_key, "read")
    rules.heartbeat(db, f"{actor.name}:{listener}")  # (a waiting session is alive: its claim runs on; peek's commit keeps it)

    def peek() -> list[dict]:
        li = rules.listener(db, listener, area_id=area or None)
        rows = [e for e in rules.unread(db, li, peek=True) if rules.heard(e, actor.name)]
        out = [{"id": e.id, "at": e.at.isoformat() if e.at else "", "kind": e.kind, "thing": e.thing, "thing_id": e.thing_id,
                "area_id": e.area_id, "says": views.event_words(e)} for e in rows]
        db.commit()  # (gives the connection back while it waits)
        return out

    items, until = peek(), time.monotonic() + max(1, min(seconds, WAIT_MAX))
    while not items and (left := until - time.monotonic()) > 0:
        with timing.step(timing.HELD):  # (held open by design: never a slow request)
            woke = realtime.heard(realtime.EVERYONE, left)
        if woke:
            time.sleep(rules.SETTLE.total_seconds() + 0.5)  # (read only once it has settled)
            items = peek()
    return _ok({"items": items, "listening": True})


@router.get("/next")
def next_work(x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """R15: what Claude takes next, why each item above it was skipped, and what waits on Brett."""
    keys.require(db, x_fft_key, "read")
    rules.confirm_due(db)
    pick = rules.pick_next(db)
    waiting = []
    for i in db.scalars(select(FftIssue).where(FftIssue.state.in_(("asks", "merge_ok")))):
        waiting.append({"issue": i.id, "title": i.title, "why": "Claude asks" if i.state == "asks" else "your OK to merge"})
    waiting += [{"item": it.id, "title": it.title, "why": it.next_step} for it in db.scalars(select(FftItem).where(FftItem.next_whose == "brett"))]
    waiting += [{"notes_to_approve": n} for n in [len(list(db.scalars(select(FftNote.id).where(FftNote.state == "waiting"))))] if n]
    db.commit()  # (the three days' hand-off, R5)
    nxt = ({"area_id": pick.area.id, "title": pick.why} if pick.area else  # (a Roadmap build with no plan of its own: itself, issue 62)
           {"item_id": pick.item.id, "title": pick.why} if pick.item else None)
    if nxt and pick.item:
        nxt["item_id"] = pick.item.id
    return _ok({"next": nxt, "blocker": pick.blocker,
                "skipped": [{"what": w, "why": y} for w, y in pick.skipped], "waiting_on_brett": waiting,
                "round_open": rules.holding_round(db) is not None})  # (a sitting that holds; ▶ Try it's never does)


@router.get("/speed")
def speed_week(days: int = 7, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Each route's time on askdnd.ai over the last `days` days, slowest tenth first (app/speed.py)."""
    from app import speed

    keys.require(db, x_fft_key, "read")
    return _ok({"routes": speed.week(db, max(1, min(days, 60))), "slow_p90_ms": speed.SLOW_P90_MS})


@router.get("/notes")
def notes(x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """The notes admins have filed (T1: never one waiting or declined)."""
    keys.require(db, x_fft_key, "read")
    rows = db.scalars(select(FftNote).where(FftNote.state == "filed").order_by(FftNote.id))
    return _ok({"items": [note_view(db, n) for n in rows]})


@router.get("/notes/{note_id:int}")
def note(note_id: int, page: int = 0, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    keys.require(db, x_fft_key, "read")
    return _ok(note_view(db, _approved_note(db, note_id), page=bool(page)))


@router.post("/notes/{note_id:int}")
def note_answer(note_id: int, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A question someone sent, answered (do: answer, words): its sender reads it on Notes you sent (Brett's round,
    Nov 18: a question filed for Claude to answer had no way to be). Only a question that's waiting."""
    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    n = _approved_note(db, note_id)
    if _str(body, "do", 20) != "answer":
        raise HTTPException(400, "do: answer")
    if n.filed_as != "question":
        raise HTTPException(409, f"It's filed as {n.filed_as or 'nothing yet'}, not a question waiting for its answer.")
    try:
        rules.answer_note(db, actor.name, n, _str(body, "words", need=True))
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(note_view(db, n))


@router.get("/issues")
def issues(state: str = "", area: int = 0, feature: str = "", x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    keys.require(db, x_fft_key, "read")
    q = select(FftIssue).order_by(FftIssue.id)
    wanted = [s for s in state.split(",") if s in rules.ISSUE_STATES]
    if wanted:
        q = q.where(FftIssue.state.in_(wanted))
    if area:
        q = q.where(FftIssue.area_id == area)
    if feature:
        q = q.where(FftIssue.feature == feature)
    return _ok({"items": [issue_view(db, i, full=False) for i in db.scalars(q)]})


@router.get("/issues/{issue_id:int}")
def issue(issue_id: int, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    keys.require(db, x_fft_key, "read")
    return _ok(issue_view(db, db.get(FftIssue, issue_id) or _missing()))


@router.get("/checks")
def checks(area: int = 0, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    keys.require(db, x_fft_key, "read")
    q = select(FftCheck).order_by(FftCheck.id)
    if area:
        q = q.where(FftCheck.area_id == area)
    return _ok({"items": [check_view(db, c) for c in db.scalars(q)]})


@router.get("/checks/waiting")
def checks_waiting(x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """The pull requests checks wait on (Nov 20): `feedback.py live` asks after each deploy, so a check whose change no
    open issue names still reaches For you once its pull request is live."""
    from app.fft.models import FftCheckWait

    keys.require(db, x_fft_key, "read")
    return _ok({"prs": sorted(set(db.scalars(select(FftCheckWait.pr))))})


@router.get("/areas")
def areas(x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    keys.require(db, x_fft_key, "read")
    out = []
    for item in db.scalars(select(FftItem).order_by(FftItem.place, FftItem.id)):
        out.append({"item": item.id, "title": item.title, "section": item.section, "standing": item.standing, "next_whose": item.next_whose,
                    "areas": [{"id": a.id, "key": a.key, "title": a.title, "turn": rules.area_turn(db, a), "lane": rules.lane_of(a), "round": a.round_no, "locked_by": a.lock_owner,
                               "issues": [i.id for i in rules.area_open_issues(db, a)], "checks": [c.id for c in rules.area_checks(db, a)]}
                              for a in db.scalars(select(FftArea).where(FftArea.item_id == item.id, FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id))]})
    return _ok({"items": out})


@router.get("/gaps")
def gaps(x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """What Claude left half done (views.gaps): Claude Code's end-of-turn hook reads it."""
    keys.require(db, x_fft_key, "read")
    return _ok({"items": [g | {"since": g["since"].isoformat()} for g in views.gaps(db)]})


@router.get("/questions")
def questions(open: int = 1, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    keys.require(db, x_fft_key, "read")
    q = select(FftQuestion).order_by(FftQuestion.id)
    if open:
        q = q.where(FftQuestion.answered_at.is_(None))
    return _ok({"items": [{"id": x.id, "about": x.about, "about_id": x.about_id, "text": x.text, "choices": x.choices, "mine": x.mine,
                           "answer_choice": x.answer_choice, "answer": _quoted(x.answer_text, "Brett") if x.answer_text else None,
                           "answered": x.answered_at is not None} for x in db.scalars(q)]})


def _missing():
    raise HTTPException(404)


def _area_given(db: Session, area_id) -> None:
    """An area named in a body is a number and an area that exists (else a 400 saying so, never a database error)."""
    if area_id is not None and (type(area_id) is not int or db.get(FftArea, area_id) is None):
        raise HTTPException(400, "area_id: no such area (feedback.py areas lists them)")


# ------------------------------------------------------------------ changing (each through rules.py)


@router.post("/issues")
def issue_new(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    _area_given(db, body.get("area_id"))
    try:
        i = rules.new_issue(db, actor.name, _str(body, "title", 120, need=True), area_id=body.get("area_id"), feature=_str(body, "feature", 20),
                            kind=_str(body, "kind", 12) or "fix")
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(issue_view(db, i))


@router.post("/issues/{issue_id:int}")
def issue_change(issue_id: int, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """One action at a time: title, feature (a key from app/data/taxonomy.json), move (area_id: a Roadmap build's batch), start, pr, close (reason, words, same_as), reopen, back (words: its live try failed), split (parts), line (words to
    "senders" or "brett"). Claude may not close an issue as working: only a person confirms a fix (R16)."""
    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    i = db.get(FftIssue, issue_id) or _missing()
    do = _str(body, "do", 20, need=True)
    try:
        if do == "title":
            rules.retitle(db, actor.name, i, _str(body, "title", 120, need=True))
        elif do == "feature":
            rules.set_feature(db, actor.name, i, _str(body, "feature", 20, need=True))
        elif do == "kind":  # (fix or improvement, Nov 20)
            rules.set_kind(db, actor.name, i, _str(body, "kind", 12, need=True))
        elif do == "move":
            _area_given(db, body.get("area_id"))
            rules.move_issue(db, actor.name, i, body.get("area_id"))
        elif do == "start":
            rules.start_fixing(db, actor.name, i)
        elif do == "pr":
            rules.fix_ready(db, actor.name, i, _str(body, "pr", 300, need=True))
        elif do == "close":
            reason = _str(body, "reason", 12, need=True)
            if reason == "works":
                raise HTTPException(403, "Only a person confirms a fix works (R16): pass its check, or let its sender confirm.")
            same = db.get(FftIssue, _int(body["same_as"], "same_as")) if body.get("same_as") is not None else None
            rules.close(db, actor.name, i, reason, _str(body, "words"), same_as=same, seen=body.get("seen"))
        elif do == "reopen":
            rules.reopen(db, actor.name, i)
        elif do == "back":  # (Claude's live try of its fix failed: back to To fix, issue 74)
            rules.fix_failed(db, actor.name, i, _str(body, "words", need=True))
        elif do == "split":  # (issue 22: parts [{title, feature}], this issue keeping the first)
            parts = body.get("parts")
            if not isinstance(parts, list) or not parts or not all(isinstance(p, dict) and isinstance(p.get("title"), str) for p in parts):
                raise HTTPException(400, "parts: a list of {title, feature}")
            made = rules.split_issue(db, actor.name, i, [(p["title"][:120], str(p.get("feature") or "")[:20]) for p in parts[:8]])
            db.commit()
            return _ok(issue_view(db, i) | {"split_into": [m.id for m in made]})
        elif do == "line":
            to = {"senders": "sender", "brett": ""}.get(_str(body, "to", 10))
            if to is None:
                raise HTTPException(400, 'to: "senders" or "brett"')
            rules.add_line(db, actor.name, _str(body, "words", need=True), issue=i, to=to)
        else:
            raise HTTPException(400, "do: title, feature, move, start, pr, close, reopen, back, split or line")
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(issue_view(db, i))


@router.post("/checks")
def check_new(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    actor = keys.require(db, x_fft_key, "check")
    body = body if isinstance(body, dict) else {}
    issue_ids = body.get("issues") or []
    if not isinstance(issue_ids, list) or not all(type(x) is int for x in issue_ids):
        raise HTTPException(400, "issues: a list of issue ids")
    devices = body.get("devices") or ["laptop"]
    if not isinstance(devices, list) or not all(d in rules.DEVICES for d in devices):
        raise HTTPException(400, f"devices: from {', '.join(rules.DEVICES)}")
    _area_given(db, body.get("area_id"))
    if any(db.get(FftIssue, i) is None for i in issue_ids):
        raise HTTPException(400, "issues: one of them isn't an issue")
    who = body.get("as_character")
    if who is not None and (type(who) is not int or db.get(Character, who) is None):
        raise HTTPException(400, "as_character: a character's id")
    try:
        c = rules.write_check(db, actor.name, title=_str(body, "title", 160, need=True), steps=_steps(body), expect=_str(body, "expect", need=True),
                              path=_str(body, "path", 500), why=_str(body, "why"), area_id=body.get("area_id"), devices=devices,
                              issue_ids=issue_ids, minutes=body.get("minutes") if type(body.get("minutes")) is int else 2,
                              makes=body.get("makes") is True, as_character=who, before=_str(body, "before", 600), now=_str(body, "now", 600),
                              people=body.get("people") is True, need_goal=True)  # (Clearer checks: never without its goal)
        if _str(body, "pr", 300):  # (its change's pull request: it reaches For you once that's live, Nov 20)
            rules.wait_for_deploy(db, actor.name, c, _str(body, "pr", 300))
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(check_view(db, c))


@router.post("/checks/{check_id:int}")
def check_change(check_id: int, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """version (steps, expect, path, why; before and now, the goal; people), preflight (passed, why), retire (why), link (issue)."""
    actor = keys.require(db, x_fft_key, "check")
    body = body if isinstance(body, dict) else {}
    c = db.get(FftCheck, check_id) or _missing()
    do = _str(body, "do", 20, need=True)
    try:
        if do == "version":
            rules.new_version(db, actor.name, c, steps=_steps(body), expect=_str(body, "expect", need=True), path=_str(body, "path", 500), why=_str(body, "why"),
                              before=_str(body, "before", 600) if "before" in body else None, now=_str(body, "now", 600) if "now" in body else None,
                              people=body["people"] if isinstance(body.get("people"), bool) else None)
        elif do == "preflight":
            if type(body.get("passed")) is not bool:
                raise HTTPException(400, "passed: true or false")
            rules.preflight(db, actor.name, c, body["passed"], _str(body, "why"))
        elif do == "retire":
            rules.retire(db, actor.name, c, _str(body, "why"))
        elif do == "link":
            rules.link_issue(db, actor.name, c, db.get(FftIssue, _int(body.get("issue"), "issue")) or _missing())
        else:
            raise HTTPException(400, "do: version, preflight, retire or link")
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(check_view(db, c))


@router.post("/questions")
def question_new(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    actor = keys.require(db, x_fft_key, "ask")
    body = body if isinstance(body, dict) else {}
    choices = body.get("choices") or []
    if not isinstance(choices, list) or not all(isinstance(c, dict) and isinstance(c.get("label"), str) for c in choices):
        raise HTTPException(400, 'choices: [{"label", "detail"}]')
    mine = body.get("mine")
    if mine is not None and type(mine) is not int:
        raise HTTPException(400, "mine: a number")
    try:
        q = rules.ask(db, actor.name, about=_str(body, "about", 10, need=True), about_id=body.get("about_id"), text=_str(body, "text", need=True),
                      choices=[{"label": c["label"][:120], "detail": str(c.get("detail") or "")[:300]} for c in choices], mine=mine,
                      doc_path=_str(body, "doc_path", 300), doc_version=_str(body, "doc_version", 20))
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok({"id": q.id})


@router.post("/questions/{question_id}/withdraw")
def question_withdraw(question_id: int, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude withdraws a question of its own that a later pick replaced (rules.withdraw), with why."""
    actor = keys.require(db, x_fft_key, "ask")
    body = body if isinstance(body, dict) else {}
    q = db.get(FftQuestion, question_id)
    if q is None:
        raise HTTPException(404, "No such question")
    try:
        rules.withdraw(db, actor.name, q, _str(body, "why", 300, need=True))
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok({"id": q.id})


@router.post("/areas")
def area_change(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """new (item_id, title), item (title, section, standing), lock / unlock (area_id, owner), next (item_id, step,
    whose): Claude sorts work into areas under items; the order is Brett's (his page)."""
    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    do = _str(body, "do", 20, need=True)
    try:
        if do == "new":
            item = db.get(FftItem, _int(body.get("item_id"), "item_id")) or _missing()
            out = {"id": rules.new_area(db, actor.name, item, _str(body, "title", 80, need=True)).id}
        elif do == "item":
            out = {"id": rules.new_item(db, actor.name, _str(body, "title", 120, need=True), _str(body, "section", 10) or "next",
                                        body.get("standing") is True).id}
        elif do in ("lock", "unlock"):
            a = db.get(FftArea, _int(body.get("area_id"), "area_id")) or _missing()
            owner = f"{actor.name}:{_str(body, 'owner', 40) or 'main'}"
            (rules.lock_area if do == "lock" else rules.unlock_area)(db, owner, a)
            out = {"id": a.id, "locked_by": a.lock_owner}
        elif do == "next":
            it = db.get(FftItem, _int(body.get("item_id"), "item_id")) or _missing()
            rules.item_next(db, actor.name, it, _str(body, "step", 200), _str(body, "whose", 10))
            out = {"id": it.id}
        elif do == "lane":  # (up only: Claude never moves a plan down a lane; Brett does, on his page)
            a = db.get(FftArea, _int(body.get("area_id"), "area_id")) or _missing()
            rules.set_lane(db, actor.name, a, _str(body, "lane", 10, need=True), _str(body, "why", 300))
            out = {"id": a.id, "lane": rules.lane_of(a), "why": a.lane_why}
        elif do == "incident":
            a = db.get(FftArea, _int(body.get("area_id"), "area_id")) or _missing()
            rules.incident(db, actor.name, a, _str(body, "why", 300))
            out = {"id": a.id, "lane": rules.lane_of(a), "careful_until": a.careful_until.isoformat()}
        else:
            raise HTTPException(400, "do: new, item, lock, unlock, next, lane or incident")
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(out)


@router.get("/available")
def available(x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Whether Deploys is After my local try (Look work then waits for his try on his Mac), and each local try with its answer."""
    keys.require(db, x_fft_key, "read")
    st = rules.check_available(db)
    db.commit()
    tries = [{"id": t.id, "title": t.title, "area_id": t.area_id, "pr": t.pr, "answer": t.answer, "words": _quoted(t.words, "Brett") if t.words else None,
              "at": t.created_at.isoformat() if t.created_at else ""}
             for t in db.scalars(select(rules.FftLocalTry).order_by(rules.FftLocalTry.id.desc()).limit(20))]
    return _ok({k: st[k] for k in ("on", "until", "off_at", "why")} | {"tries": tries})


@router.post("/local")
def local_try(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude's change, waiting for Brett's try on his Mac while Deploys is After my local try (refused when it isn't)."""
    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    rules.check_available(db)
    area = db.get(FftArea, _int(body.get("area_id"), "area_id")) if body.get("area_id") else None
    changed = body.get("changed") or []
    if not isinstance(changed, list) or not all(isinstance(c, str) for c in changed):
        raise HTTPException(400, "changed: a list of lines")
    try:
        lt = rules.new_local_try(db, actor.name, _str(body, "title", 120, need=True), area, changed, _str(body, "look_at", 1000),
                                 _str(body, "path", 300) or "/", _str(body, "pr", 300))
    except rules.RuleError as e:
        db.commit()  # (local tries may have just ended by themselves)
        _rule(e)
    db.commit()
    return _ok({"id": lt.id})


@router.get("/freeze")
def freeze(merged: str = "", db: Session = Depends(get_db)):
    """Public, and only this (Brett, Nov 19: a switch he turns on before a game): whether deploys are frozen. GitHub's
    Server tests ask it first: while it's on nothing new deploys to askdnd.ai, and a commit saying [table-fix] goes.
    Given main's commit time (`merged`), it also says whether that commit goes: one merged before the pause finishes
    going live (issue 110, Brett: "a pause is not a nuclear option"); never when the pause began."""
    out = {"frozen": rules.frozen(db)}
    if merged:
        out["goes"] = rules.freeze_lets(db, merged)
    return _ok(out)


@router.post("/deploy")
def deploy(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """After a deploy: the commit now live, and the pull requests in it; their issues become ready to try (R4). A
    rollback names the commit that went (R9)."""
    actor = keys.require(db, x_fft_key, "deploy")
    body = body if isinstance(body, dict) else {}
    commit = _str(body, "commit", 40, need=True)
    if body.get("rollback") is True:
        back = rules.rollback(db, "askdnd", commit)
        db.commit()
        return _ok({"rolled_back": back})
    prs = body.get("prs") or []
    if not isinstance(prs, list) or not all(isinstance(p, str) for p in prs):
        raise HTTPException(400, "prs: a list of pull request links")
    live = []
    for i in db.scalars(select(FftIssue).where(FftIssue.pr.in_(prs), FftIssue.state.in_(("fixing", "to_fix")))):
        rules.fix_live(db, "askdnd", i, commit)
        live.append(i.id)
    checks = rules.deployed(db, "askdnd", prs)  # (checks that waited for this deploy reach For you now)
    db.commit()
    return _ok({"live": live, "checks": checks, "by": actor.name})


# ------------------------------------------------------------------ the Roadmap (The Roadmap in askdnd, Nov 20)


def _roadmap_row(db: Session, it: FftItem) -> dict:
    from app.fft import roadmap_page
    from app.fft.models import FftAddition

    r = roadmap_page.row(db, it)
    return {"id": it.id, "title": it.title, "section": it.section, "stage": r["stage"], "size": it.size, "status": it.status,
            "result": it.result, "next": {"whose": r["next"][0], "step": r["next"][1]}, "steps": [r["done"], r["steps"]],
            "scope_version": r["scope"].version if r["scope"] else None, "agreed": bool(r["scope"] and r["scope"].agreed_at),
            "unanswered": db.scalar(select(func.count()).select_from(FftAddition).where(FftAddition.item_id == it.id, FftAddition.answer == "", FftAddition.held.is_(False))),
            "changes_asked": r["stage"] == "revising", "scope_asked": r["stage"] == "asked"}


@router.get("/roadmap")
def roadmap_list(history: int = 0, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """The Roadmap's items in Brett's order (History: shipped and not doing), each with its stage and next step."""
    from app.fft import roadmap_page

    keys.require(db, x_fft_key, "read")
    return _ok({"items": [_roadmap_row(db, r["it"]) for r in roadmap_page.items(db, bool(history))]})


@router.get("/roadmap/{item_id:int}")
def roadmap_item(item_id: int, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """One item whole: why, every scope version, Brett's additions (his words, quoted as his) and their answers, its steps
    and its plans."""
    from app.fft.models import FftAddition, FftScope, FftStep

    keys.require(db, x_fft_key, "read")
    it = db.get(FftItem, item_id) or _missing()
    return _ok(_roadmap_row(db, it) | {
        "why": it.why, "why_from": it.why_from,
        "scopes": [{"version": s.version, "what": s.what, "inside": s.inside, "not_now": s.not_now, "questions": s.questions, "changed": s.changed,
                    "suggested": s.suggested, "agreed": s.agreed_at.isoformat() if s.agreed_at else "",
                    "changes_asked": s.changes_at.isoformat() if s.changes_at else ""} for s in db.scalars(select(FftScope).where(FftScope.item_id == it.id).order_by(FftScope.version))],
        "additions": [{"id": a.id, "where": a.where, "at": a.created_at.isoformat() if a.created_at else "", "words": _quoted(a.words, "Brett"),
                       "answer": a.answer, "answer_words": a.answer_words, "version": a.scope_version,
                       "on": a.on_line, "line": a.line_text, "on_version": a.on_version}  # (issue 54: a comment on a line; "q:<n>" answers a question)
                      for a in db.scalars(select(FftAddition).where(FftAddition.item_id == it.id, FftAddition.held.is_(False)).order_by(FftAddition.id))],
        "steps": [{"id": x.id, "whose": x.whose, "text": x.text, "done": bool(x.done_at)} for x in db.scalars(select(FftStep).where(FftStep.item_id == it.id).order_by(FftStep.place, FftStep.id))],
        "plans": [a.id for a in db.scalars(select(FftArea).where(FftArea.item_id == it.id, FftArea.archived.is_(False)))]})


def _list_of(body: dict, k: str) -> list[str]:
    v = body.get(k) or []
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise HTTPException(400, f"{k}: a list of lines")
    return v


@router.post("/roadmap")
def roadmap_new(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A new Roadmap idea: what Brett outlined in chat, his words its first addition (`where`: chat)."""
    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    try:
        it = rules.new_idea(db, actor.name, _str(body, "title", 120, need=True), _str(body, "words", 8000), _str(body, "section", 10) or "next", where="chat")
        if any(body.get(k) for k in ("why", "size", "status")):
            rules.set_item(db, actor.name, it, why=_str(body, "why", 2000) or None, size=_str(body, "size", 2) or None, status=_str(body, "status", 200) or None)
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(_roadmap_row(db, it))


@router.post("/roadmap/{item_id:int}")
def roadmap_change(item_id: int, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """One change at a time: scope (what, inside, not_now, questions, changed: the next version), add (Brett's words said in
    chat), answer (addition, answer: in|later|question, words, version), step (text, whose), tick (step, done), unstep
    (step), move (section), ship, not_doing, set (title, why: its first line the headline, each after it a point; why_from: the
    decisions behind it; size, status, result). Only Brett says a scope looks right."""
    from app.fft.models import FftAddition, FftStep

    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    it = db.get(FftItem, item_id) or _missing()
    do = _str(body, "do", 12, need=True)
    try:
        if do == "scope":
            rules.write_scope(db, actor.name, it, what=_str(body, "what", 4000, need=True), inside=_list_of(body, "inside"),
                              not_now=_list_of(body, "not_now"), questions=_list_of(body, "questions"), changed=_str(body, "changed", 2000),
                              suggested=_list_of(body, "suggest"))
        elif do == "add":
            rules.add_to_item(db, actor.name, it, _str(body, "words", 8000, need=True), where=_str(body, "where", 10) or "chat")
        elif do == "answer":
            a = db.get(FftAddition, _int(body.get("addition"), "addition"))
            if a is None or a.item_id != it.id:
                _missing()
            v = body.get("version")
            rules.answer_addition(db, actor.name, a, _str(body, "answer", 10, need=True), _str(body, "words", 2000), v if isinstance(v, int) else None)
        elif do in ("step",):
            rules.add_step(db, actor.name, it, _str(body, "text", 200, need=True), _str(body, "whose", 10) or "claude")
        elif do in ("tick", "unstep"):
            st = db.get(FftStep, _int(body.get("step"), "step"))
            if st is None or st.item_id != it.id:
                _missing()
            if do == "tick":
                rules.tick_step(db, actor.name, st, body.get("done", True) is not False)
            else:
                rules.remove_step(db, actor.name, st)
        elif do == "move":
            rules.move_item(db, actor.name, it, _str(body, "section", 10, need=True))
        elif do in ("ship", "not_doing"):
            result = _str(body, "result", 4000)
            if not result.strip():  # (Brett, Nov 20: every item Claude finishes says what it changed, with its numbers)
                raise HTTPException(400, "result: what it changed, with its numbers (for Not doing, why not)")
            rules.ship_item(db, actor.name, it, not_doing=do == "not_doing", result=result)
        elif do == "set":
            rules.set_item(db, actor.name, it, **{k: _str(body, k, 4000 if k == "result" else 2000) for k in ("title", "why", "size", "status", "result", "why_from") if k in body})
        elif do == "agree":
            raise HTTPException(403, "Only Brett says a scope looks right.")
        else:
            raise HTTPException(400, "scope, add, answer, step, tick, unstep, move, ship, not_doing or set")
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(_roadmap_row(db, it))


@router.get("/ideas")
def ideas(x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Ideas from before the Roadmap was in askdnd, still to place (each with its notes, quoted with who wrote them)."""
    from app.fft.models import FftIdea

    keys.require(db, x_fft_key, "read")
    out = []
    for d in db.scalars(select(FftIdea).where(FftIdea.state == "new").order_by(FftIdea.id)):
        notes = db.scalars(select(FftNote).where(FftNote.idea_id == d.id, FftNote.state == "filed").order_by(FftNote.id))
        out.append({"id": d.id, "title": d.title, "notes": [_quoted(n.text, _by(n)) for n in notes]})
    return _ok({"items": out})


@router.post("/ideas/{idea_id:int}")
def idea_place(idea_id: int, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Place an idea: on the Roadmap (do: roadmap), or a change to a Product Area (do: fix | improvement)."""
    from app.fft.models import FftIdea

    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    d = db.get(FftIdea, idea_id) or _missing()
    do = _str(body, "do", 12, need=True)
    try:
        if do == "roadmap":
            made = {"item": rules.idea_to_roadmap(db, actor.name, d).id}
        elif do in rules.ISSUE_KINDS:
            made = {"issue": rules.idea_to_issue(db, actor.name, d, do).id}
        else:
            raise HTTPException(400, "roadmap, fix or improvement")
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(made)


@router.post("/jobs/{key}")
def job_ran(key: str, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A scheduled job's run (Work › Scheduled; The Work Pages, Nov 20): {"result": "ok"|"failed", "words": "…"}. Claude's
    key reports any; the Mac Mini's and GitHub's only their own (keys.JOBS_OF)."""
    from app.fft import work_page

    actor = keys.actor_for(db, x_fft_key)
    if actor is None:
        raise HTTPException(404)
    if not (actor.may("write") or key in keys.JOBS_OF.get(actor.name, ())):
        raise HTTPException(403, "This key can't report that job.")
    body = body if isinstance(body, dict) else {}
    try:
        work_page.report_job(db, actor.name, key, _str(body, "result", 10, need=True), _str(body, "words", 200))
    except rules.RuleError as e:
        raise _rule(e) from e
    db.commit()
    return _ok({"job": key})


@router.post("/claim")
def claim(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude asks for work (item 39, 3 of 4): askdnd hands over the top of Ready and records the claim, one at a time
    ({"owner": its listener's name, "area": an id to claim by hand}); {"release": true} gives the claim back."""
    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    owner = f"{actor.name}:{_str(body, 'owner', 40) or 'main'}"
    try:
        if body.get("release") is True:
            held = db.scalar(select(FftArea).where(FftArea.lock_owner == owner, FftArea.lock_until > rules.now()))
            if held is not None:
                rules.unlock_area(db, owner, held)
            db.commit()
            return _ok({"released": held.id if held else None})
        area = db.get(FftArea, _int(body.get("area"), "area")) if body.get("area") is not None else None
        if body.get("area") is not None and area is None:
            raise HTTPException(404)
        got, why, already = rules.claim(db, owner, area)
    except rules.RuleError as e:
        raise _rule(e) from e
    db.commit()
    return _ok({"area": got.id if got else None, "title": got.title if got else "", "why": why, "already": already})


@router.post("/github/pulls")
def github_pulls(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """What GitHub sees of the pull requests (scripts/github_report.py; item 39): {"pulls": [{"number", "title", "branch",
    "by_bot", "state", "tests", "merge_state", "auto_merge", "head", "updated" (an older reporter's)}], "snapshot": true
    when they're all the open ones}. GitHub's key may send only this and its jobs."""
    actor = keys.require(db, x_fft_key, "pulls")
    body = body if isinstance(body, dict) else {}
    rows = body.get("pulls")
    if not isinstance(rows, list) or len(rows) > 200 or not all(isinstance(r, dict) for r in rows):
        raise HTTPException(400, "pulls: a list of up to 200 pull requests")
    try:
        seen = rules.pulls_seen(db, actor.name, rows, snapshot=body.get("snapshot") is True)
    except rules.RuleError as e:
        raise _rule(e) from e
    db.commit()  # (the report is kept whatever the release below does)
    numbers, live = [p.number for p in seen], []
    try:
        with db.begin_nested():  # (a release that can't finish is undone alone: the next report tries again)
            live = rules.release_live(db, "askdnd", config.running_version())["live"]  # (one merged just before the deploy)
    except rules.RuleError:
        from app import errors

        if errors.on():
            import sentry_sdk

            sentry_sdk.capture_exception()
    db.commit()
    return _ok({"seen": numbers, "live": live})


@router.get("/pulls")
def pulls(open: int = 1, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """The pull requests askdnd knows, newest first (`open=0`: the closed ones too), each with the work it's for."""
    keys.require(db, x_fft_key, "read")
    q = select(FftPull).order_by(FftPull.number.desc())
    if open:
        q = q.where(FftPull.state == "open")
    return _ok({"items": [views.pull_row(p) for p in db.scalars(q.limit(200))]})


@router.post("/keys")
def key_new(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A key for a reporter that isn't Claude ({"actor": "github" | "mini", "name": "…"}): made with Claude's key, shown
    once, kept only as its hash; it may only report its own jobs (the jobs audit, Brett's pick 1, Nov 21)."""
    import secrets

    from app.fft.models import FftKey

    keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    actor = _str(body, "actor", 20, need=True)
    if actor not in keys.JOBS_OF:
        raise HTTPException(400, f"actor: one of {', '.join(keys.JOBS_OF)}")
    raw = secrets.token_urlsafe(32)
    db.add(FftKey(name=_str(body, "name", 60) or actor, key_hash=keys.digest(raw), actor=actor, scopes=sorted(keys.SCOPES[actor])))
    rules._event(db, "claude", "key_made", "key", 0, for_=actor)
    db.commit()
    return _ok({"actor": actor, "key": raw})


@router.post("/relay")
def relay(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A note sent on staging, relayed here: it always waits for an admin (T6), whoever it says sent it."""
    keys.require(db, x_fft_key, "relay")
    body = body if isinstance(body, dict) else {}
    raw = body.get("pictures") or []
    if not isinstance(raw, list) or len(raw) > sending.MAX_PICS or not all(sending.image(x) for x in raw):
        raise HTTPException(400, f"pictures: up to {sending.MAX_PICS} safe copies as data: URLs")
    stored = sending.store_pictures(db, [{"full": x, "safe": x, "kind": "added"} for x in raw], safe_only=True)  # (before the event: T8)
    try:
        n = rules.send_note(db, user_id=None, first_name=_str(body, "first_name", 60) or "Someone", role=_str(body, "role", 12) or "member",
                            kind=_str(body, "kind", 10), text=_str(body, "text", need=True), url=_str(body, "url", 1000), page=_str(body, "page", 120),
                            context={k: v for k, v in (body.get("context") or {}).items() if isinstance(k, str)} if isinstance(body.get("context"), dict) else {},
                            staging=True)
    except rules.RuleError as e:
        _rule(e)
    sending.attach_pictures(db, stored, note_id=n.id)
    db.commit()
    return _ok({"id": n.id, "waits": n.state == "waiting"})


@router.post("/mini/tries")
def mini_try(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """The Mac Mini's run of a check: recorded, but a pass confirms nothing (R10, R16)."""
    keys.require(db, x_fft_key, "mini")
    body = body if isinstance(body, dict) else {}
    c = db.get(FftCheck, _int(body.get("check"), "check")) or _missing()
    result = _str(body, "result", 8, need=True)
    found = []
    if result == "failed":
        words = _str(body, "words", need=True)
        open_issue = next((i for i in rules._blocking_issues(db, c) if i.state != "closed"), None)
        found = [rules.Found(issue_id=open_issue.id) if open_issue else rules.Found(title=words[:120])]
    try:
        t = rules.record_try(db, "mini", c, result=result, device="mac_mini", where=_str(body, "where", 10) or "live",
                             app_version=_str(body, "app_version", 40), found=found, why=_str(body, "words"))
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok({"try": t.id, **rules.check_state(db, c)})


@router.get("/pictures/{pic_id:int}")
def picture(pic_id: int, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A note's picture as Claude may see it: the safe copy (a player's character notes blurred at capture), only once
    its note is filed (T1, T5)."""
    from app import files

    keys.require(db, x_fft_key, "read")
    pic = db.get(FftPicture, pic_id)
    line = db.get(FftLine, pic.line_id) if pic is not None and pic.line_id else None
    note_id = (line.note_id if line else None) or (pic.note_id if pic is not None else None)
    note = db.get(FftNote, note_id) if note_id else None
    if pic is None or not pic.safe_key or note is None or note.state != "filed" or (line is not None and not line.approved):
        raise HTTPException(404)
    content_type = next((t for t, (ext, _) in files.TYPES.items() if pic.safe_key.endswith(ext)), "image/png")
    return files.serve(pic.safe_key, content_type, cache_control="no-store", release=db)


@router.post("/pages")
def page_send(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """A page Claude sends before its repo copy lands (item 39, scope v7): {"entry": its docs/library.json entry,
    "files": {path under docs/: its contents in base64}}. It opens in Backstage › Documents at once, sealed as the repo's
    pages are; sending again replaces it. feedback.py page send."""
    import base64
    import binascii

    from app import documents

    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    entry, raw = body.get("entry"), body.get("files")
    if not isinstance(entry, dict) or not isinstance(raw, dict):
        raise HTTPException(400, "Send its entry and its files.")
    try:
        files = {str(k): base64.b64decode(v, validate=True) for k, v in raw.items() if isinstance(v, str)}
    except (binascii.Error, ValueError):
        raise HTTPException(400, "Each file's contents in base64.") from None
    if len(files) != len(raw):
        raise HTTPException(400, "Each file's contents in base64.")
    try:
        doc = rules.send_page(db, actor.name, entry, files)
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    documents.invalidate()
    did = documents.doc_id(doc.source)
    return _ok({"id": did, "source": doc.source, "href": f"/manage/documents/{did}", "files": len(files)})


# Comments and picks in either place (item 39, 6 of 6): what Claude checks on claude.ai, what it brings in, what it hands out


@router.get("/docs/check")
def docs_check(x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    keys.require(db, x_fft_key, "read")
    return _ok({"docs": rules.docs_to_check(db)})


@router.get("/docs/out")
def docs_out(doc: str = "", x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    keys.require(db, x_fft_key, "read")
    return _ok(rules.doc_out(db, doc[:300]))


@router.post("/docs/in")
def docs_in(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """{"doc", "comments": [{ext_id, near, words, at, page}], "picks": {"picks": [...], "notes", "at"} | null}: what Brett
    made on claude.ai, brought in. Comments come in once each; picks answer the open question, or replace older ones."""
    from app import documents

    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    doc = _str(body, "doc", 300, need=True)
    if documents.find(documents.doc_id(doc)) is None:
        raise HTTPException(400, "That page isn't in Documents.")
    raw = body.get("comments") if isinstance(body.get("comments"), list) else []
    added = rules.comments_in(db, actor.name, doc, [c for c in raw[:200] if isinstance(c, dict)])
    p = body.get("picks") if isinstance(body.get("picks"), dict) else {}
    try:
        picks = rules.picks_in(db, actor.name, doc, p.get("picks") if isinstance(p.get("picks"), list) else [], str(p.get("notes") or ""), p.get("at"))
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok({"comments": added, "picks": picks})


# What Brett says in chat (item 42, his pick 2A): saved as it arrives, filed by Claude


@router.post("/chat")
def chat_said(body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """{"words", "session", "at"}: a message Brett sent Claude in the Code tab, from the Claude Code hook."""
    keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    c = rules.chat_said(db, "claude:chat", _str(body, "words", 20000), _str(body, "session", 64), body.get("at"))
    db.commit()
    return _ok({"id": c.id if c else None})


@router.get("/chat")
def chat_list(x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """What Brett said in chat and Claude hasn't filed yet, oldest first."""
    from app.fft.models import FftChat

    keys.require(db, x_fft_key, "read")
    rows = db.scalars(select(FftChat).where(FftChat.filed_as == "").order_by(FftChat.id))
    return _ok({"chat": [{"id": c.id, "at": c.said_at.isoformat(), "words": c.words} for c in rows]})


@router.post("/chat/{chat_id:int}")
def chat_file(chat_id: int, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """{"as": "item" | "issue" | "chat", "id"}: filed onto a Roadmap item, an issue, or as just chat."""
    from app.fft.models import FftChat

    actor = keys.require(db, x_fft_key, "write")
    body = body if isinstance(body, dict) else {}
    c = db.get(FftChat, chat_id) or _missing()
    try:
        rules.chat_file(db, actor.name, c, _str(body, "as", 10, need=True), body.get("id") if isinstance(body.get("id"), int) else None)
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok({"id": c.id, "filed_as": c.filed_as, "filed_id": c.filed_id})
