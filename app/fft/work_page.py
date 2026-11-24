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
from app.fft.models import FftArea, FftCheck, FftEvent, FftIssue, FftItem, FftPull, FftQuestion
from app.models import JobRun, ToolSetting
from app.templating import templates

router = APIRouter()
WORK = "/manage/work"
REPO = "jettison-v/dndsy"  # (where an Upkeep card's pull request opens)
# ("queue" is Your order: the Queue, kept with one job, Brett's order of importance, lanes and holds; Nov 24)
TABS = (("board", "Board"), ("queue", "Your order"), ("checks", "Checks"), ("scheduled", "Scheduled"), ("how", "How we work"))
# (Done leaves the list, Brett Nov 20: finished plans and passed checks are each list's History, `?tab=done` and
# `?tab=checks&history=1`, a quiet link under it, never a tab or a count)
PLAN_TABS = (("overview", "Overview"), ("issues", "Issues"), ("round", "Test round"), ("timeline", "Timeline"))
# (the Work Flow Map's stages, worked out from what's true: words and state_word's tone)
STAGES = {"blocker": ("Blocker: Claude's now", "failed"), "held": ("Held", "quiet"), "frozen": ("Held for game night", "quiet"), "round": ("In your round", "ask"),
          "try": ("Live: try it", "ask"), "yours": ("Waiting on you", "ask"), "building": ("Building", "claude"),
          "next": ("Claude's next", "claude"), "waiting": ("Waiting its turn", "quiet"), "done": ("Done", "passed")}
CHECK_TONE = {"to_try": "ask", "later": "ask", "asks": "ask", "failed": "failed", "fixing": "claude", "wrong": "claude",
              "blocked": "claude", "preflight": "claude", "deploying": "claude", "passed": "passed", "retired": "quiet"}
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


def build_row(db: Session, it: FftItem, pick: rules.Pick, frozen: bool) -> dict:
    """A Roadmap build as a row of the queue (issue 62, Brett's pick: one row, its steps as progress): its stage, steps
    done of all, its plans' checks, whose turn; it opens the item on the Roadmap, where its steps are."""
    from app.fft import roadmap_page
    from app.fft.models import FftStep

    steps = list(db.scalars(select(FftStep).where(FftStep.item_id == it.id)))
    plans = list(db.scalars(select(FftArea).where(FftArea.item_id == it.id, FftArea.archived.is_(False))))
    checks = [rules.check_state(db, c) for a in plans for c in rules.area_checks(db, a)]
    done = sum(1 for x in steps if x.done_at)
    if it.held:
        s = "held"
    elif frozen:
        s = "frozen"
    elif it.next_whose == "brett":
        s = "yours"
    elif pick.item is not None and pick.item.id == it.id and pick.area is None:
        s = "next"
    elif done or any(rules.area_turn(db, a) == "brett" or any(i.state == "fixing" for i in rules.area_open_issues(db, a)) for a in plans):
        s = "building"
    else:
        s = "waiting"
    sc = rules.latest_scope(db, it)
    waits = ("Held: Claude doesn't take it" if s == "held" else f"You: {it.next_step}" if s == "yours"
             else "Claude" + (f": {it.next_step}" if it.next_step else ": write its steps" if sc and sc.agreed_at and not steps
                              else ": ship it, every step is done" if s != "held" and steps and done == len(steps) else ""))  # (issue 72)
    return {"it": it, "kind": "i", "key": f"i{it.id}", "stage": s, "stage_said": STAGES[s], "steps": len(steps), "done": done,
            "checks": len(checks), "passed": sum(1 for c in checks if c["state"] == "passed"), "waits": waits,
            "ship": s not in ("held", "yours") and bool(steps) and done == len(steps),
            "turn": "brett" if s == "yours" else "claude", "section": roadmap_page.SECTION_SAID.get(it.section, ""), "size": it.size}


def queue(db: Session) -> dict:
    """The Queue: Development's one queue (issue 62, Brett's picks Nov 20: "I thought we had one consolidated development
    queue in the plan"): every Product Area batch and every Roadmap build whose scope he agreed, in his one drag order
    (`rules.queue_entries`), held rows below the cut line. Ideas still being discussed wait on the Roadmap."""
    pick = rules.pick_next(db)
    frozen = rules.freeze_state(db)["on"]
    rows, held = [], []
    for kind, x in rules.queue_entries(db):
        if kind == "a":
            if rules.area_turn(db, x) == "done" and not rules.area_open_issues(db, x):
                continue  # (its History)
            row = plan_row(db, x, pick, frozen) | {"kind_key": "a", "key": f"a{x.id}"}
            (held if x.held else rows).append(row)
        else:
            row = build_row(db, x, pick, frozen) | {"kind_key": "i"}
            (held if x.held else rows).append(row)
            for a in db.scalars(select(FftArea).where(FftArea.item_id == x.id, FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id)):
                if rules.area_turn(db, a) == "done" and not rules.area_open_issues(db, a):
                    continue  # (a build's plan of its own, under its row; done, in History)
                sub = plan_row(db, a, pick, frozen) | {"kind_key": "a", "key": f"a{a.id}", "sub": True}
                (held if (a.held or x.held) else rows).append(sub)
    for n, r in enumerate(r for r in rows if not r.get("sub")):
        r["n"] = n + 1
    nxt = pick.item.title if pick.item is not None and pick.area is None else (pick.area.title if pick.area is not None else "")
    return {"rows": rows, "held": held, "pick": pick, "above": len(rows), "next": nxt,
            "yours": sum(1 for r in rows if r["turn"] == "brett")}


# ------------------------------------------------------------------ the Board (item 39, 4 of 4; Brett's picks on The Work Board)
#
# Every piece of work from Waiting to yours to try, in five columns, each move askdnd's own record: Waiting (a gate not
# met yet: your go-ahead, your step, held, your round), Ready (in Claude's order, each with its one line of why),
# Building (Claude's claim, one at a time), Shipping (a pull request on its way: in review, merging, going live, as
# GitHub and Railway report it) and Yours to try. A card is one piece that ends in one pull request: a Product Area's
# fixes (Feedback), a Roadmap build's plan (Roadmap), or a pull request with nothing behind it (Upkeep). Amber when
# stuck. A card opens its plan, its Roadmap item, or the pull request.

COLUMNS = (("waiting", "Waiting", "on a gate"), ("ready", "Ready", "Claude's order"), ("building", "Building", "Claude, one at a time"),
           ("shipping", "Shipping", "review, merge, live"), ("yours", "Yours to try", "you"))
BOARD_EMPTY = {"waiting": "Work waiting on a gate: your OK on its scope, your step, held below the line, or your round.",
               "ready": "Nothing Ready: what Claude may take next comes here, in the order it's taken.",
               "building": "Nothing being built: Claude's one claim shows here.",
               "shipping": "No pull request on its way.", "yours": "Nothing for you to try."}
WEEK = 7  # (days a Now item may wait behind other work before its card turns amber: Brett's fence, Nov 23)


def pull_stage(db: Session, p: FftPull) -> tuple[str, str, bool]:
    """A pull request's step in Shipping: (key, words, stuck)."""
    if p.state == "merged":
        return ("going_live", "Going live", False) if p.live_at is None else ("live", "Live", False)
    if p.tests == "failed":
        return "red", "Tests failed", True
    if p.merge_state == "dirty":
        return "conflicts", "Conflicts with main", True
    if p.merge_state == "behind":
        return "behind", "Behind main", False
    if p.tests == "passed" and p.auto_merge:
        return "merging", "Merging", False
    if p.tests == "passed" and p.merge_state == "clean":
        return ("held", "Waits for your try", False) if views._held_back(db, p) else ("not_merging", "Passed, not merging", True)
    return "review", "In review", False


def _card(kind: str, key: str, title: str, sub: str, href: str, why: str, lane: str = "", **kw) -> dict:
    return {"kind": kind, "key": key, "title": title, "sub": sub, "href": href, "why": why, "lane": lane, "pr": None,
            "stage": "", "stage_said": "", "stuck": False, "since": None} | kw


def yours_waits(db: Session, a: FftArea) -> str:
    """What waits on Brett from a plan, in a few words ("2 checks to try · 1 question"), or ""."""
    issues = rules.area_open_issues(db, a)
    states = [rules.check_state(db, c)["state"] for c in rules.area_checks(db, a)]
    to_try, asks = states.count("to_try"), states.count("asks") + sum(1 for i in issues if i.state == "asks")
    from app.fft.models import FftLocalTry

    oks = sum(1 for i in issues if i.state == "merge_ok")
    live = sum(1 for i in issues if i.state == "ready")
    local = db.scalar(select(func.count()).select_from(FftLocalTry).where(FftLocalTry.area_id == a.id, FftLocalTry.answer == ""))
    bits = ["your local try" if local else "", f"{to_try} check{'s' if to_try != 1 else ''} to try" if to_try else "",
            f"{live} fix{'es' if live != 1 else ''} live to try" if live and not to_try else "",
            f"{asks} question{'s' if asks != 1 else ''}" if asks else "", f"{oks} fix{'es' if oks != 1 else ''} to OK" if oks else ""]
    return " · ".join(b for b in bits if b)


COLUMN_TONE = {"waiting": "quiet", "ready": "claude", "building": "claude", "shipping": "passed", "yours": "ask"}


def on_board(b: dict) -> dict:
    """Where each plan or build sits on the Board, for Your order's Stage: {key: {"col", "said", "tone", "kind", "stuck",
    "yours"}}; "yours" when it also has checks waiting on Brett (its card in Yours to try)."""
    said = {k: name for k, name, _ in COLUMNS}
    out: dict = {}
    for col, _name, _who, cards in b["cols"]:
        for c in cards:
            key = c["key"]
            if key.endswith("-yours"):
                out.setdefault(key.removesuffix("-yours"), {"col": col, "said": said[col], "tone": COLUMN_TONE[col], "kind": c["kind"], "stuck": False})["yours"] = True
                continue
            out[key] = out.get(key, {}) | {"col": col, "said": said[col], "tone": COLUMN_TONE[col], "kind": c["kind"], "stuck": bool(c.get("stuck"))}
    return out


def board(db: Session) -> dict:
    """The Board's five columns of cards (see above)."""
    cols: dict[str, list[dict]] = {k: [] for k, _, _ in COLUMNS}
    turns: dict[int, str] = {}

    def turn_of(_db: Session, a: FftArea) -> str:  # (each plan's turn worked out once for the page)
        if a.id not in turns:
            turns[a.id] = rules.area_turn(db, a)
        return turns[a.id]

    ready = {a.id: (reason, why) for a, reason, why in rules.ready_areas(db, turn_of)}
    order = {a_id: n for n, a_id in enumerate(ready)}
    open_pulls = list(db.scalars(select(FftPull).where((FftPull.state == "open") | ((FftPull.state == "merged") & FftPull.live_at.is_(None)))
                                .order_by(FftPull.number)))
    placed: set[int] = set()
    shown: set[int] = set()
    now_ = rules.now()

    def pulls_of(a: FftArea) -> list[FftPull]:  # (an item's own pull request goes to the first of its plans that shows it, once)
        return [p for p in open_pulls if p.id not in placed and (p.area_id == a.id or (p.area_id is None and p.item_id == a.item_id and not rules.pull_upkeep(p)))]

    def area_card(a: FftArea, it: FftItem | None) -> None:
        kind = "roadmap" if it is not None and not it.standing else "feedback"
        sub = it.title if kind == "roadmap" else "Product Area"
        base = {"kind": kind, "key": f"a{a.id}", "title": a.title, "sub": sub, "href": f"/manage/work/{a.id}", "lane": rules.lane_of(a)}
        live_claim = bool(a.lock_owner and a.lock_until and a.lock_until > now_)
        pulls = pulls_of(a)
        turn = turn_of(db, a)
        shown.add(a.id)
        if live_claim:
            cols["building"].append(_card(**base, why="Claude is building it", since=a.lock_until - rules.LOCK, stage="claimed"))
        elif pulls:  # (a card is one piece that ends in one pull request: a plan with two on their way shows both, Nov 24)
            placed.update(x.id for x in pulls)
            for n, p in enumerate(pulls):
                key, said, stuck = pull_stage(db, p)
                cols["shipping"].append(_card(**base | ({"key": f"a{a.id}-p{p.number}"} if n else {}), why=f"Pull request #{p.number}", pr=p.number,
                                              stage=key, stage_said=said, stuck=stuck))
        elif turn == "brett":
            pass  # (its card is in Yours to try, below)
        elif turn == "claude" and a.id in ready:
            reason, why = ready[a.id]
            last = db.scalar(select(func.max(FftEvent.at)).where(FftEvent.area_id == a.id))
            stuck = kind == "roadmap" and it.section == "now" and reason == "queue" and order[a.id] > 0 and last is not None and (now_ - last).days >= WEEK
            cols["ready"].append(_card(**base, why=why + (" · waiting a week behind other work" if stuck else ""), stuck=stuck, stage=reason, n=order[a.id]))
        elif turn == "claude":
            why = ("Held below the line" if a.held or (it is not None and it.held) else "In your open round: nothing merges there" if rules.in_open_round(db, a)
                   else f"Your step: {it.next_step}" if it is not None and it.next_whose == "brett" else "Waits its turn")
            cols["waiting"].append(_card(**base, why=why))
        yours = yours_waits(db, a)
        if yours:  # (what waits on Brett from this plan, beside whatever else it's doing: the try of what shipped)
            cols["yours"].append(_card(**base | {"key": f"a{a.id}-yours"}, why=yours))

    for kind_key, x in rules.queue_entries(db):
        if kind_key == "a":
            area_card(x, db.get(FftItem, x.item_id))
            continue
        plans = list(db.scalars(select(FftArea).where(FftArea.item_id == x.id, FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id)))
        for a in plans:
            area_card(a, x)
        if not plans:  # (an agreed build with no plan yet: its plan is made when Claude claims it)
            mine = x.next_whose != "brett" and not x.held
            (cols["ready"] if mine else cols["waiting"]).append(_card(
                "roadmap", f"i{x.id}", x.title, "Roadmap build", f"/manage/roadmap/{x.id}",
                "Next to plan: Claude makes its plan when it claims it" if mine else ("Held below the line" if x.held else f"Your step: {x.next_step}")))
    stray = [a for a in db.scalars(select(FftArea).where(FftArea.archived.is_(False), FftArea.lock_owner != "").order_by(FftArea.id))
             if a.id not in shown and a.lock_until and a.lock_until > now_]
    stray += [db.get(FftArea, a_id) for a_id in ready if a_id not in shown]
    for a in stray:  # (a plan claimed or Ready outside the queue's builds: claimed by hand, say; it shows all the same)
        if a.id not in shown:
            area_card(a, db.get(FftItem, a.item_id))
    for it in db.scalars(select(FftItem).where(FftItem.standing.is_(False), FftItem.section.in_(("now", "next"))).order_by(rules.item_rank(), FftItem.place, FftItem.id)):
        sc = rules.latest_scope(db, it)
        if sc is not None and sc.agreed_at is None:  # (its scope written, your OK not given yet: the first gate)
            cols["waiting"].append(_card("roadmap", f"i{it.id}", it.title, "Roadmap item", f"/manage/roadmap/{it.id}", f"Your OK on its scope (version {sc.version})"))
    for p in open_pulls:  # (Upkeep: a pull request with nothing behind it is a card of its own)
        if p.id in placed or not rules.pull_upkeep(p):
            continue
        key, said, stuck = pull_stage(db, p)
        cols["shipping"].append(_card("upkeep", f"p{p.number}", p.title or f"Pull request #{p.number}", "Dependabot" if p.by_bot else "Upkeep",
                                      f"https://github.com/{REPO}/pull/{p.number}", f"Pull request #{p.number}", pr=p.number, stage=key, stage_said=said, stuck=stuck))
    cols["ready"].sort(key=lambda c: c.get("n", 10_000))
    return {"cols": [(k, label, who, cols[k]) for k, label, who in COLUMNS],
            "stuck": sum(1 for cards in cols.values() for c in cards if c["stuck"])}


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
        if st["state"] in ("preflight", "wrong", "asks", "deploying"):  # (a state of the check as a whole, on every device)
            devs = {d: (views.check_word(st), CHECK_TONE[st["state"]]) for d in st["devices"]}
        used |= set(devs)
        tied = [i.id for i in rules.check_issues(db, c)]
        a = db.get(FftArea, c.area_id) if c.area_id else None
        rows.append({"key": f"c{c.id}", "c": c, "area": a, "devices": devs, "issues": tied, "word": views.check_word(st), "state": st["state"]})
    return rows, [d for d in DEVICES if d in used]


def listed_keys(db: Session, frm: str) -> list[str]:
    """The item window's ↑ ↓ on Work's Checks (`checks`) or a plan's Test round (`round:<id>`)."""
    if frm in ("checks", "checks:passed"):  # (open checks; or History's, the passed ones)
        return [r["key"] for r in check_rows(db)[0] if (r["state"] == "passed") == (frm == "checks:passed")]
    kind, _, rest = frm.partition(":")
    num, _, past = rest.partition(":")  # (`round:<id>` its open work's checks, `round:<id>:passed` its History; same for plan)
    if kind == "round" and num.isdigit() and (a := db.get(FftArea, int(num))):
        ids = plan_row(db, a, rules.Pick(None, ""), False)["check_ids"]
        return [r["key"] for r in check_rows(db, a)[0] if (r["c"].id in ids) != bool(past)]
    if kind == "plan" and num.isdigit():
        return [f"i{i.id}" for i in _plan_issues(db, int(num)) if (i.state == "closed") == bool(past)]
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
        if not last and j.get("reads") == "job_runs":  # (the backup reports to its own table: Manage's Overview reads it too)
            run = db.scalar(select(JobRun).where(JobRun.name == j["key"]).order_by(JobRun.id.desc()))
            if run is not None:
                last = {"at": run.finished_at.isoformat(), "result": "ok" if run.status == "ok" else "failed", "words": run.detail[:200] if run.status != "ok" else ""}
        at = datetime.fromisoformat(last["at"]) if last.get("at") else None
        late = at is not None and j.get("reads") != "elsewhere" and (rules.now() - at).total_seconds() > j["every_hours"] * 3600 * 1.5
        out.append({**j, "at": at, "result": last.get("result", ""), "words": last.get("words", ""), "late": late})
    return out


def job_runs(db: Session, j: dict, limit: int = 10) -> list[dict]:
    """A job's latest runs, newest first: {at, result, words} (its reports here, or its own table's)."""
    if j.get("reads") == "job_runs":
        return [{"at": r.finished_at, "result": "ok" if r.status == "ok" else "failed", "words": r.detail[:200] if r.status != "ok" else ""}
                for r in db.scalars(select(JobRun).where(JobRun.name == j["key"]).order_by(JobRun.id.desc()).limit(limit))]
    events = db.scalars(select(FftEvent).where(FftEvent.kind == "job_ran", FftEvent.data["job"].astext == j["key"])
                        .order_by(FftEvent.id.desc()).limit(limit))
    return [{"at": e.at, "result": e.data.get("result", ""), "words": e.data.get("words", "")} for e in events]


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
    rules._event(db, actor, "job_ran", "tool", 0, job=key, result=result, words=words.strip()[:200])  # (the job's own line, its history in the side panel)


LANE_NEEDS = {"ship": ("Nothing a person sees", "Merges when its tests and the review pass", "Nobody: the tests"),
              "look": ("Something people see", "Merges when green, after Claude tries it", "You, the batch, once it's live"),
              "careful": ("Who sees what, signing in, spending, the D&D Beyond bridge, a database change that alters data",
                          "Waits for your try on your Mac, then merges", "You, before it merges")}
STEPS = ("Claude asks askdnd for work, and askdnd hands over the top of Ready (a claim, one at a time)",
         "Read its area whole: every issue and failed check",
         "Design one fix; a design question is a mockup sent to askdnd at once and asked in For you (comment and pick here or on claude.ai)",
         "Build it, then look at it: every person, page and width",
         "The review at high effort, then one pull request: GitHub reports it to askdnd, and the Board shows its step",
         "Merged when its tests pass and its lane allows; askdnd marks it live by itself, and its checks, tried by Claude first, reach For you",
         "Live, Claude tries it again: a fix that fails goes back to To fix, and you're told why")  # (issue 74; item 39, Nov 24)


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
def page(request: Request, tab: str = "board", open: str = "", history: int = 0, db: Session = Depends(get_db)):
    user, denied = testing_page._admin(request)
    if denied:
        return denied
    tab = tab if tab in dict(TABS) or tab == "done" else "board"
    rules._expire_rounds(db)
    rules.confirm_due(db)
    q = queue(db)
    ctx = {"tab": tab, "tabs": TABS, "q": q, "status": testing_page.status(db), "gap_words": views.GAP_WORDS, "lanes": rules.LANES,
           "lane_said": rules.LANE_SAID, "stages": STAGES, "device_name": DEVICE_NAME, "history": bool(history),
           "all_items": list(db.scalars(select(FftItem).order_by(FftItem.place, FftItem.id))),
           "all_areas": list(db.scalars(select(FftArea).where(FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id))),
           "pick": testing_page._key(open), "toast": request.session.pop("toast", None)}
    if tab == "done":
        ctx["done"] = done(db)
    elif tab == "checks":  # (open checks; History, the passed ones)
        rows, ctx["devices"] = check_rows(db)
        if ctx["pick"] and any(r["key"] == ctx["pick"] and r["state"] == "passed" for r in rows):
            ctx["history"] = history = 1  # (an old link to a check that has passed: it's in History now)
        ctx["checks"] = [r for r in rows if (r["state"] == "passed") == bool(history)]
    elif tab == "scheduled":
        ctx["jobs"] = jobs(db)
    elif tab == "board":
        ctx["board"], ctx["board_empty"] = board(db), BOARD_EMPTY
    if tab == "queue":  # (Your order in the Board's words: each plan's column, kind and whether it's stuck; step 36, Nov 24)
        ob = on_board(board(db))
        for r in q["rows"] + q["held"]:  # (a build with plans has no card of its own: its row says its first plan's column)
            if r.get("sub") and f"i{r['a'].item_id}" not in ob and r["key"] in ob:
                ob[f"i{r['a'].item_id}"] = ob[r["key"]]
        ctx["on_board"] = ob
    elif tab == "how":
        ctx["how"] = how()
    db.commit()
    return templates.TemplateResponse(request, "fft_work.html", ctx)


def discuss(a: FftArea) -> dict:
    """Discuss with Claude from a plan (issue 19, Brett, Nov 17: a chat of its own for one area, listening to that area
    alone; the fresh sessions per Product Area trial in CLAUDE.md): a new Claude Code session with this message filled in."""
    n = a.id
    msg = (f'Let\'s work on askdnd\'s plan {n}, "{a.title}" (Backstage › Development), in a session of its own.\n\n'
           f"First read it: uv run python scripts/feedback.py issues --area {n} and checks --area {n}, each issue in full "
           f"(feedback.py issue <id>), docs/DECISIONS.md and its Product Area's heading in docs/MAP.md; say in your first "
           f"message what you read. Listen with this plan's own read mark: feedback.py inbox --listener area-{n}, and "
           f"feedback.py wait --listener area-{n} in the background while you wait on me.\n\n"
           f"Work only on this plan's issues, the whole area as one fix with the full review and one pull request "
           f"(feedback.py issue <id> pr <url> for each). Write back onto each issue what we decided "
           f'(feedback.py issue <id> tell "…"). Ask me in askdnd, never in chat, about what I did there.')
    from app.fft import roadmap_page  # (it reads this module: imported when used)

    return roadmap_page.links(msg)


@router.get("/manage/work/{area_id:int}/discuss")
def discuss_window(request: Request, area_id: int, db: Session = Depends(get_db)):
    _, denied = testing_page._admin(request)
    if denied:
        return denied
    a = db.get(FftArea, area_id)
    if a is None or a.archived:
        return HTMLResponse("This plan isn't here any more.", status_code=404)
    return templates.TemplateResponse(request, "_roadmap_discuss.html", {"label": f"Plan {a.id}: {a.title}", "back_to": "this plan's issues", "d": discuss(a)})


@router.get("/manage/work/jobs/{key}")
def job_panel(request: Request, key: str, db: Session = Depends(get_db)):
    """A scheduled job in the side panel (issue 55, Brett, Nov 20: "a description in the sidebar with more detail"): what it
    does, what it checks, what happens when it fails, and its latest runs."""
    _, denied = testing_page._admin(request)
    if denied:
        return denied
    j = next((x for x in jobs(db) if x["key"] == key), None)
    if j is None:
        return HTMLResponse("There's no such job.", status_code=404)
    return templates.TemplateResponse(request, "_fft_job.html", {"j": j, "runs": job_runs(db, j)})


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


def plan_view(db: Session, a: FftArea) -> dict:
    """A plan as its window and its page show it (Brett's picks M1 and P3 on Our Work, page by page, Nov 24): its facts
    on one line in the Board's words (its column, lane, fixes, checks, minutes to try, whose turn), its open issues and
    its checks now, each opening in the same window, and its latest moves."""
    row = plan_row(db, a, rules.pick_next(db), rules.freeze_state(db)["on"])
    issues = [i for i in _plan_issues(db, a.id) if i.state != "closed"]
    checks = [r for r in check_rows(db, a)[0] if r["c"].id in row["check_ids"]]
    col = on_board(board(db)).get(f"a{a.id}")
    events = [e for e in db.scalars(select(FftEvent).where(FftEvent.area_id == a.id).order_by(FftEvent.at.desc(), FftEvent.id.desc()).limit(40))
              if e.thing != "pull" or views.pull_worth_saying(e)][:10]
    who: dict = {}
    return {"a": a, "item": db.get(FftItem, a.item_id) if a.item_id else None, "row": row, "col": col, "issues": issues, "checks": checks,
            "lane_said": rules.LANE_SAID,
            "events": [(e, views.event_words(e), _who(db, e.actor, who)) for e in events],
            "turns": {i.id: views.turn_pill(*views.issue_turn(db, i)) for i in issues}}


@router.get("/manage/work/{area_id:int}")
def plan(request: Request, area_id: int, tab: str = "overview", history: int = 0, db: Session = Depends(get_db)):
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
    now_ = [r for r in checks if r["c"].id in row["check_ids"]]  # (this plan's checks now; those that passed before, its History)
    shown_checks = [r for r in checks if r["c"].id not in row["check_ids"]] if history else now_
    shown_issues = [i for i in issues if (i.state == "closed") == bool(history)]
    events = [e for e in db.scalars(select(FftEvent).where(FftEvent.area_id == a.id).order_by(FftEvent.at.desc(), FftEvent.id.desc()).limit(200))
              if e.thing != "pull" or views.pull_worth_saying(e)]
    questions = list(db.scalars(select(FftQuestion).where(FftQuestion.answered_at.is_(None), FftQuestion.about == "issue",
                                                          FftQuestion.about_id.in_([i.id for i in issues] or [0]))))
    who: dict = {}
    order = _above(db)
    at = order.index(a.id) + 1 if a.id in order else 0
    db.commit()
    return templates.TemplateResponse(request, "fft_plan.html", {
        "a": a, "item": db.get(FftItem, a.item_id), "row": row, "col": on_board(board(db)).get(f"a{a.id}"), "tab": tab, "tabs": PLAN_TABS, "issues": shown_issues, "history": bool(history),
        "open_n": sum(1 for i in issues if i.state != "closed"), "checks": shown_checks, "now_n": len(now_), "devices": devices, "device_name": DEVICE_NAME,
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
