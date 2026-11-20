"""Backstage › Global › Work (The Work Pages, Brett's picks Nov 20, docs/mockups/work-pages/; the Work Flow Map's Work,
docs/artifacts/work-flow-map.html): what's being built and what's next.

- **Queue**: every plan (an area: one per Product Area, or a Roadmap build's own) in Brett's one order, a row each: its
  lane, its stage (worked out from what's true, never set by hand), issues fixed, checks passed, and who it waits on.
  Claude takes the plans above the cut line (R15, `rules.pick_next`); Hold puts one below it. Drag to reorder.
- **Done**: plans with nothing open, newest first.
- **Checks**: every check with where it stands on each device: the library. A row opens it in the item window.
- **Scheduled**: jobs that run on their own and their last report (`POST /api/fft/jobs/<key>`; app/data/jobs.json).
- **How we work**: the lanes and the steps every plan takes, drawn from the files the tools follow.
- **A plan's page** (`/manage/work/<id>`): Overview, Issues, Test round (its checks by device), Timeline (its events).

Testing's old addresses forward here (testing_page.page). Every change goes through app/fft/rules.py."""

import json
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import get_db
from app.fft import lanes, rules, taxonomy, testing_page, views
from app.fft.models import FftArea, FftCheck, FftEvent, FftIssue, FftItem, FftQuestion
from app.models import ToolSetting
from app.templating import templates

router = APIRouter()
WORK = "/manage/work"
TABS = (("queue", "Queue"), ("done", "Done"), ("checks", "Checks"), ("scheduled", "Scheduled"), ("how", "How we work"))
PLAN_TABS = (("overview", "Overview"), ("issues", "Issues"), ("round", "Test round"), ("timeline", "Timeline"))
# (the Work Flow Map's stages, worked out from what's true: words and state_word's tone)
STAGES = {"blocker": ("Blocker: Claude's now", "failed"), "held": ("Held", "quiet"), "frozen": ("Held for game night", "quiet"), "round": ("In your round", "ask"),
          "try": ("Live: try it", "ask"), "yours": ("Waiting on you", "ask"), "building": ("Building", "claude"),
          "next": ("Claude's next", "claude"), "waiting": ("Waiting its turn", "quiet"), "done": ("Done", "passed")}
CHECK_TONE = {"to_try": "ask", "later": "ask", "asks": "ask", "failed": "failed", "fixing": "claude", "wrong": "claude",
              "blocked": "claude", "preflight": "claude", "passed": "passed", "retired": "quiet"}
DEVICES = ("laptop", "iphone", "ipad", "mac_mini")
DEVICE_NAME = {"laptop": "Laptop", "iphone": "iPhone", "ipad": "iPad", "mac_mini": "Mac Mini"}
JOBS_FILE = Path(__file__).resolve().parent.parent / "data" / "jobs.json"
JOB_KEY = "fft_job:"  # (a ToolSetting per job: its last report, {"at", "result", "words"})


# ------------------------------------------------------------------ a plan, as a row


def stage(db: Session, a: FftArea, turn: str, pick: rules.Pick, frozen: bool) -> str:
    if a.held:
        return "held"
    if turn == "done":
        return "done"
    if pick.blocker and pick.area is not None and pick.area.id == a.id:  # (an issue in it stops Brett's round: Claude fixes it now)
        return "blocker"
    if rules.in_open_round(db, a):
        return "round"
    if turn == "brett":
        issues = rules.area_open_issues(db, a)
        live = any(i.state == "ready" for i in issues) or any(rules.check_state(db, c)["state"] == "to_try" for c in rules.area_checks(db, a))
        return "try" if live else "yours"
    if frozen:
        return "frozen"
    if (a.lock_owner and a.lock_until and a.lock_until > rules.now()) or any(i.state == "fixing" for i in rules.area_open_issues(db, a)):
        return "building"
    return "next" if pick.area is not None and pick.area.id == a.id else "waiting"


def plan_row(db: Session, a: FftArea, pick: rules.Pick, frozen: bool) -> dict:
    """One plan: its stage, how far its fixes and checks are, and who it waits on."""
    issues = rules.area_open_issues(db, a)
    open_ids = {i.id for i in issues}
    checks = []
    for c in rules.area_checks(db, a):
        st = rules.check_state(db, c)
        tied = {i.id for i in rules.check_issues(db, c)}
        if st["state"] != "passed" or tied & open_ids:  # (this plan's checks now: a check that passed long ago isn't its progress)
            checks.append((c, st))
    turn = rules.area_turn(db, a)
    s = stage(db, a, turn, pick, frozen)
    fixed = sum(1 for i in issues if i.state in ("ready", "merge_ok"))
    passed = sum(1 for _, st in checks if st["state"] == "passed")
    to_try = [c for c, st in checks if st["state"] == "to_try"]
    asks = sum(1 for i in issues if i.state == "asks") + sum(1 for _, st in checks if st["state"] == "asks")
    oks = sum(1 for i in issues if i.state == "merge_ok")
    if s == "held":
        waits = "Held: Claude doesn't take it"
    elif turn == "brett":
        bits = [f"{len(to_try)} check{'s' if len(to_try) != 1 else ''} to try" if to_try else "",
                f"{asks} question{'s' if asks != 1 else ''}" if asks else "", f"{oks} fix{'es' if oks != 1 else ''} to OK" if oks else ""]
        waits = "You: " + (" · ".join(b for b in bits if b) or "a fix to look at")
    elif turn == "claude":
        waits = "Claude" + (" (game night: nothing merges)" if frozen else "")
    else:
        waits = "Nobody"
    feats: dict[str, int] = {}
    for i in issues:
        f = taxonomy.feature(i.feature)
        feats[f.title if f else "No Feature yet"] = feats.get(f.title if f else "No Feature yet", 0) + 1
    return {"a": a, "stage": s, "stage_said": STAGES[s], "turn": turn, "lane": rules.lane_of(a),
            "incident": bool(a.careful_until and a.careful_until > rules.now()),
            "issues": len(issues), "fixed": fixed, "checks": len(checks), "passed": passed, "minutes": sum(c.minutes or 0 for c in to_try),
            "waits": waits, "features": sorted(feats.items(), key=lambda x: -x[1]), "kind": "Product Area" if a.key else "Roadmap build",
            "locked": a.lock_owner if a.lock_until and a.lock_until > rules.now() else "", "check_ids": {c.id for c, _ in checks}}


def queue(db: Session) -> dict:
    """The Queue: the Roadmap's items that have plans, in Brett's order, each with its plans in his order; held plans below
    the cut line. An item with no plan (an idea not built yet, or one finished) isn't Development's: it waits on the
    Roadmap (issue 49, Nov 20: "Why do these exist here if they are still open?")."""
    pick = rules.pick_next(db)
    skipped = dict(pick.skipped)
    frozen = rules.freeze_state(db)["on"]
    items, held = [], []
    for it in db.scalars(select(FftItem).order_by(FftItem.place, FftItem.id)):
        rows = []
        for a in db.scalars(select(FftArea).where(FftArea.item_id == it.id, FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id)):
            if rules.area_turn(db, a) == "done" and not rules.area_open_issues(db, a):
                continue  # (on Done)
            row = plan_row(db, a, pick, frozen)
            row["item"] = it
            (held if a.held else rows).append(row)
        if not rows and not any(h["item"].id == it.id for h in held):
            continue
        why = skipped.get(it.title, "")
        items.append({"it": it, "n": len(items) + 1, "plans": rows, "why": f"skipped: {why}" if why else ""})
    return {"rows": items, "held": held, "pick": pick, "above": sum(len(x["plans"]) for x in items),
            "yours": sum(1 for x in items for r in x["plans"] if r["turn"] == "brett")}


def done(db: Session) -> list[dict]:
    """Plans with nothing open, the most recently busy first, with what they closed."""
    out = []
    for a in db.scalars(select(FftArea).where(FftArea.archived.is_(False))):
        if rules.area_turn(db, a) != "done" or rules.area_open_issues(db, a):
            continue
        had = db.scalar(select(FftIssue.id).where(FftIssue.area_id == a.id).limit(1)) is not None
        last = db.scalar(select(FftEvent.at).where(FftEvent.area_id == a.id).order_by(FftEvent.at.desc()).limit(1))
        n_closed = db.scalar(select(func.count()).select_from(FftIssue).where(FftIssue.area_id == a.id, FftIssue.state == "closed"))
        n_passed = sum(1 for c in rules.area_checks(db, a) if rules.check_state(db, c)["state"] == "passed")
        if not had and not n_passed:
            continue  # (a batch that never held anything isn't done work)
        out.append({"a": a, "item": db.get(FftItem, a.item_id), "lane": rules.lane_of(a), "last": last, "closed": n_closed, "passed": n_passed})
    return sorted(out, key=lambda d: d["last"] or datetime.min.replace(tzinfo=rules.now().tzinfo), reverse=True)


def check_rows(db: Session, area: FftArea | None = None) -> tuple[list[dict], list[str]]:
    """Every check (or a plan's), with where it stands on each device; and the devices any of them is tried on."""
    q = select(FftCheck).where(FftCheck.retired.is_(False))
    if area is not None:
        q = q.where(FftCheck.area_id == area.id)
    rows, used = [], set()
    for c in db.scalars(q.order_by(FftCheck.area_id.nulls_last(), FftCheck.place, FftCheck.id)):
        st = rules.check_state(db, c)
        devs = {d: (views.CHECK_WORD.get(s, s), CHECK_TONE.get(s, "quiet")) for d, s in st["devices"].items()}
        if st["state"] in ("preflight", "wrong", "asks"):  # (a state of the check as a whole, on every device)
            devs = {d: (views.check_word(st), CHECK_TONE[st["state"]]) for d in st["devices"]}
        used |= set(devs)
        tied = [i.id for i in rules.check_issues(db, c)]
        a = db.get(FftArea, c.area_id) if c.area_id else None
        rows.append({"key": f"c{c.id}", "c": c, "area": a, "devices": devs, "issues": tied, "word": views.check_word(st)})
    return rows, [d for d in DEVICES if d in used]


def listed_keys(db: Session, frm: str) -> list[str]:
    """The item window's ↑ ↓ on Work's Checks (`checks`) or a plan's Test round (`round:<id>`)."""
    if frm == "checks":
        return [r["key"] for r in check_rows(db)[0]]
    if frm.startswith("round:") and frm[6:].isdigit() and (a := db.get(FftArea, int(frm[6:]))):
        ids = plan_row(db, a, rules.Pick(None, ""), False)["check_ids"]
        rows = check_rows(db, a)[0]
        return [r["key"] for r in rows if r["c"].id in ids] + [r["key"] for r in rows if r["c"].id not in ids]
    if frm.startswith("plan:") and frm[5:].isdigit():
        return [f"i{i.id}" for i in _plan_issues(db, int(frm[5:]))]
    return []


# ------------------------------------------------------------------ Scheduled work and How we work


def jobs(db: Session) -> list[dict]:
    """The jobs that run on their own (app/data/jobs.json) and each one's last report; a job that never reported says so."""
    out = []
    for j in json.loads(JOBS_FILE.read_text())["jobs"]:
        row = db.get(ToolSetting, JOB_KEY + j["key"])
        try:
            last = json.loads(row.value) if row is not None and row.value else {}
        except ValueError:
            last = {}
        at = datetime.fromisoformat(last["at"]) if last.get("at") else None
        late = at is not None and (rules.now() - at).total_seconds() > j["every_hours"] * 3600 * 1.5
        out.append({**j, "at": at, "result": last.get("result", ""), "words": last.get("words", ""), "late": late})
    return out


def job_keys() -> set[str]:
    return {j["key"] for j in json.loads(JOBS_FILE.read_text())["jobs"]}


def report_job(db: Session, actor: str, key: str, result: str, words: str = "") -> None:
    """A job's run: ok or failed, with a line of what it found (never anyone's writing)."""
    if key not in job_keys():
        raise rules.RuleError("bad", f"There's no job “{key}”: app/data/jobs.json lists them.")
    if result not in ("ok", "failed"):
        raise rules.RuleError("bad", "A run is ok or failed.")
    row = db.get(ToolSetting, JOB_KEY + key) or ToolSetting(key=JOB_KEY + key)
    row.value = json.dumps({"at": rules.now().isoformat(), "result": result, "words": words.strip()[:200]})
    db.merge(row)
    rules._event(db, actor, "job_ran", "tool", 0, job=key, result=result)


LANE_NEEDS = {"ship": ("Nothing a person sees", "Merges when its tests and the review pass", "Nobody: the tests"),
              "look": ("Something people see", "Merges when green, after Claude tries it", "You, the batch, once it's live"),
              "careful": ("Who sees what, signing in, spending, the D&D Beyond bridge, a database change that alters data",
                          "Waits for your try on your Mac, then merges", "You, before it merges")}
STEPS = ("Read its area whole: every issue and failed check", "Design one fix, written before it's built",
         "Build it, one area at a time (its lock)", "Look at it: every person, page and width",
         "The review at high effort, then one pull request", "Its checks, tried by Claude first, then your test round")


def how() -> dict:
    """How we work, drawn from the files the tools follow (app/data/lanes.json, rules.LANES), so it can't drift."""
    r = lanes.rules()
    files = {"careful": r["careful"] + ["a migration that " + m.strip().lower() for m in r["careful_migration"][:5]], "look": r["look"], "ship": ["everything else"]}
    return {"lanes": [{"key": k, "said": rules.LANE_SAID[k], "what": LANE_NEEDS[k][0], "needs": LANE_NEEDS[k][1], "who": LANE_NEEDS[k][2],
                       "files": files[k]} for k in rules.LANES], "steps": STEPS}


def _who(db: Session, actor: str, said: dict | None = None) -> str:
    if said is not None and actor in said:
        return said[actor]
    if actor.startswith("user:") and actor[5:].isdigit():
        out = views.first_name_of(db, int(actor[5:])) or "An admin"
    else:
        out = {"claude": "Claude", "askdnd": "askdnd", "mini": "Mac Mini"}.get(actor, actor or "Someone")
    if said is not None:
        said[actor] = out
    return out


# ------------------------------------------------------------------ the pages


@router.get("/manage/work")
def page(request: Request, tab: str = "queue", open: str = "", db: Session = Depends(get_db)):
    user, denied = testing_page._admin(request)
    if denied:
        return denied
    tab = tab if tab in dict(TABS) else "queue"
    rules._expire_rounds(db)
    rules.confirm_due(db)
    q = queue(db)
    ctx = {"tab": tab, "tabs": TABS, "q": q, "status": testing_page.status(db), "missed": views.missed(db), "lanes": rules.LANES,
           "lane_said": rules.LANE_SAID, "stages": STAGES, "device_name": DEVICE_NAME, "n_done": 0,
           "all_items": list(db.scalars(select(FftItem).order_by(FftItem.place, FftItem.id))),
           "all_areas": list(db.scalars(select(FftArea).where(FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id))),
           "pick": testing_page._key(open), "toast": request.session.pop("toast", None)}
    d = done(db)
    ctx["n_done"] = len(d)
    if tab == "done":
        ctx["done"] = d
    elif tab == "checks":
        ctx["checks"], ctx["devices"] = check_rows(db)
    elif tab == "scheduled":
        ctx["jobs"] = jobs(db)
    elif tab == "how":
        ctx["how"] = how()
    db.commit()
    return templates.TemplateResponse(request, "fft_work.html", ctx)


def _above(db: Session) -> list[int]:
    """The plans above the line, in order (as the Queue lists them): a plan's page says where it is among them."""
    out = []
    for it in db.scalars(select(FftItem).order_by(FftItem.place, FftItem.id)):
        for a in db.scalars(select(FftArea).where(FftArea.item_id == it.id, FftArea.archived.is_(False), FftArea.held.is_(False)).order_by(FftArea.place, FftArea.id)):
            if rules.area_open_issues(db, a) or rules.area_turn(db, a) != "done":
                out.append(a.id)
    return out


def _plan_issues(db: Session, area_id: int) -> list[FftIssue]:
    return list(db.scalars(select(FftIssue).where(FftIssue.area_id == area_id)
                           .order_by((FftIssue.state == "closed").asc(), FftIssue.id.desc())))


@router.get("/manage/work/{area_id:int}")
def plan(request: Request, area_id: int, tab: str = "overview", db: Session = Depends(get_db)):
    """A plan's page: Overview, Issues, Test round, Timeline (a link to a group goes to its page; one item opens in the
    item window)."""
    user, denied = testing_page._admin(request)
    if denied:
        return denied
    a = db.get(FftArea, area_id)
    if a is None:
        return HTMLResponse("This plan isn't here any more.", status_code=404)
    tab = tab if tab in dict(PLAN_TABS) else "overview"
    pick = rules.pick_next(db)
    row = plan_row(db, a, pick, rules.freeze_state(db)["on"])
    issues = _plan_issues(db, a.id)
    checks, devices = check_rows(db, a)
    now_ = [r for r in checks if r["c"].id in row["check_ids"]]  # (this plan's checks now; those that passed before it, under)
    checks = now_ + [r for r in checks if r["c"].id not in row["check_ids"]]
    events = list(db.scalars(select(FftEvent).where(FftEvent.area_id == a.id).order_by(FftEvent.at.desc(), FftEvent.id.desc()).limit(200)))
    questions = list(db.scalars(select(FftQuestion).where(FftQuestion.answered_at.is_(None), FftQuestion.about == "issue",
                                                          FftQuestion.about_id.in_([i.id for i in issues] or [0]))))
    who: dict = {}
    order = _above(db)
    at = order.index(a.id) + 1 if a.id in order else 0
    db.commit()
    return templates.TemplateResponse(request, "fft_plan.html", {
        "a": a, "item": db.get(FftItem, a.item_id), "row": row, "tab": tab, "tabs": PLAN_TABS, "issues": issues,
        "open_n": sum(1 for i in issues if i.state != "closed"), "checks": checks, "now_n": len(now_), "devices": devices, "device_name": DEVICE_NAME,
        "events": [(e, views.event_words(e), _who(db, e.actor, who)) for e in events], "questions": questions,
        "issue_word": views.ISSUE_WORD, "closed_word": views.CLOSED_WORD, "lane_said": rules.LANE_SAID, "lanes": rules.LANES,
        "at": at, "of": len(order), "paths": {i.id: taxonomy.path(i.feature) for i in issues},
        "turns": {i.id: views.turn_pill(*views.issue_turn(db, i)) for i in issues if i.state != "closed"},
        "status": testing_page.status(db), "toast": request.session.pop("toast", None)})


def forward(show: str, open: str) -> RedirectResponse:
    """Testing's old addresses (Where it stands, Claude's, Done): Work's Queue, or its Checks with the check open."""
    to = WORK if show in ("", "stands") else f"{WORK}?tab=checks"
    if open:
        to += ("&" if "?" in to else "?") + f"open={open}"
    return RedirectResponse(to, status_code=303)
