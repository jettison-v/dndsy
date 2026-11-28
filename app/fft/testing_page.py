"""Backstage › Global › For you, and trying checks (screens 1–8 of docs/mockups/found-fixed-tried/): everything that's Brett's turn, and
trying what Claude built.

- **For you** (its own page, `/manage/for-you`, since Nov 19, the work flow's slice 2; its count on Backstage):
  everything that's Brett's turn, grouped by what he does with it: Try (checks on the device he's on or another he must
  use, a group per area in the one order), Decide (Claude's questions and decisions), Look at (fixes waiting for his OK
  to merge, fixes live with no check), From the table (notes to approve, ideas to place), From the Roadmap (steps that
  are his). One pill on each: Yours. Where it stands, Claude's and Done are Work's (app/fft/work_page.py).
- **A check**: the walkthrough the card will show, what he should see, why it's there (what was found, what changed),
  ▶ Try it, ✓ Passed, ✗ Something's wrong…, Can't try…; its history (every try, version and fix).
- **A round** (▶ Start round): the checks for this device page by page with the card (left by default, draggable,
  folds; keys P, F, C). Passed moves on with Undo in the corner card; Something's wrong… fails the try with its first
  issue, and the card offers ✗ Another…, Change result… and Next check →. While a round is open nothing merges (R11).

Every change goes through app/fft/rules.py."""

from datetime import datetime, timedelta
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, web
from app.db import get_db
from app.fft import host, rules, sending, steps, views
from app.fft.host import is_admin
from app.fft.models import (
    FftArea,
    FftCheck,
    FftCheckIssue,
    FftCheckVersion,
    FftDocComment,
    FftEvent,
    FftIdea,
    FftIssue,
    FftItem,
    FftLine,
    FftLocalTry,
    FftNote,
    FftQuestion,
    FftTry,
    FftTryIssue,
)
from app.templating import templates

router = APIRouter()
BACK = "/manage/testing"
WORK = "/manage/work"  # (Testing's Where it stands, Claude's and Done, since The Work Pages, Nov 20: app/fft/work_page.py)
FOR_YOU = "/manage/for-you"  # (Brett, Nov 19: For you left Testing for a page of its own; the work flow's slice 2)
LOCAL = "http://localhost:8004"  # (Claude's local server on Brett's Mac: preview "web-claude"; a local try opens there)
ROUND = "fft_round"  # the session's open round: {"id", "checks", "i", "device", "home"}
PEOPLES = ("laptop", "iphone", "ipad")  # (Brett's devices; the Mac Mini's runs are Claude's)
# What a check needs, For you's groups in Try (Clearer checks, Brett's pick 3: a group per need, each its own round): a
# device of his, or more than one person (`FftCheck.people`, tried on the laptop with someone else)
NEEDS = (("laptop", "On your laptop"), ("iphone", "On your iPhone"), ("ipad", "On your iPad"), ("people", "With more than one person"))
NEED_DEVICE = {"laptop": "laptop", "iphone": "iphone", "ipad": "ipad", "people": "laptop"}


def needs_of(c: FftCheck, mine: list[str]) -> list[str]:
    """The groups a check of Brett's is in: more than one person, or each device it's still to try on."""
    return ["people"] if c.people else (mine or ["laptop"])
DEVICE_SAID = {"laptop": "your laptop", "iphone": "your iPhone", "ipad": "your iPad", "mac_mini": "the Mac Mini"}
# The same device in the other ways a sentence needs it, each written whole (issue 146: they were cut from DEVICE_SAID
# with replace(), so a translation would have broken them): "on your laptop", and the bare name
DEVICE_ON = {"laptop": "on your laptop", "iphone": "on your iPhone", "ipad": "on your iPad", "mac_mini": "on the Mac Mini"}
DEVICE_NAME = {"laptop": "laptop", "iphone": "iPhone", "ipad": "iPad", "mac_mini": "Mac Mini"}
DEVICE_LABEL = {"laptop": "Laptop", "iphone": "iPhone", "ipad": "iPad", "mac_mini": "Mac Mini"}  # (a label's own capital: capitalize made "Iphone")
templates.env.globals.update(device_on=DEVICE_ON, device_name=DEVICE_NAME, device_label=DEVICE_LABEL)  # (every page with a check says it the same way)


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
    return rules.check_version(db, c)


def page_of(db: Session, c: FftCheck) -> str:
    v = version_of(db, c)
    return v.path if v is not None and steps.local_path(v.path) else f"{FOR_YOU}?open=c{c.id}"


def check_view(db: Session, c: FftCheck, device: str = "laptop") -> dict:
    v = version_of(db, c)
    st = rules.check_state(db, c)
    mine = [d for d in (c.devices or ["laptop"]) if d in PEOPLES and st["devices"].get(d) in ("to_try", "later")]
    word = views.check_word(st)
    issues = rules.check_issues(db, c)
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
            "blocked": "Blocked by another issue; it comes back when that's fixed.", "preflight": "Claude tries it first, then it's yours.", "deploying": "Its change isn't live yet; it comes to you once its deploy is.",
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
        line = f"{what} by {who} · {DEVICE_NAME.get(t.device, t.device)} · v{t.version}" + (f" · {n} issue{'s' if n != 1 else ''}" if n else "") \
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


# For you's three tables, quick ones first (issue 111, Brett's picks on docs/mockups/for-you-tables/, Nov 24): Decide (one
# read and one press), From the Roadmap (in his order), then Try (the long one, its rounds)
SECTIONS = (("decide", "Decide"), ("roadmap", "From the Roadmap"), ("try", "Try"))
SECTION_ORDER = {k: n for n, (k, _) in enumerate(SECTIONS)}
SECTION_OF = {"local": "try", "check": "try", "question": "decide", "decision": "decide", "merge": "decide", "note": "decide", "idea": "decide", "ask": "decide",
              "roadmap": "roadmap", "scope": "roadmap"}
# What each row asks of him, as one action word (his comments on the mockup: action words, fewer of them, Approve for
# what's sent for his yes, a local try named for what it is), with its tone
ACT = {"local": ("Try locally", "ask"), "check": ("Try", "ask"), "question": ("Answer", "claude"), "decision": ("Answer", "claude"),
       "merge": ("Approve", "passed"), "note": ("Approve", "passed"), "idea": ("Approve", "passed"), "ask": ("Send", "passed"), "scope": ("Approve", "passed"), "roadmap": ("Do", "quiet")}
NUMBER = {"c": "check", "q": "question", "i": "issue", "n": "note", "d": "idea", "r": "item", "l": "local try"}  # (the numbers Claude writes)


NEED_ORDER = {k: n for n, (k, _) in enumerate(NEEDS)}


def for_you(db: Session, device: str) -> list[dict]:
    """Groups of rows by what Brett does with them (the Work Flow Map's For you, Nov 19): Try (checks, a group per area
    in the one order), Decide (Claude's questions and decisions), Look at (fixes to OK, fixes live with no check), From
    the table (notes to approve, ideas to place), From the Roadmap (steps that are his). Within each, the one order.
    Each group: key, title, section, rows, area_id, checks; each row: key, title, sub, kind."""
    groups: dict = {}
    order: list = []

    def put(gkey, gtitle, row, area_id=None):
        row = row | {"no": f"{NUMBER[row['key'][:1]]} {row['key'][1:]}"}
        if gkey not in groups:
            groups[gkey] = {"key": gkey, "title": gtitle, "section": SECTION_OF[row["kind"]], "rows": [], "area_id": area_id, "checks": 0}
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
        v = cv["v"]
        goal = f"Now: {v.now}" if v is not None and v.now else cv["word"]  # (its goal on the row: what it's for, Brett's picks Nov 21)
        for need in needs_of(c, cv["mine"]):
            rows.append(((NEED_ORDER[need], *area_key(c.area_id)), c.area_id, {"key": f"c{c.id}", "title": c.title, "kind": "check", "need": need,
                                                                               "here": NEED_DEVICE[need] == device, "sub": goal, "minutes": c.minutes}))
    for q in db.scalars(select(FftQuestion).where(FftQuestion.answered_at.is_(None)).order_by(FftQuestion.id)):
        aid = None
        if q.about == "issue" and q.about_id and (i := db.get(FftIssue, q.about_id)):
            aid = i.area_id
        elif q.about == "check" and q.about_id and (c := db.get(FftCheck, q.about_id)):
            aid = c.area_id
        elif q.about == "area":
            aid = q.about_id
        decision = q.about == "document" or bool(q.doc_path)  # (a mockup to look at first, whatever it's about)
        rows.append((area_key(aid), aid, {"key": f"q{q.id}", "title": views.title_of(q.text), "kind": "decision" if decision else "question",
                                          "sub": "A decision: look, then one verdict" if decision else "Claude asks",
                                          # (its choices, answered in place on a phone: Roadmap item 49, Brett's pick N2)
                                          "choices": [] if decision else list(enumerate(q.choices or [])), "mine": q.mine, "qid": q.id}))
    for i in db.scalars(select(FftIssue).where(FftIssue.state == "merge_ok").order_by(FftIssue.id)):
        rows.append((area_key(i.area_id), i.area_id, {"key": f"i{i.id}", "title": i.title, "kind": "merge", "sub": "Fix ready: your OK to merge (players asked)"}))
    # (a fix live with no check isn't his to look at: it's Claude's gap until its check is written, issue 111)
    for lt in db.scalars(select(FftLocalTry).where(FftLocalTry.answer == "").order_by(FftLocalTry.id)):  # (while he's Available)
        rows.append((area_key(lt.area_id), lt.area_id, {"key": f"l{lt.id}", "title": lt.title, "kind": "local", "sub": "Ready on your computer, before it merges"}))
    for _, aid, row in sorted(rows, key=lambda r: (SECTION_ORDER[SECTION_OF[r[2]["kind"]]], r[0] if r[2]["kind"] == "check" else (0, *r[0]))):
        a = areas.get(aid) if aid else None
        if row["kind"] == "check":  # (a group per need, then per area: ▶ Start round and ▶ Just this area)
            put(f"{row['need']}:a{aid or 0}", a.title if a else "In no area yet", row, aid)
            groups[f"{row['need']}:a{aid or 0}"]["need"] = row["need"]
        elif row["kind"] == "local":  # (Try's first group: on his computer, before it merges)
            put("local", "On your computer · before it merges", row | {"sub": f"{a.title} · {row['sub']}" if a else row["sub"]})
        else:  # (one group each, the area in its From column)
            put(SECTION_OF[row["kind"]], dict(SECTIONS)[SECTION_OF[row["kind"]]], row | {"from": a.title if a else ""})
    for n in db.scalars(select(FftNote).where(FftNote.state == "waiting").order_by(FftNote.id)):  # (from the table: a yes or no, in Decide)
        put("decide", "Decide", {"key": f"n{n.id}", "title": views.title_of(n.text), "kind": "note", "sub": f"{n.first_name}'s note: your yes sends it to Claude", "from": "The table"})
    for line in db.scalars(select(FftLine).where(FftLine.who == "claude", FftLine.to == "sender", FftLine.approved.is_(False),
                                                FftLine.note_id.isnot(None)).order_by(FftLine.id)):  # (ask back: R10's slice 5)
        n = db.get(FftNote, line.note_id)
        put("decide", "Decide", {"key": f"n{n.id}", "title": views.title_of(n.text), "kind": "ask", "sub": f"Claude's question for {n.first_name}: send it?", "from": "The table"})
    for d in db.scalars(select(FftIdea).where(FftIdea.state == "new").order_by(FftIdea.id)):
        who = db.scalar(select(FftNote.first_name).where(FftNote.idea_id == d.id))
        put("decide", "Decide", {"key": f"d{d.id}", "title": d.title, "kind": "idea", "sub": f"{who}'s idea: place it" if who else "An idea to place", "from": "The table"})
    for it in db.scalars(select(FftItem).where(FftItem.standing.is_(False), FftItem.section.in_(rules.ROADMAP_SECTIONS))
                         .order_by(rules.item_rank(), FftItem.place, FftItem.id)):  # (a scope waiting for his OK, or a step of his: Nov 20)
        sc = rules.latest_scope(db, it)
        if rules.waits_on_brett(sc):
            put("roadmap", "From the Roadmap", {"key": f"r{it.id}", "title": it.title, "kind": "scope", "sub": f"Scope version {sc.version} waits for your OK",
                                                "from": it.section.capitalize()})
        elif it.next_whose == "brett":
            put("roadmap", "From the Roadmap", {"key": f"r{it.id}", "title": it.title, "kind": "roadmap", "sub": it.next_step or "Its next step is yours",
                                                "from": it.section.capitalize()})
    return sorted((groups[k] for k in order), key=lambda g: SECTION_ORDER[g["section"]])  # (in the page's order: ↑ ↓ follow it)


def summary(groups: list[dict]) -> dict:
    every = [r for g in groups for r in g["rows"]]
    rows = list({r["key"]: r for r in every}.values())  # (a check to try on two devices is one check, in two groups)
    count = lambda kind: sum(1 for r in rows if r["kind"] == kind)
    checks = [r for r in rows if r["kind"] == "check"]
    act = lambda *kinds: sum(count(k) for k in kinds)
    bits = [(act("question", "decision"), "to answer", ""), (act("merge", "note", "idea", "scope"), "to approve", ""), (count("roadmap"), "to do", ""),
            (count("ask"), "to send", ""), (count("local"), "to try locally", ""), (len(checks), "to try", f" (about {sum(r['minutes'] for r in checks)} minutes)" if checks else "")]
    return {"n": len(rows), "line": " · ".join(f"{n} {words}{extra}" for n, words, extra in bits if n)}


# ------------------------------------------------------------------ the page


@router.get("/manage/testing")
def page(request: Request, show: str = "", open: str = "", db: Session = Depends(get_db)):
    """Testing's old address: Where it stands, Claude's and Done are Work's now; For you has a page of its own."""
    user, denied = _admin(request)
    if denied:
        return denied
    if show == "foryou" or (not show and open):  # (For you's rows were /manage/testing?open=…: links in notes, toasts, bookmarks)
        keep = {k: v for k, v in (("open", _key(open)), ("device", request.query_params.get("device", ""))) if v}
        return RedirectResponse(FOR_YOU + ("?" + urlencode(keep) if keep else ""), status_code=303)
    from app.fft import work_page  # (Testing became Work, The Work Pages, Nov 20: its old addresses go there)

    return work_page.forward(show, _key(open))


@router.get("/manage/for-you")
def for_you_page(request: Request, open: str = "", db: Session = Depends(get_db)):
    """Backstage › Global › For you: everything that's Brett's turn, by what he does with it (the work flow's slice 2)."""
    user, denied = _admin(request)
    if denied:
        return denied
    return _render(request, db, user, "foryou", open)


@router.get("/manage/for-you/count")
def for_you_count(request: Request, seen: int = 0, db: Session = Depends(get_db)):
    """For you's count, for Backstage's badge on every page an admin opens (fetched after the page shows, and again
    on a live change). Only reads: R5's due confirmations are moved by the pages that show them (For you, Testing,
    Feedback), so a background fetch never writes or announces a change of its own."""
    user, denied = _admin(request)
    if denied:
        return denied
    if seen:  # (a page of his just showed: Available's "quiet for 30 minutes" reads it; at most a write a minute)
        row = views.person(db, user)["row"]
        if row is not None and (row.last_seen_at is None or rules.now() - row.last_seen_at > timedelta(minutes=1)):
            row.last_seen_at = rules.now()
            db.commit()
    return JSONResponse({"n": summary(for_you(db, device_of(request)))["n"]}, headers={"Cache-Control": "no-store"})


def _key(open: str) -> str:
    return open if open[:1] in ("c", "q", "i", "n", "d", "r", "l") and open[1:].isdigit() else ""


def status(db: Session) -> dict:
    """The status bar on For you and Work (_fft_status.html): Available, Claude listening, an open round,
    the game-night freeze. Available turns itself off here when one of its signals says so."""
    li = db.scalars(select(rules.FftListener).order_by(rules.FftListener.heard_at.desc().nulls_last())).first()
    av = rules.check_available(db)
    av["ended"] = bool(av["why"] and av["off_at"] and rules.now() - datetime.fromisoformat(av["off_at"]) < timedelta(hours=2))  # (said for a while)
    r = rules.round_open(db)
    area = db.get(FftArea, r.area_id) if r is not None and r.area_id else None
    after = rules.after_state(db)
    hands = views.hands(db)  # (what's in Claude's hands: the bar's quiet line, Development's amber panel for the late ones)
    from app.fft import handoffs

    missed = handoffs.missed(db)  # (a handoff past its usual time: Brett's pick CQ4, beside what's in Claude's hands)
    return {"available": av, "listening": views.listening(db), "listener": li, "round": r, "hands": hands, "late": [g for g in hands if g["late"]],
            "missed": missed,
            "gap_words": views.GAP_WORDS,
            "after": after, "flight": rules.in_flight(db),  # (a round waiting for changes to go live; what pausing would hold)
            "round_area": area.title if area else "",  # (what the round holds: its own area, a lighter round, Nov 19)
            "freeze": rules.freeze_state(db), "mode": rules.mode_of(db),
            "usage": usage_bar(db),
            "updated": config.STARTED_AT.isoformat()}  # (askdnd.ai's last deploy: a pause has settled once nothing newer comes)


def usage_bar(db: Session) -> dict:
    """The Usage pill beside Deploys (Roadmap item 34): the last reading, its verdict now (against Brett's limits as they
    stand, so a change of limit shows at once), the week's limit, and the limits for its menu. `tone`: ok, near (within
    10% of the limit), over (stopped), wait (the 5-hour window), old (no reading in the last 30 minutes)."""
    limits, r = rules.usage_limits(db), rules.last_usage(db)
    if r is None:
        return {"limits": limits, "reading": None, "tone": "old", "why": "No reading yet", "cap": limits["week"], "days": rules.DAYS}
    verdict, why, cap = rules.usage_verdict(limits, r.five_hour, r.week, r.extra_spent, r.five_resets_at, r.week_resets_at)
    old = rules.now() - r.created_at > rules.USAGE_FRESH
    if verdict == "wait" and r.five_resets_at and rules.now() >= r.five_resets_at:  # (the window has reset since: not paused now)
        verdict, why = "go", "The 5-hour window has reset: Claude reads its usage again before going on."
    tone = {"stop": "over", "wait": "wait"}.get(verdict) or ("near" if cap - r.week <= 10 else "old" if old else "ok")
    return {"limits": limits, "reading": r, "verdict": verdict, "why": why, "cap": cap, "tone": tone, "old": old, "days": rules.DAYS}


def _render(request: Request, db: Session, user: dict, show: str, open: str):
    rules._expire_rounds(db)
    rules.confirm_due(db)  # (R5: a player's three days to say whether it works are up: it's yours)
    device = device_of(request)
    groups = for_you(db, device)
    pick = _key(open)  # (an old link to one item: it opens in the item window over the list)
    round_checks = [r for g in groups for r in g["rows"] if r["kind"] == "check" and r.get("here")]
    me = views.person(db, user)
    flight = rules.in_flight(db)  # (the heads-up before ▶ Start round: a lighter round, item 3)
    whole = rules.round_areas(db)
    db.commit()
    return templates.TemplateResponse(request, "fft_testing.html", {
        "round_flight": any(g["area_ids"] & whole or None in g["area_ids"] for g in flight),
        "flight_areas": set().union(*[g["area_ids"] for g in flight]) if flight else set(),
        "show": show, "sections": SECTIONS, "act": ACT, "groups": groups, "pick": pick, "summary": summary(groups), "from_": show,
        "round_n": len(round_checks), "round_open": request.session.get(ROUND), "device": device, "device_said": DEVICE_SAID, "check_words": views.CHECK_WORD,
        "need_said": dict(NEEDS), "need_device": NEED_DEVICE, "need_counts": need_counts(groups),
        "device_need": device if device in NEED_DEVICE else "", "several_needs": len({g.get("need") for g in groups if g["section"] == "try"}) > 1,
        "try_minutes": sum(r.get("minutes") or 0 for g in groups if g["section"] == "try" for r in g["rows"]),
        "me_id": me["id"], "listening": views.listening(db), "here_path": FOR_YOU, "status": status(db),
        "toast": request.session.pop("toast", None)})


def need_counts(groups: list[dict]) -> dict:
    """Each need's checks and minutes, for its heading in Try."""
    out = {k: {"n": 0, "minutes": 0} for k, _ in NEEDS}
    for g in groups:
        for r in g["rows"]:
            if r["kind"] == "check":
                out[r["need"]]["n"] += 1
                out[r["need"]]["minutes"] += r.get("minutes") or 0
    return out


def listed_keys(db: Session, show: str, device: str) -> list[str]:
    """For you's rows, in their order: the item window's ↑ ↓ follow it."""
    return list(dict.fromkeys(r["key"] for g in for_you(db, device) for r in g["rows"])) if show == "foryou" else []


def _picked(db: Session, pick: str, device: str) -> dict | None:
    kind, ident = pick[:1], int(pick[1:]) if pick[1:].isdigit() else 0
    if kind == "c" and (c := db.get(FftCheck, ident)):
        cv = check_view(db, c, device)
        return {"kind": "check", **cv, "why": why_line(db, c, cv["v"]), "history": history(db, c), "page": page_of(db, c),
                "last_failed": _last_failed(db, c, device)}
    if kind == "q" and (q := db.get(FftQuestion, ident)):
        return {"kind": "question", "q": q, "about": _about(db, q), "doc": views.doc_of(q.doc_path)}
    if kind == "i" and (i := db.get(FftIssue, ident)):
        return {"kind": "issue", "i": i, "sentence": views.issue_sentence(db, i), "pill": views.turn_pill(*views.issue_turn(db, i)),
                "checks": views.issue_checks(db, i)}
    if kind == "n" and (n := db.get(FftNote, ident)):
        return {"kind": "note", "n": n}
    if kind == "d" and (d := db.get(FftIdea, ident)):
        return {"kind": "idea", "d": d}
    if kind == "a" and (a := db.get(FftArea, ident)):  # (a plan in the item window: Brett's pick M1, Nov 24)
        from app.fft import work_page

        return {"kind": "plan", **work_page.plan_view(db, a)}
    if kind == "r" and (it := db.get(FftItem, ident)):
        from app.fft import roadmap_page
        from app.fft.models import FftStep

        return {"kind": "roadmap", "it": it, "scope": rules.latest_scope(db, it), "row": roadmap_page.row(db, it), "pages": roadmap_page.pages(db, it), "page_answers": roadmap_page.page_answers(db, it),
                "mine": list(db.scalars(select(FftStep).where(FftStep.item_id == it.id, FftStep.whose == "brett", FftStep.done_at.is_(None)).order_by(FftStep.place)))}
    if kind == "l" and (lt := db.get(FftLocalTry, ident)):
        return {"kind": "local", "lt": lt, "area": db.get(FftArea, lt.area_id) if lt.area_id else None, "open": LOCAL + "/dev/login?next=" + quote(lt.path, safe="/?=&")}
    return None


def _about(db: Session, q: FftQuestion) -> dict:
    """What a question is about, as a link: an issue on Feedback, a check here, an area, or a document."""
    if q.about == "issue" and q.about_id and (i := db.get(FftIssue, q.about_id)):
        return {"said": f"the issue “{i.title}”", "href": f"/manage/feedback?tab=open&open=i{i.id}", "key": f"i{i.id}"}
    if q.about == "check" and q.about_id and (c := db.get(FftCheck, q.about_id)):
        return {"said": f"the check “{c.title}”", "href": f"{FOR_YOU}?open=c{c.id}", "key": f"c{c.id}"}
    if q.about == "area" and q.about_id and (a := db.get(FftArea, q.about_id)):
        return {"said": f"the {a.title} plan", "href": f"{WORK}/{a.id}", "key": f"a{a.id}"}
    if q.about == "document" and (doc := views.doc_of(q.doc_path)):
        return {"said": doc["title"], "href": doc["href"], "version": q.doc_version}
    return {"said": "", "href": ""}


def _last_failed(db: Session, c: FftCheck, device: str) -> FftTry | None:
    """The try that left this check failed on this device, while it still stands (issue 46, Brett, Nov 20: a check back to
    try once its fix went live opened as ✗ Failed; that failure is history now, and the card opens fresh)."""
    t = db.scalar(select(FftTry).where(FftTry.check_id == c.id, FftTry.device == device, FftTry.actor == "person").order_by(FftTry.id.desc()))
    if t is None or t.result != "failed" or t.replaced:
        return None
    return t if rules.check_state(db, c)["devices"].get(device) == "failed" else None


@router.post("/manage/testing/order")
def order(request: Request, column: str = Form(...), keys: list[str] = Form(default=[]), db: Session = Depends(get_db)):
    """Drag and drop on Work: the items' order, or one item's areas' (Brett's one order, R15)."""
    user, denied = _admin(request)
    if denied:
        return denied
    actor = f"user:{views.person(db, user)['id']}"
    ids = [int(k) for k in keys if k.isdigit()]
    if column == "queue":  # (Development's one queue: batches "a<id>" and builds "i<id>", issue 62)
        rules.order_queue(db, actor, keys)
    elif column == "items":
        rules.order_items(db, actor, ids)
    elif column.startswith("item-") and column[5:].isdigit() and (it := db.get(FftItem, int(column[5:]))):
        rules.order_areas(db, actor, it, ids)
    else:
        raise HTTPException(400)
    db.commit()
    return JSONResponse({"ok": True})


@router.post("/manage/testing/areas/{area_id:int}")
def area_change(request: Request, area_id: int, do: str = Form(...), title: str = Form(""), into: int = Form(0), item: int = Form(0),
                lane: str = Form(""), back: str = Form(""), db: Session = Depends(get_db)):
    """Rename…, Merge into…, Move to another item…, Archive, Hold and Let it go (Work's cut line), and its lane (Ship,
    Look, Careful). The answer is Work (or the plan's page it was pressed on)."""
    user, denied = _admin(request)
    if denied:
        return denied
    home = back if back.startswith(WORK) and "//" not in back else WORK
    a = db.get(FftArea, area_id) or _missing()
    actor = f"user:{views.person(db, user)['id']}"
    try:
        if do == "rename":
            rules.rename_area(db, actor, a, title)
            said = "Renamed"
        elif do == "merge":
            target = db.get(FftArea, into) or _missing()
            rules.merge_area(db, actor, a, target)
            said = f"Merged into {target.title}"
        elif do == "move":
            target = db.get(FftItem, item) or _missing()
            rules.move_area(db, actor, a, target)
            said = f"Moved to {target.title}"
        elif do == "archive":
            rules.archive_area(db, actor, a)
            said = "Archived"
        elif do in ("hold", "unhold"):
            rules.hold_area(db, actor, a, do == "hold")
            said = f"{a.title}: held below the line" if do == "hold" else f"{a.title}: back above the line"
        elif do == "lane":  # (Brett's word: any lane, down too; kept with who)
            rules.set_lane(db, actor, a, lane, "Brett chose it", admin=True)
            said = f"{a.title}: {rules.LANE_SAID[lane]}"
        else:
            raise HTTPException(400)
    except rules.RuleError as e:
        request.session["toast"] = web.notice(e.words, "warn")
        return RedirectResponse(home, status_code=303)
    db.commit()
    request.session["toast"] = said
    return RedirectResponse(home, status_code=303)


@router.post("/manage/for-you/mode")
def mode(request: Request, mode: str = Form(...), back: str = Form(""), here: str = Form(""), why: str = Form(""), db: Session = Depends(get_db)):
    """Deploys (Brett, Nov 19): After my local try, When tests pass, or Paused (with an optional reason)."""
    user, denied = _admin(request)
    if denied:
        return denied
    me = views.person(db, user)
    try:
        rules.set_mode(db, f"user:{me['id']}", mode, by=me["first_name"], why=why)
    except rules.RuleError as e:
        raise HTTPException(400, e.words) from e
    db.commit()
    request.session["toast"] = {"available": f"Deploys after your local try, for {rules.AVAILABLE_HOURS} hours: visible changes wait for your try on your Mac",
                                "independent": "Deploys when tests pass: visible changes go live, and you try them after",
                                "frozen": "Deploys paused" + (f": {why.strip()[:120]}" if why.strip() else "") + ". Nothing deploys until you choose another"}[mode]
    if here.startswith("/manage/") and "//" not in here and "\\" not in here:  # (the page, tab and filters you were on: one of Backstage's own)
        return RedirectResponse(here, status_code=303)
    back_to = {"work": WORK, "stands": WORK, "feedback": "/manage/feedback", "roadmap": "/manage/roadmap"}
    return RedirectResponse(back_to.get(back, FOR_YOU), status_code=303)


@router.post("/manage/for-you/usage")
def usage_limits(request: Request, week: int = Form(...), keep: int = Form(...), game_day: str = Form(""), extra: float = Form(0.0),
                 window: str = Form("pause"), here: str = Form(""), db: Session = Depends(get_db)):
    """Brett's usage limits (Roadmap item 34), from the Usage menu beside Deploys."""
    user, denied = _admin(request)
    if denied:
        return denied
    me = views.person(db, user)
    try:
        rules.set_usage_limits(db, f"user:{me['id']}", week, keep, int(game_day) if game_day.isdigit() else None, extra, window)
    except rules.RuleError as e:
        request.session["toast"] = web.notice(e.words, "warn")
    else:
        db.commit()
        request.session["toast"] = f"Claude stops at {week}% of the week" + (f", {keep}% kept for game night" if keep else "")
    if here.startswith("/manage/") and "//" not in here and "\\" not in here:  # (the page you were on: one of Backstage's own)
        return RedirectResponse(here, status_code=303)
    return RedirectResponse(FOR_YOU, status_code=303)


@router.post("/manage/for-you/local/{try_id:int}")
def local_answer(request: Request, try_id: int, answer: str = Form(...), words: str = Form(""), db: Session = Depends(get_db)):
    """Looks good (Claude merges it) or Something's off… (his words go back to Claude)."""
    user, denied = _admin(request)
    if denied:
        return denied
    lt = db.get(FftLocalTry, try_id) or _missing()
    me = views.person(db, user)
    try:
        rules.answer_local_try(db, f"user:{me['id']}", lt, answer, words)
    except rules.RuleError as e:
        request.session["toast"] = web.notice(e.words, "warn")
        return RedirectResponse(f"{FOR_YOU}?open=l{lt.id}", status_code=303)
    db.commit()
    request.session["toast"] = "Looks good: Claude merges it" if answer == "good" else "Sent to Claude: it goes back to its plan"
    return RedirectResponse(FOR_YOU, status_code=303)


# ------------------------------------------------------------------ trying a check


def _round(request: Request) -> dict | None:
    return request.session.get(ROUND)


def _next_page(db: Session, request: Request) -> str:
    """The round's next check's page, or For you when every check is tried. A round stays open until Brett presses End
    round (his round, Nov 18: he may keep sending notes after the checks). ▶ Try it on one check isn't a round to him: it
    ends with its check (leaving a round it joined as it was)."""
    r = _round(request)
    if r is None:
        return FOR_YOU
    while r["i"] < len(r["checks"]):
        c = db.get(FftCheck, r["checks"][r["i"]])
        if c is not None and check_view(db, c, r["device"])["here"]:
            request.session[ROUND] = r
            return enter(request, db, c, page_of(db, c))
        r["i"] += 1
    request.session[ROUND] = r
    if r.get("one"):
        return _end(request, db)
    _home(request, db, r)  # (the round's card says it stays open, with End round on it: _fft_card_done.html)
    return leave(request, FOR_YOU)


def _end(request: Request, db: Session) -> str:
    r = request.session.pop(ROUND, None)
    if r and r.get("owns", True) and (row := db.get(rules.FftRound, r["id"])) and row.ended_at is None:  # (a round of one never ends the round it joined)
        user = request.session.get("real_user") or request.session.get("user")
        rules.end_round(db, f"user:{views.person(db, user)['id']}" if user else "askdnd", row)
    _home(request, db, r)
    return leave(request, FOR_YOU)


def _home(request: Request, db: Session, r: dict | None) -> None:
    """Back in the campaign the round started in (a check that makes something runs in a test campaign)."""
    was = (r or {}).get("home")
    email = ((request.session.get("user") or {}).get("email") or "").lower()
    here = host.current_campaign(email)
    if was and email and (here is None or here["id"] != was):
        host.remember_campaign(db, email, was)


def enter(request: Request, db: Session, c: FftCheck, path: str) -> str:
    """A check's page, through its character's eyes when it names one (View as for its player, View as's own rule:
    never yourself, never a player you're the DM of; refused, it opens as you, with why)."""
    target = None
    if c.as_character:
        owner = host.character_player(db, c.as_character)
        real = ((request.session.get("user") or {}).get("email") or "").lower()
        if owner is None:
            request.session["toast"] = web.notice("Its character has no player in askdnd, so it opens as you.", "warn")
        elif why := host.view_refusal(real, owner.email):
            request.session["toast"] = web.notice(f"{why} It opens as you.", "warn")
        else:
            target = {"email": owner.email.lower(), "name": (owner.name if owner.name and owner.name != owner.email else None) or owner.email}
    if target:
        request.session["view_as"] = target
        request.session["view_as_back"] = FOR_YOU
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
def round_start(request: Request, area: int = Form(0), need: str = Form(""), db: Session = Depends(get_db)):
    """▶ Start round (or ▶ Just this area): the checks of one need, yours on this device, in For you's order (Clearer
    checks, Brett's pick 3: a round never mixes laptop, phone and more than one person)."""
    user, denied = _admin(request)
    if denied:
        return denied
    need = need if need in NEED_DEVICE else device_of(request)
    # (the need's own device, wherever it's started: he reads the steps on the laptop and taps on the iPhone, and his
    # marks count for the iPhone; issue 104, Nov 23)
    device = NEED_DEVICE[need]
    groups = for_you(db, device)
    ids = list(dict.fromkeys(int(r["key"][1:]) for g in groups if not area or g["area_id"] == area for r in g["rows"]
                             if r["kind"] == "check" and r.get("here") and r.get("need") == need))
    if not ids:
        request.session["toast"] = web.notice("Nothing to try on this device right now.", "info")
        return RedirectResponse(FOR_YOU, status_code=303)
    me = views.person(db, user)
    try:
        r = rules.open_round(db, f"user:{me['id']}", me["id"], area or None)
    except rules.RuleError as e:
        raise HTTPException(409, e.words) from e
    here = host.current_campaign(me["email"])
    request.session[ROUND] = {"id": r.id, "checks": ids, "i": 0, "device": device, "need": need, "home": here["id"] if here else None}
    to = _next_page(db, request)
    db.commit()
    return RedirectResponse(to, status_code=303)


@router.get("/manage/testing/round/heads-up")
def round_heads_up(request: Request, area: int = 0, need: str = "", db: Session = Depends(get_db)):
    """Before ▶ Start round holds a change of Claude's about to go live there (Brett's pick A on
    docs/mockups/round-heads-up/, Nov 19): what would wait, with Let it go live first, Start now, Cancel."""
    _, denied = _admin(request)
    if denied:
        return denied
    flight = rules.in_flight(db, rules.round_areas(db, area or None), whole=not area)
    return templates.TemplateResponse(request, "_round_heads_up.html", {"flight": flight, "area": area, "need": need if need in NEED_DEVICE else ""})


@router.post("/manage/testing/round/after")
def round_after(request: Request, area: int = Form(0), db: Session = Depends(get_db)):
    """Let it go live first: the round opens by itself once what it would hold is live."""
    user, denied = _admin(request)
    if denied:
        return denied
    me = views.person(db, user)
    try:
        flight = rules.wait_for_live(db, f"user:{me['id']}", me["id"], area or None)
    except rules.RuleError as e:
        raise HTTPException(409, e.words) from e
    db.commit()
    request.session["toast"] = web.notice(f"Your round starts when {'it goes' if len(flight) == 1 else 'they go'} live: press ▶ Start round then", "info")
    return RedirectResponse(FOR_YOU, status_code=303)


@router.post("/manage/testing/round/after/cancel")
def round_after_cancel(request: Request, db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    rules.cancel_wait(db, f"user:{views.person(db, user)['id']}")
    db.commit()
    return RedirectResponse(FOR_YOU, status_code=303)


@router.post("/manage/testing/checks/{check_id:int}/go")
def go(request: Request, check_id: int, db: Session = Depends(get_db)):
    """▶ Try it: a round of one, on the check's page with its card. It holds nothing (a lighter round, Brett's pick
    Nov 19: one quick try never stops Claude's merges); a sitting already open stays as it is."""
    user, denied = _admin(request)
    if denied:
        return denied
    c = db.get(FftCheck, check_id) or _missing()
    me = views.person(db, user)
    was = rules.round_open(db)
    try:
        r = rules.open_round(db, f"user:{me['id']}", me["id"], c.area_id, holds=False)
    except rules.RuleError as e:
        raise HTTPException(409, e.words) from e
    here = host.current_campaign(me["email"])
    device = device_of(request)
    mine = check_view(db, c, device)["mine"]  # (a check for another device counts for it: issue 104, Nov 23)
    device = device if device in mine or not mine else mine[0]
    request.session[ROUND] = {"id": r.id, "checks": [c.id], "i": 0, "device": device, "home": here["id"] if here else None,
                              "one": True, "owns": was is None or was.id != r.id}
    to = enter(request, db, c, page_of(db, c))
    db.commit()
    return RedirectResponse(to, status_code=303)


@router.post("/manage/testing/round/end")
def round_end(request: Request, db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    to = _end(request, db)
    if (row := rules.round_open(db)) is not None:  # (the round the bar shows, wherever it was started: issue 106)
        rules.end_round(db, f"user:{views.person(db, request.session.get('real_user') or user)['id']}", row)
    db.commit()
    request.session["toast"] = "Round ended: Claude's work in its area may merge again"
    return RedirectResponse(to, status_code=303)


@router.post("/manage/testing/round/skip")
def round_skip(request: Request, check: int = Form(0), db: Session = Depends(get_db)):
    """Skip for now (issue 171, Brett, Nov 25: "skip to the next one without ending the round; you can come back to it
    at the end, before ending the round"): the check moves to the end of the round's list, still to try, and the next
    one comes up; nothing is recorded on it."""
    _, denied = _admin(request)
    if denied:
        return denied
    r = _round(request)
    if r is not None and r["i"] < len(r["checks"]) - 1 and r["checks"][r["i"]] == check:  # (the one on the card: a stale press skips nothing)
        r["checks"].append(r["checks"].pop(r["i"]))
        r["skipped"] = sorted(set(r.get("skipped", [])) | {check})
        request.session[ROUND] = r
        request.session["toast"] = "Skipped: it comes back at the end of the round, before End round"
    to = _next_page(db, request)
    db.commit()
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
    if blocked_by and db.get(FftIssue, blocked_by) is None:
        raise HTTPException(400, "No such issue.")
    t = _record(request, db, c, result=result, cant_kind=cant, blocked_by=blocked_by or None, why=why.strip()[:1000], seen=seen or None)
    on_round = _on_round(request, c)
    if on_round:
        r = _round(request)
        r["i"] += 1
        request.session[ROUND] = r
    to = _next_page(db, request) if on_round else f"{FOR_YOU}?open=c{c.id}"
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
    c = db.get(FftCheck, t.check_id)
    try:
        rules.correct_try(db, f"user:{me['id']}", t, "untried", "Undone", user_id=me["id"])
    except rules.RuleError as e:
        request.session["toast"] = web.notice(e.words, "warn")
        return RedirectResponse(f"{FOR_YOU}?open=c{c.id}", status_code=303)
    r = _round(request)
    if r and c.id in r["checks"]:
        r["i"] = r["checks"].index(c.id)
        request.session[ROUND] = r
    db.commit()
    request.session["toast"] = "Undone: it's to try again"
    return RedirectResponse(page_of(db, c) if r else f"{FOR_YOU}?open=c{c.id}", status_code=303)


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
    said = [{"id": i.id, "title": i.title, "said": "fixed, not confirmed · still happening" if i.state != "closed" else "closed: works now · still happening"} for i in issues]
    said += [{"id": i.id, "title": i.title, "said": "you sent it from this check · didn't stop it then", "sent": True} for i in _sent_from(db, c)]
    return JSONResponse({"title": c.title, "device": DEVICE_SAID.get(device, device), "version": c.version, "app_version": app_version(),
                         "where": where_of(request), "issues": said, "try": last.id if last else None,
                         "elsewhere": device != device_of(request)}, headers={"Cache-Control": "no-store"})  # (issue 104: its picture is this screen's)


def _sent_from(db: Session, c: FftCheck) -> list[FftIssue]:
    """The open issues sent from this check's version that didn't stop it (issue 16, Brett, Nov 17: "I had already added
    issues … Should I be allowed to skip logging the last issue?"): Something's wrong… offers them, so failing the check
    for one needs no second note."""
    since = db.scalar(select(FftCheckVersion.created_at).where(FftCheckVersion.check_id == c.id, FftCheckVersion.version == c.version))
    named = {i.id for i in rules._blocking_issues(db, c)}
    q = (select(FftIssue).join(FftNote, FftNote.issue_id == FftIssue.id)
         .where(FftNote.context["check"].astext == str(c.id), FftIssue.state.in_(("to_fix", "fixing", "asks")))  # (as text: a context's check may be empty)
         .distinct().order_by(FftIssue.id))
    if since is not None:
        q = q.where(FftNote.created_at >= since)
    return [i for i in db.scalars(q) if i.id not in named]


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
    if type(body.get("blocking")) is not bool:
        raise HTTPException(400, "Does it stop this check passing?")
    blocking, stops = body["blocking"], body.get("stops_round") is True
    issue_id = body.get("issue") if type(body.get("issue")) is int else None
    if issue_id is not None and issue_id not in [i.id for i in rules._blocking_issues(db, c) + _sent_from(db, c)]:
        raise HTTPException(400, "That isn't one of this check's issues.")
    pics = sending._pictures(body)
    if not text and (issue_id is None or pics or not blocking):  # (an issue named again to fail the check needs no words: issue 16)
        raise HTTPException(400, "Say what's wrong.")
    me = views.person(db, request.session.get("real_user") or user)
    actor = f"user:{me['id']}"
    found = rules.Found(issue_id=issue_id, title=views.title_of(text, 120), blocking=blocking, stops_round=stops and blocking)
    stored = sending.store_pictures(db, pics)  # (uploaded before any event is written: T8, the review of PR #417)
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
        note = None if not text else rules.note_on_issue(db, actor, issue, user_id=me["id"], first_name=me["first_name"], text=text, url=str(body.get("url") or ""),
                                   page=str(context.get("page") or ""), context=context | {"check": c.id, "blocking": blocking},
                                   html=sending.safe_html(str(body.get("html") or "")[:sending.MAX_HTML]), try_id=t.id if t else None)
    except rules.RuleError as e:
        raise HTTPException(409 if e.code == "stale" else 400, e.words) from e
    if note is not None:
        sending.attach_pictures(db, stored, note_id=note.id)
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
    return RedirectResponse(page_of(db, c) if _on_round(request, c) else f"{FOR_YOU}?open=c{c.id}", status_code=303)


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
            return RedirectResponse(f"{FOR_YOU}?open=q{q.id}", status_code=303)
        raise HTTPException(409, e.words) from e
    db.commit()
    request.session["toast"] = "Answered: Claude reads it"
    return RedirectResponse(FOR_YOU, status_code=303)


# Picks made on a mockup opened inside askdnd (Brett's round, Nov 18: they could only save on claude.ai, so his were
# lost). The mockup's Save my picks hands them to its askdnd page (app.js "picks from a mockup"), which saves them here as
# the answer to the newest question asking about that mockup; opening it again shows them.


_doc_question = rules.doc_question  # (the one way, shared with picks brought in from claude.ai: item 39, 6 of 6)
_picks_said = rules.picks_said


@router.get("/manage/testing/picks")
def picks_read(request: Request, doc: str = "", db: Session = Depends(get_db)):
    _, denied = _admin(request)
    if denied:
        return denied
    asked = _doc_question(db, doc, open_only=True)
    done = db.scalar(select(FftQuestion).where(FftQuestion.doc_path == doc, func.jsonb_array_length(FftQuestion.picks) > 0).order_by(FftQuestion.answered_at.desc()))
    return {"open": asked is not None, "picks": done.picks if done else [], "notes": rules.answer_notes(done.answer_text) if done else "",  # (his notes alone: never the picks line or the comments)
            "at": done.answered_at.isoformat() if done and done.answered_at else ""}


@router.post("/manage/testing/picks")
def picks_save(request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    body = body if isinstance(body, dict) else {}
    doc, notes = str(body.get("doc", ""))[:300], str(body.get("notes", ""))[:4000].strip()
    raw = body.get("picks") if isinstance(body.get("picks"), list) else []
    picks = [{k: str(p.get(k, ""))[:200] for k in ("name", "value", "label")} for p in raw[:20] if isinstance(p, dict)]
    if not any(p["value"] for p in picks):
        raise HTTPException(400, "Pick something first.")
    q = _doc_question(db, doc, open_only=True)
    if q is None:
        raise HTTPException(409, "There's no open question about this mockup: its picks are already in. Send a note to change one.")
    me = views.person(db, user)
    held = _held_comments(db, doc, me["id"])  # (his comments on the mockup go with his picks: issue 24, Brett's pick 3)
    said = _picks_said(picks) + (f"\n\n{notes}" if notes else "") + _comments_said(held)
    try:
        rules.answer(db, f"user:{me['id']}", q, choice=None, text=said[:8000], user_id=me["id"], picks=picks)
    except rules.RuleError as e:
        raise HTTPException(409 if e.code == "stale" else 400, e.words) from e
    for c in held:
        c.question_id, c.sent_at = q.id, rules.now()
    db.commit()
    return {"ok": True, "at": q.answered_at.isoformat(), "comments": len(held)}


# ------------------------------------------------------------------ comments pinned to a mockup (issue 24)
# Brett's picks, Nov 21 (docs/mockups/mockup-comments/): a pin wherever he clicks on any mockup askdnd opens (its layer,
# app/static/doc-layer.js, added as askdnd serves the page: app/documents.py), the comments in a column beside it, held
# as his until Save my picks, which sends them with his answer to its question (and so into its issue's conversation).


_held_comments = rules.held_comments  # (his own, and those brought in from claude.ai)
_comments_said = rules.comments_said


def _comments_rail(request: Request, db: Session, doc: str, user_id: int | None):
    asked = _doc_question(db, doc, open_only=True)
    rows = list(db.scalars(select(FftDocComment).where(FftDocComment.doc == doc, (FftDocComment.sent_at.is_not(None)) | (FftDocComment.user_id == user_id)
                                                       | (FftDocComment.origin == "claude.ai"))
                           .order_by(FftDocComment.sent_at.is_(None), FftDocComment.n)))
    held = sum(1 for c in rows if c.sent_at is None and c.user_id == user_id)  # (his own waiting: Send now shows while there are any)
    return templates.TemplateResponse(request, "_doc_comments.html", {"doc": doc, "comments": rows, "open": asked is not None, "held": held,
                                                                      "pins": [{"n": c.n, "x": c.x, "y": c.y, "page": c.page, "held": c.sent_at is None, "near": c.near if c.origin == "claude.ai" else ""}
                                                                               for c in rows]})


@router.get("/manage/testing/comments")
def comments_rail(request: Request, doc: str = "", db: Session = Depends(get_db)):
    """The column beside a mockup: its pinned comments, yours held until you save your picks, and those sent with them."""
    user, denied = _admin(request)
    if denied:
        return denied
    return _comments_rail(request, db, doc[:300], views.person(db, user)["id"])


@router.post("/manage/testing/comments")
def comment_add(request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    """A comment pinned where he clicked: only while the mockup's question is open, since it goes with his picks."""
    user, denied = _admin(request)
    if denied:
        return denied
    body = body if isinstance(body, dict) else {}
    doc, words = str(body.get("doc", ""))[:300], str(body.get("words", "")).strip()[:2000]
    if not words:
        raise HTTPException(400, "Write your comment first.")
    if _doc_question(db, doc, open_only=True) is None:
        raise HTTPException(409, "This mockup has no open question: a comment goes with your picks, and they're in.")
    try:
        x, y = min(max(float(body.get("x", 0)), 0.0), 1.0), max(float(body.get("y", 0)), 0.0)
    except (TypeError, ValueError):
        raise HTTPException(400, "Where on the page?") from None
    me = views.person(db, user)
    n = (db.scalar(select(func.max(FftDocComment.n)).where(FftDocComment.doc == doc)) or 0) + 1
    db.add(FftDocComment(doc=doc, page=str(body.get("page", ""))[:300], n=n, x=x, y=min(y, 100000.0), near=str(body.get("near", "")).strip()[:200],
                         words=words, user_id=me["id"]))
    db.commit()
    return _comments_rail(request, db, doc, me["id"])


@router.post("/manage/testing/comments/send")
def comments_send(request: Request, body=web.JsonBody, db: Session = Depends(get_db)):
    """Send now (issue 116): your comments not sent yet go to Claude at once; the question stays open for your picks."""
    user, denied = _admin(request)
    if denied:
        return denied
    body = body if isinstance(body, dict) else {}
    doc = str(body.get("doc", ""))[:300]
    me = views.person(db, user)
    try:
        rules.comments_sent(db, f"user:{me['id']}", doc, me["id"])
    except rules.RuleError as e:
        raise HTTPException(409, e.words) from e
    db.commit()
    return _comments_rail(request, db, doc, me["id"])


@router.post("/manage/testing/comments/{comment_id:int}/drop")
def comment_drop(request: Request, comment_id: int, db: Session = Depends(get_db)):
    """Take back a comment of yours not sent yet."""
    user, denied = _admin(request)
    if denied:
        return denied
    me = views.person(db, user)
    c = db.get(FftDocComment, comment_id)
    if c is None or c.user_id != me["id"] or c.sent_at is not None:
        raise HTTPException(404)
    doc = c.doc
    db.delete(c)
    db.commit()
    return _comments_rail(request, db, doc, me["id"])


# ------------------------------------------------------------------ the card (on every page while a round is open)


@router.get("/manage/testing/card")
def card(request: Request, at: str = "", db: Session = Depends(get_db)):
    """The round's card, on every page while a round is open, Backstage and For you too (issue 130, Brett, Nov 25: kept
    off them unless the check was about them, it vanished each time he came back to For you mid-try). `at` is unused
    now; the page still sends it."""
    _, denied = _admin(request)
    if denied:
        return denied
    r = _round(request)
    if r is not None and ((row := db.get(rules.FftRound, r["id"])) is None or row.ended_at is not None):
        request.session.pop(ROUND, None)  # (ended from the other device's bar: its card goes too; the review of #476)
        r = None
    if r is None:
        return templates.TemplateResponse(request, "_fft_card_empty.html", {})
    if r["i"] >= len(r["checks"]):  # (every check tried: the round stays open until End round)
        return templates.TemplateResponse(request, "_fft_card_done.html", {"of": len(r["checks"]), **card_prefs(request)})
    c = db.get(FftCheck, r["checks"][r["i"]])
    if c is None:
        return templates.TemplateResponse(request, "_fft_card_empty.html", {})
    cv = check_view(db, c, r["device"])
    last = _last_failed(db, c, r["device"])
    sent = len(list(db.scalars(select(FftTryIssue.issue_id).where(FftTryIssue.try_id == last.id)))) if last else 0
    return templates.TemplateResponse(request, "_fft_card.html", {**cv, "n": r["i"] + 1, "of": len(r["checks"]), "device_said": DEVICE_SAID,
                                                                  "can_skip": r["i"] < len(r["checks"]) - 1, "came_back": c.id in r.get("skipped", []),
                                                                   "device": r["device"], "elsewhere": r["device"] != device_of(request),
                                                                   "failed": last, "sent": sent, **card_prefs(request)})


def card_prefs(request: Request) -> dict:
    """How the card was left on this device (folded, and the corner its top bar was dragged to; left by default)."""
    raw = request.cookies.get("askdnd-cc", "")
    corner = raw.rsplit(".", 1)[-1]
    return {"folded": raw.startswith("folded."), "corner": corner if corner in ("tl", "tr", "bl", "br") else "bl"}


templates.env.globals["fft_round"] = lambda request: bool(request.session.get(ROUND))
