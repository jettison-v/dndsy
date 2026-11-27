"""Backstage › Global › Feedback (screens 10–14 of docs/mockups/found-fixed-tried/): the record of every note and issue,
admins only, as a Reader: the list, and the open thing beside it.

- **To approve**: a player's note, which Claude sees none of until it's approved (T1), from its safe copy (T5). Approve
  it as a new issue, Same as… an issue already filed (R2), an idea, a question answered, or decline it with why; a
  corner card offers Undo for a minute.
- **Open**, **Ready to try**, **Closed**: issues, each with the notes that became it, its conversation (to Claude, or to
  everyone who sent its notes), its Product Area › Feature with Change… (the Product Taxonomy, Nov 18), Same as…, Close with a reason… (its senders read the reason),
  Reopen. A fix a player's words prompted waits for **OK to merge** (R17).
- **Ideas**: what was taken up as an idea, until the Roadmap takes it.

The issue tabs group their rows under Product Area headings (Brett chose A on docs/mockups/product-taxonomy/): a chip per
Product Area with open work narrows the list, and the Features of the one pressed hang under it as a tray.

Every change goes through app/fft/rules.py."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app import files, web
from app.db import get_db
from app.fft import rules, taxonomy, testing_page, views
from app.fft.host import is_admin
from app.fft.models import (
    FftArea,
    FftCheck,
    FftEvent,
    FftIdea,
    FftIssue,
    FftLine,
    FftNote,
    FftPicture,
    FftPull,
    FftQuestion,
    FftSeen,
    FftTry,
    FftTryIssue,
)
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
    asked = db.scalar(select(func.count()).select_from(FftNote).where(FftNote.state == "filed", FftNote.filed_as == "question")) or 0
    return {"approve": views.to_approve(db), "open": sum(by.get(s, 0) for s in OPEN_STATES) + asked, "ready": by.get("ready", 0),
            "closed": 0,  # (a closed thing isn't counted: a count means there's something there to do)
            "ideas": db.scalar(select(func.count()).select_from(FftIdea).where(FftIdea.state.in_(("new", "roadmap")))) or 0}


def notes_of_issue(db: Session, issue: FftIssue) -> list[FftNote]:
    return list(db.scalars(select(FftNote).where(rules.on_issue(issue.id)).order_by(FftNote.id)))  # (a split part's too, issue 22)


def senders(notes: list[FftNote]) -> list[str]:
    """The first names of a list of notes' senders, each once, in order."""
    out = []
    for n in notes:
        if n.role != "admin" and n.first_name not in out:
            out.append(n.first_name)
    return out


def pictures(db: Session, note: FftNote) -> list[FftPicture]:
    return list(db.scalars(select(FftPicture).where(FftPicture.note_id == note.id).order_by(FftPicture.id)))


FOUND_BY = ("sentry", "speed", "live_test", "iphone", "review", "claude")  # (Who found it's chips beyond players and checks)


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
            word, tone = idea_word(d)
            out.append({"key": f"d{d.id}", "title": d.title, "word": word, "tone": tone, "sub": ""})
        return out
    q = _issue_q(tab).order_by(FftIssue.id.desc())
    if area:
        q = q.where(FftIssue.area_id == area)
    if chip == "players":
        q = q.where(FftIssue.from_player.is_(True))
    elif chip in rules.ISSUE_KINDS:  # (Fixes, Improvements: Nov 20)
        q = q.where(FftIssue.kind == chip)
    elif chip == "checks":  # (Found on a check: what a check's try turned up; an issue a check is written for shows it in
        # Where it stands. Brett's round, Nov 18, issue 33: "From checks" said neither)
        q = q.where(or_(FftIssue.origin_try_id.isnot(None), FftIssue.id.in_(select(FftTryIssue.issue_id))))
    if chip in FOUND_BY:  # (Who found it, by where it came from: R10's slice 5; its own source in the query, before the
        q = q.where(FftIssue.source.in_((chip, "")))  # limit; one made before sources were kept is worked out below)
    for i in db.scalars(q.limit(300)):
        notes = notes_of_issue(db, i)
        if chip in FOUND_BY and rules.source_of(i, bool(notes)) != chip:
            continue
        turn, name = views.issue_turn(db, i)
        word, tone = views.turn_pill(turn, name)
        bits = [views.ISSUE_WORD[i.state] if i.state != "closed" else views.CLOSED_WORD.get(i.close_reason or "", "Closed")]
        if i.reopened and i.state != "closed":
            bits.append("came back")
        f = taxonomy.feature(i.feature)
        if f:
            bits.append(f.title)
        if who := senders(notes):
            bits.append(", ".join(who))
        else:  # (where it came from, when no one's note did: R10's slice 5)
            bits.append(rules.SOURCE_FROM[rules.source_of(i, bool(notes))])
        out.append({"key": f"i{i.id}", "title": i.title, "word": word, "tone": tone, "sub": " · ".join(bits), "kind": i.kind,
                    "pa": f.area if f else "", "feature": f.key if f else ""})
    if tab == "open" and not chip and not area:  # (a question sent for Claude to answer, waiting: Claude's; issue 27)
        for n in db.scalars(select(FftNote).where(FftNote.state == "filed", FftNote.filed_as == "question").order_by(FftNote.id)):
            word, tone = views.turn_pill("claude")
            out.append({"key": f"n{n.id}", "title": views.title_of(n.text), "word": word, "tone": tone,
                        "sub": f"A question · {n.first_name}", "loose": "questions"})
    if tab == "closed" and not chip and not area:  # (notes decided without an issue: declined, or a question answered)
        for n in db.scalars(select(FftNote).where(or_(FftNote.state == "declined", FftNote.filed_as == "answered")).order_by(FftNote.id.desc()).limit(200)):
            word, tone = views.turn_pill("closed")
            out.append({"key": f"n{n.id}", "title": views.title_of(n.text), "word": "Answered" if n.filed_as == "answered" else "Declined",
                        "tone": tone, "sub": f"{n.first_name} · {views.KIND_SAID.get(n.kind, '').lower()}", "loose": "notes"})
    return out


LOOSE = {"questions": "Questions for Claude", "notes": "Notes decided"}  # (rows that are notes, not issues: their group)


def idea_word(d: FftIdea) -> tuple[str, str]:
    """An idea's state as a word and its tone (its row, and Where it stands in the reader)."""
    return {"roadmap": ("On the Roadmap", "claude"), "shipped": ("Built", "quiet"), "declined": ("Declined", "quiet")}.get(d.state, ("New idea", "ask"))


IDEA_SAYS = {"roadmap": "On the Roadmap: it waits its turn there.", "shipped": "Built: it's in askdnd.", "declined": "Not taken up: its senders read why.",
             "new": "New: put it on the Roadmap, mark it built, or decline it with why."}


def by_area(listed: list[dict], pa: str, feature: str) -> dict:
    """The issue tabs by Product Area: a chip per area with rows (its count), the Features of the one picked (theirs),
    and the rows it shows under headings in the list's order, those with no Feature yet first."""
    chips = [{"a": a, "n": sum(1 for r in listed if r.get("pa") == a.key)} for a in taxonomy.areas()]
    chips = [c for c in chips if c["n"]]
    unsorted = sum(1 for r in listed if r["key"][:1] == "i" and not r.get("pa"))
    picked = taxonomy.area(pa)
    feats = [{"f": f, "n": sum(1 for r in listed if r.get("feature") == f.key)} for f in picked.features] if picked else []
    shown = [r for r in listed if (not picked or r.get("pa") == pa) and (not feature or r.get("feature") == feature)]
    groups = []
    if questions := [r for r in shown if r.get("loose") == "questions"]:  # (first on Open: each a quick answer)
        groups.append({"key": "questions", "title": LOOSE["questions"], "rows": questions})
    if not picked and (nofeat := [r for r in shown if r["key"][:1] == "i" and not r.get("pa")]):
        groups.append({"key": "", "title": "No Feature yet", "rows": nofeat})
    for a in taxonomy.areas():
        if mine := [r for r in shown if r.get("pa") == a.key]:
            groups.append({"key": a.key, "title": a.title, "rows": mine})
    if decided := [r for r in shown if r.get("loose") == "notes"]:  # (on Closed: notes decided without an issue)
        groups.append({"key": "notes", "title": LOOSE["notes"], "rows": decided})
    return {"chips": chips, "unsorted": unsorted, "pa": picked, "feats": [x for x in feats if x["n"]], "feature": feature if picked else "",
            "groups": groups, "rows": [r for g in groups for r in g["rows"]]}


def last_line(db: Session, note: FftNote) -> int:
    """The newest line on a note: an approval names it, so words added after the page was drawn aren't approved
    unseen (T1, R14)."""
    return db.scalar(select(func.max(FftLine.id)).where(FftLine.note_id == note.id)) or 0


def note_view(db: Session, note: FftNote, viewer_id: int | None) -> dict:
    pics = pictures(db, note)
    return {"n": note, "pics": pics, "covered": any(p.key != p.safe_key for p in pics),
            "lines": list(db.scalars(select(FftLine).where(FftLine.note_id == note.id).order_by(FftLine.id))),
            "mine": note.user_id and note.user_id == viewer_id, "seen": last_line(db, note)}


def issue_view(db: Session, issue: FftIssue, viewer_id: int | None) -> dict:
    notes = notes_of_issue(db, issue)
    turn, name = views.issue_turn(db, issue)
    pulls = [p.id for p in db.scalars(select(FftPull).where(or_(FftPull.issue_id == issue.id, rules._names_pull_any(issue.pr))))]  # (its round trip, item 39)
    events = [e for e in db.scalars(select(FftEvent).where(or_((FftEvent.thing == "issue") & (FftEvent.thing_id == issue.id),
                                                               (FftEvent.thing == "note") & FftEvent.thing_id.in_([n.id for n in notes] or [0]),
                                                               (FftEvent.thing == "pull") & FftEvent.thing_id.in_(pulls or [0])))
                                    .order_by(FftEvent.id.desc()))
              if e.thing != "pull" or views.pull_worth_saying(e)]
    asked = [views.question_view(q) for q in db.scalars(select(FftQuestion).where(FftQuestion.about == "issue", FftQuestion.about_id == issue.id)
                                                           .order_by(FftQuestion.id))]
    return {"i": issue, "turn": turn, "pill": views.turn_pill(turn, name), "sentence": views.issue_sentence(db, issue), "asked": asked,
            "source_from": rules.SOURCE_FROM[rules.source_of(issue, bool(notes))],  # (where it came from: R10's slice 5)
            "area": db.get(FftArea, issue.area_id) if issue.area_id else None, "feature": taxonomy.feature(issue.feature),
            "pa": taxonomy.area(taxonomy.feature(issue.feature).area) if taxonomy.feature(issue.feature) else None, "notes": [note_view(db, n, viewer_id) for n in notes],
            "senders": senders(notes), "lines": list(db.scalars(select(FftLine).where(FftLine.issue_id == issue.id).order_by(FftLine.id))),
            "may_merge": rules.may_merge(db, issue), "events": events, "listening": views.listening(db),
            "checks": views.issue_checks(db, issue), "found": found_on_checks(db, issue), **new_since(db, issue, viewer_id, asked)}


DEVICE = {"laptop": "on the laptop", "iphone": "on the iPhone", "ipad": "on the iPad", "mac_mini": "on the Mac Mini"}


def found_on_checks(db: Session, issue: FftIssue) -> list[dict]:
    """The tries of checks that found this issue (Something's wrong…, Brett's pick A on docs/mockups/fft-reader/: What was
    found holds them with its notes): the check, the device, when, and whether it stopped the check or the round."""
    out = []
    for t, ti, c in db.execute(select(FftTry, FftTryIssue, FftCheck).join(FftTryIssue, FftTryIssue.try_id == FftTry.id)
                               .join(FftCheck, FftCheck.id == FftTry.check_id)
                               .where(FftTryIssue.issue_id == issue.id, FftTry.replaced.is_(False)).order_by(FftTry.id)):
        out.append({"t": t, "check": c, "device": DEVICE.get(t.device, t.device), "blocking": ti.blocking, "stops_round": ti.stops_round,
                    "still": ti.how == "still"})
    return out


def new_since(db: Session, issue: FftIssue, viewer_id: int | None, asked: list[dict]) -> dict:
    """What in an issue's conversation is new since this person last opened it (issue 32): lines and questions said after
    their read mark (`FftSeen`) by someone else. Never opened: everything someone else said is new."""
    seen = db.scalar(select(FftSeen.at).where(FftSeen.user_id == viewer_id, FftSeen.issue_id == issue.id)) if viewer_id else None
    after = (lambda at: at is not None and at > seen) if seen else (lambda at: at is not None)
    lines = db.scalars(select(FftLine).where(or_(FftLine.issue_id == issue.id,
                                                 FftLine.note_id.in_(select(FftNote.id).where(rules.on_issue(issue.id))))))
    return {"seen_at": seen,
            "new_lines": {x.id for x in lines if after(x.created_at) and not (x.user_id and x.user_id == viewer_id)},
            "new_asked": {a["q"].id for a in asked if after(a["q"].created_at)}}


def mark_seen(db: Session, viewer_id: int | None, issue: FftIssue) -> None:
    """This person has the issue open: what's said in it until now isn't new to them any more (a read mark, not a state,
    like Notes you sent's `seen`: rules.py keeps the states)."""
    if not viewer_id:
        return
    row = db.scalar(select(FftSeen).where(FftSeen.user_id == viewer_id, FftSeen.issue_id == issue.id))
    if row is None:
        db.add(FftSeen(user_id=viewer_id, issue_id=issue.id, at=rules.now()))
    else:
        row.at = rules.now()
    db.commit()


@router.get("/manage/feedback")
def page(request: Request, tab: str = "", open: str = "", chip: str = "", area: int = 0, pa: str = "", feature: str = "",
         db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    n = counts(db)
    tab = tab if tab in dict(TABS) else ("approve" if n["approve"] else "open")
    chip = chip if chip in ("players", "checks", *FOUND_BY, *rules.ISSUE_KINDS) else ""
    keyed = db.get(FftArea, area) if area else None
    if keyed is not None and keyed.key:  # (a Product Area's batch, as Where it stands links it: its chip)
        pa, area = keyed.key, 0
    listed = rows(db, tab, chip, area)
    grouped = by_area(listed, pa, feature) if tab in ("open", "ready", "closed") else None
    if grouped:
        listed = grouped["rows"]
    pick = open if open[:1] in ("n", "i", "d") and open[1:].isdigit() else ""  # (an old link to one item: it opens in the item window)
    return templates.TemplateResponse(request, "fft_feedback.html", {
        "tab": tab, "tabs": TABS, "counts": n, "rows": listed, "pick": pick, "chip": chip, "area": area, "area_said": keyed.title if area and keyed is not None else "", "pa": pa, "feature": feature,
        "grouped": grouped, "taxonomy": taxonomy.areas(), "from_": from_key(tab, chip, area, pa, feature),
        "status": testing_page.status(db),  # (the bar every Our work page has: issue 109)
        "toast": request.session.pop("toast", None)})


def listed_keys(db: Session, tab: str, chip: str = "", area: int = 0, pa: str = "", feature: str = "") -> list[str]:
    """The rows of one view of Feedback, in their order: the item window's ↑ ↓ follow it."""
    listed = rows(db, tab, chip, area)
    grouped = by_area(listed, pa, feature) if tab in ("open", "ready", "closed") else None
    return [r["key"] for r in (grouped["rows"] if grouped else listed)]


def from_key(tab: str, chip: str, area: int, pa: str, feature: str) -> str:
    """Which list an item window was opened from (?from=), so ↑ ↓ walk that list: feedback:<tab>:<chip>:<area>:<pa>:<feature>."""
    return ":".join(["feedback", tab, chip, str(area or ""), pa, feature])


def picked_of(db: Session, key: str, viewer_id: int | None) -> dict | None:
    """A note, an issue or an idea, as its reader draws it (the item window, app/fft/item_page.py)."""
    kind, ident = key[:1], int(key[1:]) if key[1:].isdigit() else 0
    if kind == "n" and (note := db.get(FftNote, ident)):
        return {"kind": "note", **note_view(db, note, viewer_id)} | ({"issue": issue_view(db, db.get(FftIssue, note.issue_id), viewer_id)} if note.issue_id else {})
    if kind == "i" and (issue := db.get(FftIssue, ident)):
        picked = {"kind": "issue", **issue_view(db, issue, viewer_id)}
        mark_seen(db, viewer_id, issue)  # (drawn with what's new marked, then it's seen)
        return picked
    if kind == "d" and (idea := db.get(FftIdea, ident)):
        return {"kind": "idea", "d": idea, "word": idea_word(idea), "says": IDEA_SAYS.get(idea.state, ""), "notes": [note_view(db, x, viewer_id) for x in db.scalars(select(FftNote).where(FftNote.idea_id == idea.id))]}
    return None


def tab_of(picked: dict) -> str:
    """The Feedback tab an item lives on (its forms' ?tab=, where an answer lands)."""
    if picked["kind"] == "note":
        return "approve" if picked["n"].state == "waiting" else "open"
    if picked["kind"] == "issue":
        st = picked["i"].state
        return "closed" if st == "closed" else "ready" if st == "ready" else "open"
    return "ideas"


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
                seen: str = Form(""), db: Session = Depends(get_db)):
    """Approve a waiting note (as an issue, joined to one, an idea, a question answered), decline it with why, or undo
    that within a minute (R1, R2). Adding a line to a note's conversation (to its sender, or to Claude)."""
    user, denied = _admin(request)
    if denied:
        return denied
    note = db.get(FftNote, note_id) or _missing()
    actor = f"user:{views.person(db, user)['id']}"
    undo = f"/manage/feedback/notes/{note.id}/undo"
    if do != "tell" and note.state == "waiting" and seen.isdigit() and int(seen) != last_line(db, note):
        request.session["toast"] = web.notice(f"{note.first_name} added to it while you were looking: read it again first.", "warn")
        return RedirectResponse(f"{BACK}?tab=approve&open=n{note.id}", status_code=303)
    if do in ("issue", "fix", "improvement"):  # (Nov 20: a fix or an improvement, the two kinds of change to a Product Area)
        made = _act(lambda: rules.file_issue(db, actor, note, kind="" if do == "issue" else do))
        _said(request, f"Approved as {'an improvement' if made.kind == 'improvement' else 'a fix'}: it's Claude's", undo)
        key = f"i{made.id}"
    elif do == "same":
        target = db.get(FftIssue, issue) or _missing()
        made = _act(lambda: rules.join_issue(db, actor, note, target))
        _said(request, f"Joined “{made.title}”", undo)
        key = f"i{made.id}"
    elif do == "idea":  # (an idea that needs discussion: a Roadmap idea, Nov 20)
        made = _act(lambda: rules.file_roadmap_idea(db, actor, note))
        _said(request, "On the Roadmap as an idea: Claude scopes it when it's next", undo)
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
    try:
        rules.undo_decision(db, f"user:{views.person(db, user)['id']}", note)
    except rules.RuleError as e:
        request.session["toast"] = web.notice(e.words, "warn")
        return RedirectResponse(f"{BACK}?open=n{note.id}", status_code=303)
    db.commit()
    request.session["toast"] = "Undone: it's waiting for you again"
    return RedirectResponse(f"{BACK}?tab=approve&open=n{note.id}", status_code=303)


@router.post("/manage/feedback/issues/{issue_id:int}")
def issue_change(request: Request, issue_id: int, do: str = Form(...), words: str = Form(""), to: str = Form(""), feature: str = Form(""), kind: str = Form(""),
                 reason: str = Form(""), same_as: int = Form(0), note: int = Form(0), seen: str = Form(""),
                 part_title: list[str] = Form([]), part_feature: list[str] = Form([]), db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    i = db.get(FftIssue, issue_id) or _missing()
    me = views.person(db, user)
    actor = f"user:{me['id']}"
    if do == "feature":
        _act(lambda: rules.set_feature(db, actor, i, feature))
        _said(request, f"Now in {taxonomy.path(i.feature)}: Claude sees it")
    elif do == "kind":
        _act(lambda: rules.set_kind(db, actor, i, kind))
        _said(request, "Now an improvement" if i.kind == "improvement" else "Now a fix")
    elif do == "close":
        other = db.get(FftIssue, same_as) if same_as else None
        if reason == "same" and other is None:
            raise HTTPException(400, "Same as which issue?")
        _act(lambda: rules.close(db, actor, i, reason, words, same_as=other, seen=seen or None))
        _said(request, "Closed: its senders read why" if words.strip() else "Closed")
    elif do == "split":  # (issue 22: this issue keeps the first part, `words` and `feature` its title and Feature)
        feats = list(part_feature) + [""] * len(part_title)
        made = _act(lambda: rules.split_issue(db, actor, i, [(t[:120], feats[n][:20]) for n, t in enumerate(part_title[:8])], title=words[:120], feature=feature[:20]))
        _said(request, f"Split into {len(made) + 1}: each has its notes, and their senders hear how each turns out")
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
        try:
            rules.retitle(db, actor, i, words)
        except rules.RuleError as e:
            raise HTTPException(400, e.words) from e
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
    try:
        rules.idea_state(db, f"user:{views.person(db, user)['id']}", d, do, words)
    except rules.RuleError as e:
        raise HTTPException(400, e.words) from e
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
    return templates.TemplateResponse(request, "_fft_same.html", {"note": n, "issue": this, "q": q, "options": options, "seen": last_line(db, n) if n else 0,
                                                                    "senders": senders, "partial": bool(part)})


@router.get("/manage/feedback/split")
def split_window(request: Request, issue: int, db: Session = Depends(get_db)):
    """Split… (issue 22, Brett's pick 2A): an open issue with several problems in it, as several issues, its notes the
    evidence of each (docs/mockups/fft-round-2/, screen 2A)."""
    _, denied = _admin(request)
    if denied:
        return denied
    i = db.get(FftIssue, issue) or _missing()
    notes = notes_of_issue(db, i)
    return templates.TemplateResponse(request, "_fft_split.html", {"i": i, "notes": notes, "senders": senders(notes), "taxonomy": taxonomy.areas()})


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
def line_approve(request: Request, line_id: int, do: str = Form(""), db: Session = Depends(get_db)):
    """A player's later line (their reply, their Still broken) approved: now Claude reads it (T1). Or Claude's question
    to a note's sender: Send (`do=send`) or Don't send (`do=drop`; ask back, R10's slice 5)."""
    user, denied = _admin(request)
    if denied:
        return denied
    line = db.get(FftLine, line_id) or _missing()
    me = f"user:{views.person(db, user)['id']}"
    if do in ("send", "drop"):
        _act(lambda: rules.send_ask(db, me, line, do == "send"))
        db.commit()
        request.session["toast"] = "Sent: it's on their note" if do == "send" else "Not sent: it stays here, theirs never sees it"
        return _back(request, f"n{line.note_id}")
    _act(lambda: rules.approve_line(db, me, line))
    db.commit()
    request.session["toast"] = "Approved: Claude reads it"
    issue = line.issue_id or (db.get(FftNote, line.note_id).issue_id if line.note_id else None)
    return _back(request, f"i{issue}" if issue else f"n{line.note_id}")


templates.env.globals["event_words"] = views.event_words
templates.env.globals["talk"] = views.talk
templates.env.filters["local_href"] = views.local_href
templates.env.filters["note_title"] = views.title_of


@router.get("/manage/product-areas")
def product_areas(request: Request, db: Session = Depends(get_db)):
    """Backstage › Global › Product areas (docs/mockups/product-taxonomy/, screen 1): the Product Taxonomy as askdnd keeps
    it (app/data/taxonomy.json), each Feature with its open issues, a press away from them on Feedback."""
    _, denied = _admin(request)
    if denied:
        return denied
    open_by = dict(db.execute(select(FftIssue.feature, func.count()).where(FftIssue.state != "closed").group_by(FftIssue.feature)).all())
    plans = dict(db.execute(select(FftArea.key, func.min(FftArea.id)).where(FftArea.key.is_not(None)).group_by(FftArea.key)).all())
    cards = [{"a": a, "n": sum(open_by.get(f.key, 0) for f in a.features), "features": [(f, open_by.get(f.key, 0)) for f in a.features],
              "plan": plans.get(a.key)} for a in taxonomy.areas()]
    cards.sort(key=lambda c: -c["n"])  # (the busiest first, the list's order between equals: Brett's pick PA1, Nov 25)
    return templates.TemplateResponse(request, "manage_product_areas.html", {
        "cards": cards, "features": sum(len(a.features) for a in taxonomy.areas()), "loose": open_by.get("", 0)})
