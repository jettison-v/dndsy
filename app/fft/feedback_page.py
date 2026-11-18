"""Manage › askdnd › Feedback (screens 10–14 of docs/mockups/found-fixed-tried/): the record of every note and issue,
admins only, as a Reader: the list, and the open thing beside it.

- **To approve**: a player's note, which Claude sees none of until it's approved (T1), from its safe copy (T5). Approve
  it as a new issue, Same as… an issue already filed (R2), an idea, a question answered, or decline it with why; a
  corner card offers Undo for a minute.
- **Open**, **Ready to try**, **Closed**: issues, each with the notes that became it, its conversation (to Claude, or to
  everyone who sent its notes), Move to another area…, Same as…, Close with a reason… (its senders read the reason),
  Reopen. A fix a player's words prompted waits for **OK to merge** (R17).
- **Ideas**: what was taken up as an idea, until the Roadmap takes it.

Every change goes through app/fft/rules.py."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import files, web
from app.auth import is_admin
from app.db import get_db
from app.fft import rules, views
from app.fft.models import FftArea, FftCheckIssue, FftEvent, FftIdea, FftIssue, FftLine, FftNote, FftPicture
from app.templating import templates

router = APIRouter()
BACK = "/manage/feedback"
TABS = (("approve", "To approve"), ("open", "Open"), ("ready", "Ready to try"), ("closed", "Closed"), ("ideas", "Ideas"))
OPEN_STATES = ("to_fix", "fixing", "asks", "merge_ok")


def _admin(request: Request):
    return web.require(request, is_admin, "Feedback is for admins.")


def _missing():
    raise HTTPException(404)


def _issue_q(tab: str):
    states = {"open": OPEN_STATES, "ready": ("ready",), "closed": ("closed",)}[tab]
    return select(FftIssue).where(FftIssue.state.in_(states))


def counts(db: Session) -> dict:
    by = dict(db.execute(select(FftIssue.state, func.count()).group_by(FftIssue.state)).all())
    return {"approve": views.to_approve(db), "open": sum(by.get(s, 0) for s in OPEN_STATES), "ready": by.get("ready", 0),
            "closed": 0,  # (a closed thing isn't counted: a count means there's something there to do)
            "ideas": db.scalar(select(func.count()).select_from(FftIdea).where(FftIdea.state.in_(("new", "roadmap")))) or 0}


def notes_of_issue(db: Session, issue: FftIssue) -> list[FftNote]:
    return list(db.scalars(select(FftNote).where(FftNote.issue_id == issue.id).order_by(FftNote.id)))


def senders(notes: list[FftNote]) -> list[str]:
    """The first names of a list of notes' senders, each once, in order."""
    out = []
    for n in notes:
        if n.role != "admin" and n.first_name not in out:
            out.append(n.first_name)
    return out


def pictures(db: Session, note: FftNote) -> list[FftPicture]:
    return list(db.scalars(select(FftPicture).where(FftPicture.note_id == note.id).order_by(FftPicture.id)))


def rows(db: Session, tab: str, chip: str = "", area: int = 0) -> list[dict]:
    """The list: each row's id ("n" a note, "i" an issue, "d" an idea), title, pill and line under it."""
    out = []
    if tab == "approve":
        for n in db.scalars(select(FftNote).where(FftNote.state == "waiting").order_by(FftNote.id)):
            word, tone = views.turn_pill("yours")
            out.append({"key": f"n{n.id}", "title": views.title_of(n.text), "word": word, "tone": tone,
                        "sub": f"{n.first_name} · {views.KIND_SAID.get(n.kind, '').lower()}" + (" · from staging" if n.staging else "")})
        return out
    if tab == "ideas":
        for d in db.scalars(select(FftIdea).where(FftIdea.state != "declined").order_by(FftIdea.id.desc())):
            word, tone = ("On the Roadmap", "claude") if d.state == "roadmap" else ("Built", "quiet") if d.state == "shipped" else ("New idea", "ask")
            out.append({"key": f"d{d.id}", "title": d.title, "word": word, "tone": tone, "sub": ""})
        return out
    q = _issue_q(tab).order_by(FftIssue.id.desc())
    if area:
        q = q.where(FftIssue.area_id == area)
    if chip == "players":
        q = q.where(FftIssue.from_player.is_(True))
    elif chip == "checks":
        q = q.where(or_(FftIssue.origin_try_id.isnot(None), FftIssue.id.in_(select(FftCheckIssue.issue_id))))
    areas = {a.id: a.title for a in db.scalars(select(FftArea))}
    for i in db.scalars(q.limit(300)):
        turn, name = views.issue_turn(db, i)
        word, tone = views.turn_pill(turn, name)
        notes = notes_of_issue(db, i)
        bits = [views.ISSUE_WORD[i.state] if i.state != "closed" else views.CLOSED_WORD.get(i.close_reason or "", "Closed")]
        if i.reopened and i.state != "closed":
            bits.append("came back")
        if i.area_id in areas:
            bits.append(areas[i.area_id])
        if who := senders(notes):
            bits.append(", ".join(who))
        elif i.origin_try_id:
            bits.append("from a check")
        out.append({"key": f"i{i.id}", "title": i.title, "word": word, "tone": tone, "sub": " · ".join(bits)})
    if tab == "closed" and not chip and not area:  # (notes decided without an issue: declined, or a question answered)
        for n in db.scalars(select(FftNote).where(or_(FftNote.state == "declined", FftNote.filed_as == "answered")).order_by(FftNote.id.desc()).limit(200)):
            word, tone = views.turn_pill("closed")
            out.append({"key": f"n{n.id}", "title": views.title_of(n.text), "word": "Answered" if n.filed_as == "answered" else "Declined",
                        "tone": tone, "sub": f"{n.first_name} · {views.KIND_SAID.get(n.kind, '').lower()}"})
    return out


def note_view(db: Session, note: FftNote, viewer_id: int | None) -> dict:
    pics = pictures(db, note)
    return {"n": note, "pics": pics, "covered": any(p.key != p.safe_key for p in pics),
            "lines": list(db.scalars(select(FftLine).where(FftLine.note_id == note.id).order_by(FftLine.id))),
            "mine": note.user_id and note.user_id == viewer_id}


def issue_view(db: Session, issue: FftIssue, viewer_id: int | None) -> dict:
    notes = notes_of_issue(db, issue)
    turn, name = views.issue_turn(db, issue)
    events = list(db.scalars(select(FftEvent).where(or_((FftEvent.thing == "issue") & (FftEvent.thing_id == issue.id),
                                                        (FftEvent.thing == "note") & FftEvent.thing_id.in_([n.id for n in notes] or [0])))
                             .order_by(FftEvent.id.desc())))
    return {"i": issue, "turn": turn, "pill": views.turn_pill(turn, name), "sentence": views.issue_sentence(db, issue),
            "area": db.get(FftArea, issue.area_id) if issue.area_id else None, "notes": [note_view(db, n, viewer_id) for n in notes],
            "senders": senders(notes), "lines": list(db.scalars(select(FftLine).where(FftLine.issue_id == issue.id).order_by(FftLine.id))),
            "may_merge": rules.may_merge(db, issue), "events": events, "listening": views.listening(db),
            "checks": list(db.scalars(select(FftCheckIssue.check_id).where(FftCheckIssue.issue_id == issue.id)))}


@router.get("/manage/feedback")
def page(request: Request, tab: str = "", open: str = "", chip: str = "", area: int = 0, db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    n = counts(db)
    tab = tab if tab in dict(TABS) else ("approve" if n["approve"] else "open")
    chip = chip if chip in ("players", "checks") else ""
    listed = rows(db, tab, chip, area)
    pick = open if any(r["key"] == open for r in listed) or open[:1] in ("n", "i", "d") else (listed[0]["key"] if listed else "")
    me = views.person(db, user)
    picked = None
    if pick[:1] == "n" and pick[1:].isdigit() and (note := db.get(FftNote, int(pick[1:]))):
        picked = {"kind": "note", **note_view(db, note, me["id"])} | ({"issue": issue_view(db, db.get(FftIssue, note.issue_id), me["id"])} if note.issue_id else {})
    elif pick[:1] == "i" and pick[1:].isdigit() and (issue := db.get(FftIssue, int(pick[1:]))):
        picked = {"kind": "issue", **issue_view(db, issue, me["id"])}
    elif pick[:1] == "d" and pick[1:].isdigit() and (idea := db.get(FftIdea, int(pick[1:]))):
        picked = {"kind": "idea", "d": idea, "notes": [note_view(db, x, me["id"]) for x in db.scalars(select(FftNote).where(FftNote.idea_id == idea.id))]}
    return templates.TemplateResponse(request, "fft_feedback.html", {
        "tab": tab, "tabs": TABS, "counts": n, "rows": listed, "pick": pick, "picked": picked, "chip": chip, "area": area,
        "areas": list(db.scalars(select(FftArea).where(FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id))),
        "kind_said": views.KIND_SAID, "closed_word": views.CLOSED_WORD, "issue_word": views.ISSUE_WORD, "me_id": me["id"],
        "toast": request.session.pop("toast", None)})


def _back(request: Request, key: str = "") -> RedirectResponse:
    q = request.query_params
    tab = q.get("tab", "")
    return RedirectResponse(f"{BACK}?tab={tab if tab in dict(TABS) else ''}" + (f"&open={key}" if key else ""), status_code=303)


def _said(request: Request, text: str, undo: str = "") -> None:
    request.session["toast"] = {"text": text, "kind": "ok", **({"undo": undo} if undo else {})}


def _act(fn):
    try:
        return fn()
    except rules.RuleError as e:
        raise HTTPException(409 if e.code in ("stale", "late", "busy") else 400, e.words) from e


@router.post("/manage/feedback/notes/{note_id:int}")
def note_change(request: Request, note_id: int, do: str = Form(...), issue: int = Form(0), words: str = Form(""),
                db: Session = Depends(get_db)):
    """Approve a waiting note (as an issue, joined to one, an idea, a question answered), decline it with why, or undo
    that within a minute (R1, R2). Adding a line to a note's conversation (to its sender, or to Claude)."""
    user, denied = _admin(request)
    if denied:
        return denied
    note = db.get(FftNote, note_id) or _missing()
    actor = f"user:{views.person(db, user)['id']}"
    undo = f"/manage/feedback/notes/{note.id}/undo"
    if do == "issue":
        made = _act(lambda: rules.file_issue(db, actor, note))
        _said(request, "Approved as a new issue: it's Claude's to fix", undo)
        key = f"i{made.id}"
    elif do == "same":
        target = db.get(FftIssue, issue) or _missing()
        made = _act(lambda: rules.join_issue(db, actor, note, target))
        _said(request, f"Joined “{made.title}”", undo)
        key = f"i{made.id}"
    elif do == "idea":
        made = _act(lambda: rules.file_idea(db, actor, note))
        _said(request, "Approved as an idea", undo)
        key = ""
    elif do == "answer":
        _act(lambda: rules.answer_note(db, actor, note, words, user_id=views.person(db, user)["id"]))
        _said(request, f"Answered: {note.first_name} reads it on Notes you sent", undo)
        key = ""
    elif do == "decline":
        _act(lambda: rules.decline(db, actor, note, words))
        _said(request, f"Declined: {note.first_name} reads why" if words.strip() else "Declined", undo)
        key = ""
    elif do == "tell":
        _act(lambda: rules.add_line(db, actor, words, note=note, to="sender", user_id=views.person(db, user)["id"]))
        _said(request, f"Sent to {note.first_name}: they read it on Notes you sent")
        key = f"n{note.id}"
    else:
        raise HTTPException(400)
    db.commit()
    if do != "tell" and views.to_approve(db):  # (approving: on to the next note waiting)
        return RedirectResponse(f"{BACK}?tab=approve", status_code=303)
    if key[:1] == "i":  # (the last one: where it went)
        return RedirectResponse(f"{BACK}?tab=open&open={key}", status_code=303)
    return RedirectResponse(f"{BACK}?tab=ideas" if do == "idea" else f"{BACK}?tab=closed" if do in ("answer", "decline") else f"{BACK}?tab=approve&open={key}", status_code=303)


@router.post("/manage/feedback/notes/{note_id:int}/undo")
def note_undo(request: Request, note_id: int, db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    note = db.get(FftNote, note_id) or _missing()
    _act(lambda: rules.undo_decision(db, f"user:{views.person(db, user)['id']}", note))
    db.commit()
    request.session["toast"] = "Undone: it's waiting for you again"
    return RedirectResponse(f"{BACK}?tab=approve&open=n{note.id}", status_code=303)


@router.post("/manage/feedback/issues/{issue_id:int}")
def issue_change(request: Request, issue_id: int, do: str = Form(...), words: str = Form(""), to: str = Form(""), area: int = Form(0),
                 reason: str = Form(""), same_as: int = Form(0), note: int = Form(0), seen: str = Form(""), db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    i = db.get(FftIssue, issue_id) or _missing()
    me = views.person(db, user)
    actor = f"user:{me['id']}"
    if do == "move":
        _act(lambda: rules.move_issue(db, actor, i, area or None))
        a = db.get(FftArea, area) if area else None
        _said(request, f"Moved to {a.title}" if a else "Out of its area")
    elif do == "close":
        other = db.get(FftIssue, same_as) if same_as else None
        if reason == "same" and other is None:
            raise HTTPException(400, "Same as which issue?")
        _act(lambda: rules.close(db, actor, i, reason, words, same_as=other, seen=seen or None))
        _said(request, "Closed: its senders read why" if words.strip() else "Closed")
    elif do == "reopen":
        _act(lambda: rules.reopen(db, actor, i))
        _said(request, "Reopened: it's Claude's again, marked came back")
    elif do == "ok_merge":
        _act(lambda: rules.ok_merge(db, actor, i))
        _said(request, "OK to merge: Claude merges it once checks pass")
    elif do == "line":
        if to not in ("claude", "senders"):
            raise HTTPException(400, "To Claude, or to those who sent its notes?")
        _act(lambda: rules.add_line(db, actor, words, issue=i, to="sender" if to == "senders" else "", user_id=me["id"]))
        _said(request, "Sent to those who sent its notes" if to == "senders" else "Sent to Claude")
    elif do == "unjoin":
        n = db.get(FftNote, note) or _missing()
        if n.issue_id != i.id:
            raise HTTPException(400, "That note isn't on this issue.")
        made = _act(lambda: rules.unjoin(db, actor, n))
        db.commit()
        _said(request, "Unjoined: it's an issue of its own")
        return _back(request, f"i{made.id}")
    elif do == "title":
        if not words.strip():
            raise HTTPException(400, "Give it a title.")
        i.title = words.strip()[:120]
        rules._event(db, actor, "issue_title", "issue", i.id, area_id=i.area_id)
        _said(request, "Renamed")
    else:
        raise HTTPException(400)
    db.commit()
    return _back(request, f"i{i.id}")


@router.post("/manage/feedback/ideas/{idea_id:int}")
def idea_change(request: Request, idea_id: int, do: str = Form(...), words: str = Form(""), db: Session = Depends(get_db)):
    """An idea taken onto the Roadmap, built, or declined with why (its senders read it)."""
    user, denied = _admin(request)
    if denied:
        return denied
    d = db.get(FftIdea, idea_id) or _missing()
    if do not in ("roadmap", "shipped", "declined", "new"):
        raise HTTPException(400)
    was, d.state = d.state, do
    d.reason = words.strip()[:500] if do == "declined" else d.reason
    rules._event(db, f"user:{views.person(db, user)['id']}", "idea_" + do, "idea", d.id, **{"from": was, "to": do})
    db.commit()
    _said(request, {"roadmap": "On the Roadmap", "shipped": "Marked built", "declined": "Declined", "new": "Back to new"}[do])
    return RedirectResponse(f"{BACK}?tab=ideas&open=d{d.id}", status_code=303)


# ------------------------------------------------------------------ windows: Same as…, Close with a reason…


@router.get("/manage/feedback/same")
def same_window(request: Request, note: int = 0, issue: int = 0, q: str = "", part: int = 0, db: Session = Depends(get_db)):
    """Same as which issue? Search the issues; join a waiting note to one, or close an issue as the same as one (R2)."""
    _, denied = _admin(request)
    if denied:
        return denied
    n = db.get(FftNote, note) if note else None
    this = db.get(FftIssue, issue) if issue else None
    if n is None and this is None:
        raise HTTPException(404)
    found = select(FftIssue).where(FftIssue.id != (this.id if this else 0)).order_by(FftIssue.state == "closed", FftIssue.id.desc())
    if q.strip():
        found = found.where(FftIssue.title.ilike(f"%{q.strip()[:60]}%"))
    options = [{"i": i, "notes": notes_of_issue(db, i), "word": views.ISSUE_WORD[i.state] if i.state != "closed" else "closed: " + views.CLOSED_WORD.get(i.close_reason or "", "").lower()}
               for i in db.scalars(found.limit(20))]
    return templates.TemplateResponse(request, "_fft_same.html", {"note": n, "issue": this, "q": q, "options": options,
                                                                    "senders": senders, "partial": bool(part)})


@router.get("/manage/feedback/close")
def close_window(request: Request, issue: int, db: Session = Depends(get_db)):
    _, denied = _admin(request)
    if denied:
        return denied
    i = db.get(FftIssue, issue) or _missing()
    return templates.TemplateResponse(request, "_fft_close.html", {"i": i, "senders": senders(notes_of_issue(db, i)),
                                                                     "reasons": views.CLOSED_WORD})


# ------------------------------------------------------------------ pictures and the page as drawn


@router.get("/manage/feedback/pictures/{pic_id:int}")
def picture(request: Request, pic_id: int, db: Session = Depends(get_db)):
    """A note's picture for an admin: the safe copy, always (T5); the full one only ever goes to its sender."""
    _, denied = _admin(request)
    if denied:
        return denied
    pic = db.get(FftPicture, pic_id) or _missing()
    key = pic.safe_key or _missing()
    return files.serve(key, next((t for t, (ext, _) in files.TYPES.items() if key.endswith(ext)), "image/png"), cache_control="private, no-store", release=db)


@router.get("/manage/feedback/notes/{note_id:int}/page")
def drawn(request: Request, note_id: int, db: Session = Depends(get_db)):
    """The page as drawn, as text (it never runs here), with its sender's private parts already emptied (T4, T5)."""
    _, denied = _admin(request)
    if denied:
        return denied
    note = db.get(FftNote, note_id) or _missing()
    return Response(note.html or "", media_type="text/plain; charset=utf-8", headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "no-store"})


@router.post("/manage/feedback/lines/{line_id:int}")
def line_approve(request: Request, line_id: int, db: Session = Depends(get_db)):
    """A player's later line (their reply, their Still broken) approved: now Claude reads it (T1)."""
    user, denied = _admin(request)
    if denied:
        return denied
    line = db.get(FftLine, line_id) or _missing()
    _act(lambda: rules.approve_line(db, f"user:{views.person(db, user)['id']}", line))
    db.commit()
    request.session["toast"] = "Approved: Claude reads it"
    issue = line.issue_id or (db.get(FftNote, line.note_id).issue_id if line.note_id else None)
    return _back(request, f"i{issue}" if issue else f"n{line.note_id}")


templates.env.globals["event_words"] = views.event_words
templates.env.filters["local_href"] = views.local_href
templates.env.filters["note_title"] = views.title_of
