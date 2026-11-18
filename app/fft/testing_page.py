"""Manage › askdnd › Testing (screens 1–8 of docs/mockups/found-fixed-tried/): everything that's Brett's turn, and
trying what Claude built.

- **For you** is a view of everything Brett's, in the one order (the Roadmap's items, their areas): checks to try (on
  the device he's on, or another he must use), Claude's questions and decisions, fixes waiting for his OK to merge,
  then the table's notes to approve and ideas to place, then Roadmap steps that are his. One pill on each: Yours.
- **A check**: the walkthrough the card will show, what he should see, why it's there (what was found, what changed),
  ▶ Try it, ✓ Passed, ✗ Something's wrong…, Can't try…; its history (every try, version and fix).
- **A round** (▶ Start round): the checks for this device page by page with the card (left by default, draggable,
  folds; keys P, F, C). Passed moves on with Undo in the corner card; Something's wrong… fails the try with its first
  issue, and the card offers ✗ Another…, Change result… and Next check →. While a round is open nothing merges (R11).
- **Claude's** and **Done**: what's with Claude, and what passed.

Every change goes through app/fft/rules.py."""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access, campaign_paths, config, view_as, web
from app.auth import is_admin
from app.db import get_db
from app.fft import rules, sending, steps, views
from app.fft.models import (
    FftArea,
    FftCheck,
    FftCheckIssue,
    FftCheckVersion,
    FftEvent,
    FftIdea,
    FftIssue,
    FftItem,
    FftNote,
    FftQuestion,
    FftTry,
    FftTryIssue,
)
from app.templating import templates

router = APIRouter()
BACK = "/manage/testing"
ROUND = "fft_round"  # the session's open round: {"id", "checks", "i", "device", "home"}
SHOWS = (("foryou", "For you"), ("stands", "Where it stands"), ("claudes", "Claude's"), ("done", "Done"))
PEOPLES = ("laptop", "iphone", "ipad")  # (Brett's devices; the Mac Mini's runs are Claude's)
DEVICE_SAID = {"laptop": "your laptop", "iphone": "your iPhone", "ipad": "your iPad", "mac_mini": "the Mac Mini"}
STATE_WORD = {"to_try": "To try", "again": "To try again", "later": "Later", "asks": "Claude asks", "failed": "Failed",
              "fixing": "Being fixed", "wrong": "Being rewritten", "blocked": "Blocked", "preflight": "Claude tries it first",
              "passed": "Passed", "retired": "Retired"}


def _admin(request: Request):
    return web.require(request, is_admin, "Testing is for admins.")


def _missing():
    raise HTTPException(404)


def device_of(request: Request) -> str:
    """The device this page is on, as Testing counts them (a check names the ones it must pass on)."""
    asked = request.query_params.get("device", "")
    if asked in PEOPLES:
        return asked
    ua = request.headers.get("user-agent", "")
    return "iphone" if "iPhone" in ua else "ipad" if "iPad" in ua else "laptop"


def where_of(request: Request) -> str:
    if config.STAGING:
        return "staging"
    host = (request.url.hostname or "").lower()
    return "local" if host in ("localhost", "127.0.0.1") or host.endswith(".localhost") else "live"


def app_version() -> str:
    import os

    return (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "local")[:12]


# ------------------------------------------------------------------ a check, read


def version_of(db: Session, c: FftCheck) -> FftCheckVersion | None:
    return db.scalar(select(FftCheckVersion).where(FftCheckVersion.check_id == c.id, FftCheckVersion.version == c.version))


def page_of(db: Session, c: FftCheck) -> str:
    v = version_of(db, c)
    return v.path if v is not None and steps.local_path(v.path) else f"{BACK}?open=c{c.id}"


def check_view(db: Session, c: FftCheck, device: str = "laptop") -> dict:
    v = version_of(db, c)
    st = rules.check_state(db, c)
    mine = [d for d in (c.devices or ["laptop"]) if d in PEOPLES and st["devices"].get(d) in ("to_try", "later")]
    word = "To try again" if st["again"] and st["state"] == "to_try" else STATE_WORD.get(st["state"], st["state"])
    issues = list(db.scalars(select(FftIssue).join(FftCheckIssue, FftCheckIssue.issue_id == FftIssue.id).where(FftCheckIssue.check_id == c.id)))
    return {"c": c, "v": v, "steps": steps.walk("\n".join(v.steps)) if v else [], "state": st, "word": word,
            "turn": {"brett": "yours", "claude": "claude", "closed": "closed"}[st["turn"]], "mine": mine,
            "here": device in mine, "devices": st["devices"], "issues": issues, "area": db.get(FftArea, c.area_id) if c.area_id else None,
            "sentence": sentence(st, issues, device, mine)}


def sentence(st: dict, issues: list[FftIssue], device: str, mine: list[str]) -> str:
    """The line under a check's title: what it means for Brett, in one sentence (screen 1)."""
    s = st["state"]
    on = "" if not mine or device in mine else f" On {DEVICE_SAID[mine[0]]}."
    if s == "to_try" and st["again"]:
        fixed = [i for i in issues if i.state in ("ready", "closed")]
        return f"To try again: the {len(fixed)} issue{'s' if len(fixed) != 1 else ''} you found {'are' if len(fixed) != 1 else 'is'} fixed and live.{on}"
    return {"to_try": f"To try: Claude built it and tried it first.{on}", "later": f"You said later.{on}",
            "asks": "Claude asks you something about it first.", "failed": "Your try failed; it comes back to you once its issues are fixed and live.",
            "fixing": "Claude is fixing what was found; it comes back when the fix is live.", "wrong": "Claude is rewriting it (you said it was wrong).",
            "blocked": "Blocked by another issue; it comes back when that's fixed.", "preflight": "Claude tries it first, then it's yours.",
            "passed": "Passed.", "retired": "Retired: it no longer applies."}.get(s, "")


def why_line(db: Session, c: FftCheck, v: FftCheckVersion | None) -> str:
    """Why it's here, in words: what was found (its issues' titles) and what changed."""
    found = [i.title for i in db.scalars(select(FftIssue).join(FftCheckIssue, FftCheckIssue.issue_id == FftIssue.id).where(FftCheckIssue.check_id == c.id))]
    bits = []
    if found:
        bits.append(", ".join(found[:4]) + ("…" if len(found) > 4 else "") + ".")
    if v is not None and v.why:
        bits.append(v.why)
    return " ".join(bits)


def history(db: Session, c: FftCheck) -> list[dict]:
    """Every try, version and fix, newest first (screen 7). A corrected try is struck through with what replaced it."""
    out = []
    for t in db.scalars(select(FftTry).where(FftTry.check_id == c.id)):
        n = len(list(db.scalars(select(FftTryIssue.issue_id).where(FftTryIssue.try_id == t.id))))
        who = "the Mac Mini" if t.actor == "mini" else "you"
        what = {"passed": "Passed", "failed": "Failed", "cant": {"later": "Later", "blocked": "Blocked", "wrong": "The check is wrong"}.get(t.cant_kind, "Can't try"),
                "untried": "Back to try"}[t.result]
        line = f"{what} by {who} · {DEVICE_SAID.get(t.device, t.device).replace('your ', '')} · v{t.version}" + (f" · {n} issue{'s' if n != 1 else ''}" if n else "") \
            + (f" · {t.where}" if t.where != "live" else "")
        replaced_by = db.scalar(select(FftTry).where(FftTry.replaces_id == t.id))
        out.append({"at": t.created_at, "line": line, "why": t.why if t.result in ("cant", "untried") or t.replaces_id else "",
                    "struck": t.replaced, "replaced": f"replaced by “{replaced_by.result}”" + (f": {replaced_by.why}" if replaced_by and replaced_by.why else "") if replaced_by else "",
                    "tone": "failed" if t.result == "failed" else "passed" if t.result == "passed" else "quiet"})
    for v in db.scalars(select(FftCheckVersion).where(FftCheckVersion.check_id == c.id)):
        out.append({"at": v.created_at, "line": f"{'Written' if v.version == 1 else 'Version ' + str(v.version)} by Claude · v{v.version}"
                    + (f" · {v.why}" if v.why and v.version > 1 else ""), "why": "", "struck": False, "replaced": "", "tone": "claude"})
    issue_ids = list(db.scalars(select(FftCheckIssue.issue_id).where(FftCheckIssue.check_id == c.id)))
    for e in db.scalars(select(FftEvent).where(FftEvent.thing == "issue", FftEvent.thing_id.in_(issue_ids or [0]), FftEvent.kind == "issue_live")):
        issue = db.get(FftIssue, e.thing_id)
        out.append({"at": e.at, "line": f"Fixed by Claude, live · “{issue.title if issue else ''}”" + (f" ({issue.pr.rsplit('/', 1)[-1]})" if issue and issue.pr else ""),
                    "why": "", "struck": False, "replaced": "", "tone": "claude"})
    return sorted(out, key=lambda x: x["at"] or rules.now(), reverse=True)


# ------------------------------------------------------------------ For you: everything that's Brett's turn


def for_you(db: Session, device: str) -> list[dict]:
    """Groups of rows, in the one order: each area's checks, questions and fixes to OK; then the table's; then the
    Roadmap's. Each row: key, title, sub, kind, area_id."""
    groups: dict = {}
    order: list = []

    def put(gkey, gtitle, row, area_id=None):
        if gkey not in groups:
            groups[gkey] = {"key": gkey, "title": gtitle, "rows": [], "area_id": area_id, "checks": 0}
            order.append(gkey)
        groups[gkey]["rows"].append(row)
        if row["kind"] == "check" and row.get("here"):
            groups[gkey]["checks"] += 1

    areas = {a.id: a for a in db.scalars(select(FftArea))}
    items = {it.id: it for it in db.scalars(select(FftItem))}

    def area_key(area_id):
        a = areas.get(area_id) if area_id else None
        it = items.get(a.item_id) if a else None
        return (it.place if it else 9999, a.place if a else 9999, area_id or 0)

    rows = []
    for c in db.scalars(select(FftCheck).where(FftCheck.retired.is_(False)).order_by(FftCheck.place, FftCheck.id)):
        cv = check_view(db, c, device)
        if cv["turn"] != "yours" or cv["state"]["state"] == "asks":
            continue
        where = "" if cv["here"] or not cv["mine"] else f" · on {DEVICE_SAID[cv['mine'][0]]}"
        rows.append((area_key(c.area_id), c.area_id, {"key": f"c{c.id}", "title": c.title, "kind": "check", "here": cv["here"],
                                                       "sub": f"{cv['word']}{where} · {c.minutes} min", "minutes": c.minutes}))
    for q in db.scalars(select(FftQuestion).where(FftQuestion.answered_at.is_(None)).order_by(FftQuestion.id)):
        aid = None
        if q.about == "issue" and q.about_id and (i := db.get(FftIssue, q.about_id)):
            aid = i.area_id
        elif q.about == "check" and q.about_id and (c := db.get(FftCheck, q.about_id)):
            aid = c.area_id
        elif q.about == "area":
            aid = q.about_id
        decision = q.about == "document"
        rows.append((area_key(aid), aid, {"key": f"q{q.id}", "title": views.title_of(q.text), "kind": "decision" if decision else "question",
                                          "sub": "A decision: look, then one verdict" if decision else "Claude asks"}))
    for i in db.scalars(select(FftIssue).where(FftIssue.state == "merge_ok").order_by(FftIssue.id)):
        rows.append((area_key(i.area_id), i.area_id, {"key": f"i{i.id}", "title": i.title, "kind": "merge", "sub": "Fix ready: your OK to merge (players asked)"}))
    for i in db.scalars(select(FftIssue).where(FftIssue.state == "ready", FftIssue.confirm_by.is_(None)).order_by(FftIssue.id)):
        if not db.scalar(select(FftCheckIssue.check_id).where(FftCheckIssue.issue_id == i.id)):
            rows.append((area_key(i.area_id), i.area_id, {"key": f"i{i.id}", "title": i.title, "kind": "ready", "sub": "Fixed and live, with no check: does it work?"}))
    for _, aid, row in sorted(rows, key=lambda r: r[0]):
        a = areas.get(aid) if aid else None
        put(f"a{aid or 0}", a.title if a else "In no area yet", row, aid)
    for n in db.scalars(select(FftNote).where(FftNote.state == "waiting").order_by(FftNote.id)):
        put("table", "From the table", {"key": f"n{n.id}", "title": views.title_of(n.text), "kind": "note", "sub": f"{n.first_name}'s note waits for you"})
    for d in db.scalars(select(FftIdea).where(FftIdea.state == "new").order_by(FftIdea.id)):
        who = db.scalar(select(FftNote.first_name).where(FftNote.idea_id == d.id))
        put("table", "From the table", {"key": f"d{d.id}", "title": d.title, "kind": "idea", "sub": f"{who}'s idea to place" if who else "An idea to place"})
    for it in db.scalars(select(FftItem).where(FftItem.next_whose == "brett").order_by(FftItem.place, FftItem.id)):
        put("roadmap", "From the Roadmap", {"key": f"r{it.id}", "title": it.title, "kind": "roadmap", "sub": it.next_step or "Its next step is yours"})
    return [groups[k] for k in order]


def summary(groups: list[dict]) -> dict:
    rows = [r for g in groups for r in g["rows"]]
    count = lambda kind: sum(1 for r in rows if r["kind"] == kind)
    checks = [r for r in rows if r["kind"] == "check"]
    bits = [(len(checks), "check", "checks", f" (about {sum(r['minutes'] for r in checks)} minutes)" if checks else ""),
            (count("question"), "question", "questions", ""), (count("decision"), "decision", "decisions", ""),
            (count("merge"), "fix to OK", "fixes to OK", ""), (count("ready"), "fix to look at", "fixes to look at", ""),
            (count("note"), "note to approve", "notes to approve", ""), (count("idea"), "idea", "ideas", ""),
            (count("roadmap"), "Roadmap step", "Roadmap steps", "")]
    return {"n": len(rows), "line": " · ".join(f"{n} {one if n == 1 else many}{extra}" for n, one, many, extra in bits if n)}


def others(db: Session, show: str, device: str) -> list[dict]:
    """Claude's (what's with Claude) and Done (passed or retired): the checks, a row each, by area."""
    groups: dict = {}
    order = []
    for c in db.scalars(select(FftCheck).order_by(FftCheck.area_id.nulls_last(), FftCheck.place, FftCheck.id)):
        cv = check_view(db, c, device)
        if (show == "claudes" and cv["turn"] != "claude") or (show == "done" and cv["turn"] != "closed"):
            continue
        a = cv["area"]
        key = f"a{a.id if a else 0}"
        if key not in groups:
            groups[key] = {"key": key, "title": a.title if a else "In no area yet", "rows": [], "area_id": a.id if a else None, "checks": 0}
            order.append(key)
        groups[key]["rows"].append({"key": f"c{c.id}", "title": c.title, "kind": "check", "sub": cv["word"], "turn": cv["turn"]})
    return [groups[k] for k in order]


# ------------------------------------------------------------------ the page


@router.get("/manage/testing")
def page(request: Request, show: str = "", open: str = "", db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    rules._expire_rounds(db)
    device = device_of(request)
    show = show if show in dict(SHOWS) else "foryou"
    groups = for_you(db, device) if show == "foryou" else others(db, show, device) if show in ("claudes", "done") else []
    keys = [r["key"] for g in groups for r in g["rows"]]
    pick = open if open[:1] in ("c", "q", "i", "n", "d", "r") and open[1:].isdigit() else (keys[0] if keys else "")
    picked = _picked(db, pick, device)
    mine = for_you(db, device) if show != "foryou" else groups
    round_checks = [r for g in mine for r in g["rows"] if r["kind"] == "check" and r.get("here")]
    me = views.person(db, user)
    db.commit()
    return templates.TemplateResponse(request, "fft_testing.html", {
        "show": show, "shows": SHOWS, "groups": groups, "pick": pick, "picked": picked, "summary": summary(mine),
        "round_n": len(round_checks), "round_open": request.session.get(ROUND), "device": device, "device_said": DEVICE_SAID,
        "me_id": me["id"], "stands": stands(db) if show == "stands" else None, "listening": views.listening(db),
        "toast": request.session.pop("toast", None)})


def _picked(db: Session, pick: str, device: str) -> dict | None:
    kind, ident = pick[:1], int(pick[1:]) if pick[1:].isdigit() else 0
    if kind == "c" and (c := db.get(FftCheck, ident)):
        cv = check_view(db, c, device)
        return {"kind": "check", **cv, "why": why_line(db, c, cv["v"]), "history": history(db, c), "page": page_of(db, c),
                "last_failed": _last_failed(db, c, device)}
    if kind == "q" and (q := db.get(FftQuestion, ident)):
        return {"kind": "question", "q": q, "about": _about(db, q)}
    if kind == "i" and (i := db.get(FftIssue, ident)):
        return {"kind": "issue", "i": i, "sentence": views.issue_sentence(db, i), "pill": views.turn_pill(*views.issue_turn(db, i))}
    if kind == "n" and (n := db.get(FftNote, ident)):
        return {"kind": "note", "n": n}
    if kind == "d" and (d := db.get(FftIdea, ident)):
        return {"kind": "idea", "d": d}
    if kind == "r" and (it := db.get(FftItem, ident)):
        return {"kind": "roadmap", "it": it}
    return None


def _about(db: Session, q: FftQuestion) -> dict:
    """What a question is about, as a link: an issue on Feedback, a check here, an area, or a document."""
    if q.about == "issue" and q.about_id and (i := db.get(FftIssue, q.about_id)):
        return {"said": f"the issue “{i.title}”", "href": f"/manage/feedback?tab=open&open=i{i.id}"}
    if q.about == "check" and q.about_id and (c := db.get(FftCheck, q.about_id)):
        return {"said": f"the check “{c.title}”", "href": f"{BACK}?open=c{c.id}"}
    if q.about == "area" and q.about_id and (a := db.get(FftArea, q.about_id)):
        return {"said": f"the {a.title} area", "href": f"{BACK}?show=stands"}
    if q.about == "document" and q.doc_path:
        return {"said": q.doc_path.rsplit("/", 2)[-2] if "/" in q.doc_path else q.doc_path, "href": "/manage/documents", "doc": q.doc_path, "version": q.doc_version}
    return {"said": "", "href": ""}


def _last_failed(db: Session, c: FftCheck, device: str) -> FftTry | None:
    t = db.scalar(select(FftTry).where(FftTry.check_id == c.id, FftTry.device == device, FftTry.actor == "person").order_by(FftTry.id.desc()))
    return t if t is not None and t.result == "failed" and not t.replaced else None


def stands(db: Session) -> list[dict]:
    """Where it stands (slice 6 draws it whole): the items in order, their areas, whose turn each is."""
    out = []
    for it in db.scalars(select(FftItem).order_by(FftItem.place, FftItem.id)):
        areas = [{"a": a, "turn": rules.area_turn(db, a), "issues": len(rules.area_open_issues(db, a)), "checks": len(rules.area_checks(db, a))}
                 for a in db.scalars(select(FftArea).where(FftArea.item_id == it.id, FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id))]
        out.append({"it": it, "areas": areas})
    return out


# ------------------------------------------------------------------ trying a check


def _round(request: Request) -> dict | None:
    return request.session.get(ROUND)


def _next_page(db: Session, request: Request) -> str:
    """The round's next check's page, or For you when it's done."""
    r = _round(request)
    if r is None:
        return BACK
    while r["i"] < len(r["checks"]):
        c = db.get(FftCheck, r["checks"][r["i"]])
        if c is not None and check_view(db, c, r["device"])["here"]:
            request.session[ROUND] = r
            return enter(request, db, c, page_of(db, c))
        r["i"] += 1
    request.session[ROUND] = r
    return _end(request, db)


def _end(request: Request, db: Session) -> str:
    r = request.session.pop(ROUND, None)
    if r and (row := db.get(rules.FftRound, r["id"])) and row.ended_at is None:
        rules.end_round(db, "user", row)
    was = (r or {}).get("home")
    email = ((request.session.get("user") or {}).get("email") or "").lower()
    here = access.current_campaign(email)
    if was and email and (here is None or here["id"] != was):
        campaign_paths.remember_in(db, email, was)
    return leave(request, f"{BACK}?show=foryou")


def enter(request: Request, db: Session, c: FftCheck, path: str) -> str:
    """A check's page, through its character's eyes when it names one (View as for its player, View as's own rule:
    never yourself, never a player you're the DM of; refused, it opens as you, with why)."""
    from app.models import Character, User

    target = None
    if c.as_character:
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
        request.session["view_as_back"] = BACK
        request.session["view_as_testing"] = True
    else:
        leave(request, "")
    return path


def leave(request: Request, back: str) -> str:
    """Back to your own view: a View as Testing turned on ends; one started from Accounts stays."""
    if request.session.pop("view_as_testing", None):
        request.session.pop("view_as", None)
    return back


@router.post("/manage/testing/round")
def round_start(request: Request, area: int = Form(0), db: Session = Depends(get_db)):
    """▶ Start round (or ▶ Just this area): the checks that are yours on this device, in For you's order."""
    user, denied = _admin(request)
    if denied:
        return denied
    device = device_of(request)
    groups = for_you(db, device)
    ids = [int(r["key"][1:]) for g in groups if not area or g["area_id"] == area for r in g["rows"] if r["kind"] == "check" and r.get("here")]
    if not ids:
        request.session["toast"] = web.notice("Nothing to try on this device right now.", "info")
        return RedirectResponse(BACK, status_code=303)
    me = views.person(db, user)
    try:
        r = rules.open_round(db, f"user:{me['id']}", me["id"], area or None)
    except rules.RuleError as e:
        raise HTTPException(409, e.words) from e
    here = access.current_campaign(me["email"])
    request.session[ROUND] = {"id": r.id, "checks": ids, "i": 0, "device": device, "home": here["id"] if here else None}
    to = _next_page(db, request)
    db.commit()
    return RedirectResponse(to, status_code=303)


@router.post("/manage/testing/checks/{check_id:int}/go")
def go(request: Request, check_id: int, db: Session = Depends(get_db)):
    """▶ Try it: a round of one, on the check's page with its card."""
    user, denied = _admin(request)
    if denied:
        return denied
    c = db.get(FftCheck, check_id) or _missing()
    me = views.person(db, user)
    try:
        r = rules.round_open(db) or rules.open_round(db, f"user:{me['id']}", me["id"], c.area_id)
    except rules.RuleError as e:
        raise HTTPException(409, e.words) from e
    here = access.current_campaign(me["email"])
    request.session[ROUND] = {"id": r.id, "checks": [c.id], "i": 0, "device": device_of(request), "home": here["id"] if here else None, "one": True}
    to = enter(request, db, c, page_of(db, c))
    db.commit()
    return RedirectResponse(to, status_code=303)


@router.post("/manage/testing/round/end")
def round_end(request: Request, db: Session = Depends(get_db)):
    _, denied = _admin(request)
    if denied:
        return denied
    to = _end(request, db)
    db.commit()
    request.session["toast"] = "Round ended: Claude may merge again"
    return RedirectResponse(to, status_code=303)


@router.post("/manage/testing/round/next")
def round_next(request: Request, db: Session = Depends(get_db)):
    """Next check → after a fail (its issues sent)."""
    _, denied = _admin(request)
    if denied:
        return denied
    r = _round(request)
    if r is not None:
        r["i"] += 1
        request.session[ROUND] = r
    to = _next_page(db, request)
    db.commit()
    return RedirectResponse(to, status_code=303)


def _record(request: Request, db: Session, c: FftCheck, **kw) -> FftTry:
    user = request.session.get("real_user") or request.session.get("user")
    me = views.person(db, user)
    r = _round(request)
    device = r["device"] if r else device_of(request)
    seen = kw.pop("seen", None)
    try:
        return rules.record_try(db, f"user:{me['id']}", c, device=device, where=where_of(request), app_version=app_version(),
                                user_id=me["id"], round_id=r["id"] if r else None, seen={device: seen} if seen else None, **kw)
    except rules.RuleError as e:
        raise HTTPException(409 if e.code == "stale" else 400, e.words) from e


def _on_round(request: Request, c: FftCheck) -> bool:
    r = _round(request)
    return bool(r and r["i"] < len(r["checks"]) and r["checks"][r["i"]] == c.id)


@router.post("/manage/testing/checks/{check_id:int}/try")
def tried(request: Request, check_id: int, result: str = Form(...), cant: str = Form(""), blocked_by: int = Form(0), why: str = Form(""),
          seen: str = Form(""), db: Session = Depends(get_db)):
    """✓ Passed, or Can't try… (later, blocked by an issue, the check is wrong). In a round it moves on, with Undo in
    the corner card (a pass undone goes back to To try)."""
    _, denied = _admin(request)
    if denied:
        return denied
    c = db.get(FftCheck, check_id) or _missing()
    if result not in ("passed", "cant"):
        raise HTTPException(400)
    t = _record(request, db, c, result=result, cant_kind=cant, blocked_by=blocked_by or None, why=why.strip()[:1000], seen=seen or None)
    on_round = _on_round(request, c)
    if on_round:
        r = _round(request)
        r["i"] += 1
        request.session[ROUND] = r
    to = _next_page(db, request) if on_round else f"{BACK}?open=c{c.id}"
    db.commit()
    said = f"Passed: {c.title}" if result == "passed" else {"later": "Later: it stays yours", "blocked": "Blocked: it comes back when that's fixed",
                                                             "wrong": "Sent to Claude to rewrite"}.get(cant, "Saved")
    request.session["toast"] = {"text": said, "kind": "ok", "undo": f"/manage/testing/tries/{t.id}/undo"}
    return RedirectResponse(to, status_code=303)


@router.post("/manage/testing/tries/{try_id:int}/undo")
def undo(request: Request, try_id: int, db: Session = Depends(get_db)):
    """Undo from the corner card: the try is corrected back to To try (R6), and a round goes back to it."""
    user, denied = _admin(request)
    if denied:
        return denied
    t = db.get(FftTry, try_id) or _missing()
    me = views.person(db, user)
    try:
        rules.correct_try(db, f"user:{me['id']}", t, "untried", "Undone", user_id=me["id"])
    except rules.RuleError as e:
        raise HTTPException(409, e.words) from e
    c = db.get(FftCheck, t.check_id)
    r = _round(request)
    if r and c.id in r["checks"]:
        r["i"] = r["checks"].index(c.id)
        request.session[ROUND] = r
    db.commit()
    request.session["toast"] = "Undone: it's to try again"
    return RedirectResponse(page_of(db, c) if r else f"{BACK}?open=c{c.id}", status_code=303)


# ------------------------------------------------------------------ Something's wrong… (screen 3)


@router.get("/manage/testing/checks/{check_id:int}/wrong")
def wrong_form(request: Request, check_id: int, db: Session = Depends(get_db)):
    """What the window asks first: the issues this check found before that are fixed since (still happening?)."""
    _, denied = _admin(request)
    if denied:
        return denied
    c = db.get(FftCheck, check_id) or _missing()
    device = (_round(request) or {}).get("device") or device_of(request)
    issues = [i for i in rules._blocking_issues(db, c) if i.state in ("ready", "closed", "merge_ok")]
    last = _last_failed(db, c, device)
    return JSONResponse({"title": c.title, "device": DEVICE_SAID.get(device, device), "version": c.version, "app_version": app_version(),
                         "where": where_of(request), "issues": [{"id": i.id, "title": i.title, "said": "fixed, not confirmed" if i.state != "closed" else "closed: works now"} for i in issues],
                         "try": last.id if last else None}, headers={"Cache-Control": "no-store"})


@router.post("/manage/testing/checks/{check_id:int}/wrong")
def wrong(request: Request, check_id: int, body=web.JsonBody, db: Session = Depends(get_db)):
    """Something's wrong… sent: an issue (still happening, or new) with the words and pictures as the tester's note on
    it. One that stops the check fails this try (the first does; ✗ Another… adds to the same try); one that doesn't is
    sent on its own and the check stays to try. "It stops my round" lets Claude fix it now (R11)."""
    user, denied = _admin(request)
    if denied:
        return denied
    c = db.get(FftCheck, check_id) or _missing()
    body = body if isinstance(body, dict) else {}
    text = str(body.get("text") or "").strip()[:sending.MAX_TEXT]
    if not text:
        raise HTTPException(400, "Say what's wrong.")
    if type(body.get("blocking")) is not bool:
        raise HTTPException(400, "Does it stop this check passing?")
    blocking, stops = body["blocking"], body.get("stops_round") is True
    issue_id = body.get("issue") if type(body.get("issue")) is int else None
    if issue_id is not None and issue_id not in [i.id for i in rules._blocking_issues(db, c)]:
        raise HTTPException(400, "That isn't one of this check's issues.")
    pics = sending._pictures(body)
    me = views.person(db, request.session.get("real_user") or user)
    actor = f"user:{me['id']}"
    found = rules.Found(issue_id=issue_id, title=views.title_of(text, 120), blocking=blocking, stops_round=stops and blocking)
    t = None
    try:
        prior = db.get(FftTry, body["try"]) if type(body.get("try")) is int else None
        if prior is not None and prior.check_id == c.id and prior.result == "failed" and not prior.replaced:
            t = prior
            issue = rules.add_found(db, actor, t, found)
        elif blocking:
            t = _record(request, db, c, result="failed", found=[found])
            issue = db.get(FftIssue, db.scalar(select(FftTryIssue.issue_id).where(FftTryIssue.try_id == t.id).order_by(FftTryIssue.issue_id.desc())))
        elif issue_id:  # (still happening, but it doesn't stop this check: Claude's again, the check stays to try)
            issue = db.get(FftIssue, issue_id)
            rules.still_happening(db, actor, issue, c)
        else:
            issue = rules.new_issue(db, actor, found.title, area_id=c.area_id)
        context = body.get("context") if isinstance(body.get("context"), dict) else {}
        note = rules.note_on_issue(db, actor, issue, user_id=me["id"], first_name=me["first_name"], text=text, url=str(body.get("url") or ""),
                                   page=str(context.get("page") or ""), context=context | {"check": c.id, "blocking": blocking},
                                   html=str(body.get("html") or "")[:sending.MAX_HTML], try_id=t.id if t else None)
    except rules.RuleError as e:
        raise HTTPException(409 if e.code == "stale" else 400, e.words) from e
    sending.keep_pictures(db, pics, note_id=note.id)
    db.commit()
    return JSONResponse({"ok": True, "try": t.id if t else None, "issue": issue.id, "failed": bool(t),
                         "said": ("Failed: sent to Claude" if t and not prior else "Added to this try" if t else "Sent on its own: the check stays to try")})


# ------------------------------------------------------------------ windows: Can't try…, Change result…


@router.get("/manage/testing/checks/{check_id:int}/cant")
def cant_window(request: Request, check_id: int, db: Session = Depends(get_db)):
    _, denied = _admin(request)
    if denied:
        return denied
    c = db.get(FftCheck, check_id) or _missing()
    open_issues = list(db.scalars(select(FftIssue).where(FftIssue.state.in_(("to_fix", "fixing", "asks", "merge_ok"))).order_by(FftIssue.id.desc()).limit(50)))
    return templates.TemplateResponse(request, "_fft_cant.html", {"c": c, "issues": open_issues})


@router.get("/manage/testing/tries/{try_id:int}/change")
def change_window(request: Request, try_id: int, db: Session = Depends(get_db)):
    _, denied = _admin(request)
    if denied:
        return denied
    t = db.get(FftTry, try_id) or _missing()
    effects = []
    for ti in db.scalars(select(FftTryIssue).where(FftTryIssue.try_id == t.id)):
        i = db.get(FftIssue, ti.issue_id)
        if ti.how == "new":
            effects.append(f"“{i.title}”: this try found it; unless a note or a fix uses it elsewhere, it closes as withdrawn (still findable).")
        else:
            effects.append(f"“{i.title}”: this try said it was still happening, so it goes back to fixed and ready to try.")
    return templates.TemplateResponse(request, "_fft_change.html", {"t": t, "c": db.get(FftCheck, t.check_id), "effects": effects,
                                                                     "n": len(effects), "device_said": DEVICE_SAID})


@router.post("/manage/testing/tries/{try_id:int}/change")
def change(request: Request, try_id: int, result: str = Form(...), why: str = Form(""), db: Session = Depends(get_db)):
    """Change result…: a correction, never a deletion (R6)."""
    user, denied = _admin(request)
    if denied:
        return denied
    t = db.get(FftTry, try_id) or _missing()
    me = views.person(db, user)
    try:
        rules.correct_try(db, f"user:{me['id']}", t, result, why, user_id=me["id"])
    except rules.RuleError as e:
        raise HTTPException(409 if e.code == "stale" else 400, e.words) from e
    db.commit()
    request.session["toast"] = "Corrected: the history keeps both"
    c = db.get(FftCheck, t.check_id)
    return RedirectResponse(page_of(db, c) if _on_round(request, c) else f"{BACK}?open=c{c.id}", status_code=303)


# ------------------------------------------------------------------ questions and decisions (screen 8)


@router.post("/manage/testing/questions/{question_id:int}")
def answer(request: Request, question_id: int, choice: str = Form(""), text: str = Form(""), db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    q = db.get(FftQuestion, question_id) or _missing()
    me = views.person(db, user)
    picked = int(choice) if choice.isdigit() else None
    try:
        rules.answer(db, f"user:{me['id']}", q, choice=picked, text=text, user_id=me["id"])
    except rules.RuleError as e:
        if e.code == "bad":
            request.session["toast"] = web.notice(e.words, "warn")
            return RedirectResponse(f"{BACK}?open=q{q.id}", status_code=303)
        raise HTTPException(409, e.words) from e
    db.commit()
    request.session["toast"] = "Answered: Claude reads it"
    return RedirectResponse(BACK, status_code=303)


# ------------------------------------------------------------------ the card (on every page while a round is open)


@router.get("/manage/testing/card")
def card(request: Request, at: str = "", db: Session = Depends(get_db)):
    _, denied = _admin(request)
    if denied:
        return denied
    r = _round(request)
    if r is None or r["i"] >= len(r["checks"]):
        return templates.TemplateResponse(request, "_fft_card_empty.html", {})
    c = db.get(FftCheck, r["checks"][r["i"]])
    if c is None:
        return templates.TemplateResponse(request, "_fft_card_empty.html", {})
    if at.startswith(BACK) and not (version_of(db, c) and version_of(db, c).path.startswith(BACK)):
        return templates.TemplateResponse(request, "_fft_card_empty.html", {})  # (on Testing itself, only a check about Testing)
    cv = check_view(db, c, r["device"])
    last = _last_failed(db, c, r["device"])
    sent = len(list(db.scalars(select(FftTryIssue.issue_id).where(FftTryIssue.try_id == last.id)))) if last else 0
    return templates.TemplateResponse(request, "_fft_card.html", {**cv, "n": r["i"] + 1, "of": len(r["checks"]), "device_said": DEVICE_SAID,
                                                                   "device": r["device"], "failed": last, "sent": sent, **card_prefs(request)})


def card_prefs(request: Request) -> dict:
    """How the card was left on this device (folded, and the corner its top bar was dragged to; left by default)."""
    raw = request.cookies.get("askdnd-cc", "")
    corner = raw.rsplit(".", 1)[-1]
    return {"folded": raw.startswith("folded."), "corner": corner if corner in ("tl", "tr", "bl", "br") else "bl"}


templates.env.globals["fft_round"] = lambda request: bool(request.session.get(ROUND))
