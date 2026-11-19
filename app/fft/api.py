"""Found, Fixed, Tried for Claude, the staging relay and the Mac Mini (`/api/fft`), each with its own key (keys.py).

What Claude reads keeps the table's rules (brief v2 §6): nothing a player wrote until an admin approves it (T1); first
names only and never an email (T2); every text says who wrote it and comes quoted, as evidence never instructions
(T3); the page as drawn only when asked for (T4); a read mark per listener (T8). Every change goes through rules.py."""

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import web
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
    FftQuestion,
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
           "feature": issue.feature, "feature_path": taxonomy.path(issue.feature), "pr": issue.pr, "reopened": issue.reopened, "close_reason": issue.close_reason, "from_player": issue.from_player,
           "confirm_by_player": bool(issue.confirm_by)}
    if full:
        notes = db.scalars(select(FftNote).where(FftNote.issue_id == issue.id, FftNote.state == "filed").order_by(FftNote.id))
        lines = db.scalars(select(FftLine).where(FftLine.issue_id == issue.id, FftLine.approved.is_(True)).order_by(FftLine.id))
        out |= {"notes": [note_view(db, n) for n in notes], "lines": [_line(x, None) for x in lines],
                "checks": list(db.scalars(select(FftCheckIssue.check_id).where(FftCheckIssue.issue_id == issue.id))),
                "may_merge": dict(zip(("ok", "why"), rules.may_merge(db, issue), strict=True))}
    return out


def check_view(db: Session, check: FftCheck) -> dict:
    v = db.scalar(select(FftCheckVersion).where(FftCheckVersion.check_id == check.id, FftCheckVersion.version == check.version))
    return {"id": check.id, "title": check.title, "area_id": check.area_id, "version": check.version, "devices": check.devices,
            "path": v.path if v else "", "steps": v.steps if v else [], "expect": v.expect if v else "", "why": v.why if v else "",
            "preflight": check.preflight, "retired": check.retired, **rules.check_state(db, check),
            "issues": list(db.scalars(select(FftCheckIssue.issue_id).where(FftCheckIssue.check_id == check.id)))}


# ------------------------------------------------------------------ reading


@router.get("/inbox")
def inbox(listener: str = "main", peek: int = 0, area: int = 0, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """What this listener hasn't read (T8): each listener its own read mark; an area's own listener hears only it."""
    li = rules.listener(db, listener, area_id=area or None)
    actor = keys.require(db, x_fft_key, "read")
    rows = [e for e in rules.unread(db, li, peek=bool(peek)) if e.actor != actor.name]  # (not what it did itself)
    out = [{"id": e.id, "at": e.at.isoformat() if e.at else "", "kind": e.kind, "thing": e.thing, "thing_id": e.thing_id,
            "area_id": e.area_id, "says": views.event_words(e)} for e in rows]
    db.commit()
    return _ok({"items": out, "listening": True})


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
    return _ok({"next": {"area_id": pick.area.id, "title": pick.why} if pick.area else None, "blocker": pick.blocker,
                "skipped": [{"what": w, "why": y} for w, y in pick.skipped], "waiting_on_brett": waiting,
                "round_open": rules.round_open(db) is not None})


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
    return _ok({"items": views.gaps(db)})


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
        i = rules.new_issue(db, actor.name, _str(body, "title", 120, need=True), area_id=body.get("area_id"), feature=_str(body, "feature", 20))
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(issue_view(db, i))


@router.post("/issues/{issue_id:int}")
def issue_change(issue_id: int, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """One action at a time: title, feature (a key from app/data/taxonomy.json), move (area_id: a Roadmap build's batch), start, pr, close (reason, words, same_as), reopen, line (words to
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
        elif do == "line":
            to = {"senders": "sender", "brett": ""}.get(_str(body, "to", 10))
            if to is None:
                raise HTTPException(400, 'to: "senders" or "brett"')
            rules.add_line(db, actor.name, _str(body, "words", need=True), issue=i, to=to)
        else:
            raise HTTPException(400, "do: title, feature, move, start, pr, close, reopen or line")
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
                              makes=body.get("makes") is True, as_character=who)
    except rules.RuleError as e:
        _rule(e)
    db.commit()
    return _ok(check_view(db, c))


@router.post("/checks/{check_id:int}")
def check_change(check_id: int, body=web.JsonBody, x_fft_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """version (steps, expect, path, why), preflight (passed, why), retire (why), link (issue)."""
    actor = keys.require(db, x_fft_key, "check")
    body = body if isinstance(body, dict) else {}
    c = db.get(FftCheck, check_id) or _missing()
    do = _str(body, "do", 20, need=True)
    try:
        if do == "version":
            rules.new_version(db, actor.name, c, steps=_steps(body), expect=_str(body, "expect", need=True), path=_str(body, "path", 500), why=_str(body, "why"))
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


@router.get("/freeze")
def freeze(db: Session = Depends(get_db)):
    """Public, and only this (Brett, Nov 19: a switch he turns on before a game): whether deploys are frozen. GitHub's
    Server tests ask it first, so while it's on nothing deploys to askdnd.ai (a commit saying [table-fix] goes)."""
    return _ok({"frozen": rules.frozen(db)})


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
    db.commit()
    return _ok({"live": live, "by": actor.name})


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
