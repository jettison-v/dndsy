"""Backstage › Global › Roadmap (Brett's picks, Nov 20, docs/mockups/roadmap-in-askdnd/): the ideas that need discussion,
in Brett's one order, for Brett and Claude only.

- **The Roadmap** (`/manage/roadmap`): the items by section (Now, Next, Later, Paused), each with its stage (worked out
  from what's true: an Idea, its Scope waiting for Brett's OK, Scope agreed, Building), size, steps done and next step;
  drag to reorder (the order Claude follows); + New idea; History: shipped and not doing.
- **An item's page** (`/manage/roadmap/<id>`): Scope (the latest version, earlier ones a click away, Brett's additions
  beside it with Claude's answers, Add to this item…, Scope looks right), Steps (a checklist, each Brett's or Claude's;
  Brett ticks his), Plans (its areas, in Development), Updates (its events).

The conversation stays in chat; Claude writes what was decided onto the item (`feedback.py roadmap`). Every change goes
through app/fft/rules.py."""

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config, web
from app.db import get_db
from app.fft import rules, testing_page, views, work_page
from app.fft.models import FftAddition, FftArea, FftEvent, FftItem, FftScope, FftStep
from app.templating import templates

router = APIRouter()
ROADMAP = "/manage/roadmap"
SECTION_SAID = {"now": "Now", "next": "Next", "later": "Later", "paused": "Paused", "shipped": "Shipped", "not_doing": "Not doing"}
STAGE = {"idea": ("Idea", "quiet"), "asked": ("Scoping", "claude"), "scoping": ("Scope: your OK", "ask"), "revising": ("Scope: Claude's", "claude"), "agreed": ("Scope agreed", "claude"),
         "building": ("Building", "claude"), "paused": ("Paused", "quiet"), "shipped": ("Shipped", "passed"),
         "not_doing": ("Not doing", "quiet")}
TABS = (("scope", "Scope"), ("steps", "Steps"), ("plans", "Plans"), ("updates", "Updates"))


def _admin(request: Request):
    return testing_page._admin(request)


def stage(db: Session, it: FftItem, scope: FftScope | None) -> str:
    if it.section in ("shipped", "not_doing", "paused"):
        return it.section
    if scope is None:
        return "asked" if it.scope_asked_at else "idea"  # (Scope it: Brett asked for its scope, Nov 21)
    if scope.agreed_at is None:
        return "revising" if scope.changes_at else "scoping"  # (Needs changes…: Claude's turn, issue 54)
    areas = db.scalars(select(FftArea).where(FftArea.item_id == it.id, FftArea.archived.is_(False)))
    return "building" if any(rules.area_open_issues(db, a) or rules.area_turn(db, a) != "done" for a in areas) else "agreed"


def row(db: Session, it: FftItem) -> dict:
    """One item, as a row: its stage, size, steps done, next step and whose."""
    scope = rules.latest_scope(db, it)
    s = stage(db, it, scope)
    steps = list(db.scalars(select(FftStep).where(FftStep.item_id == it.id).order_by(FftStep.place, FftStep.id)))
    first = next((x for x in steps if x.done_at is None), None)
    if s == "scoping":
        nxt = ("brett", f"OK its scope (version {scope.version})")
    elif s == "revising":
        nxt = ("claude", f"Answer your comments, write version {scope.version + 1}")
    elif s == "idea":
        nxt = ("claude", "Scope it")
    elif s == "asked":
        nxt = ("claude", "Write its scope · first in Claude's queue")
    elif first:
        nxt = (first.whose, first.text)
    else:
        nxt = ("", "")
    last = it.created_at
    for ev_at in db.scalars(select(FftEvent.at).where(FftEvent.thing == "item", FftEvent.thing_id == it.id).order_by(FftEvent.at.desc()).limit(1)):
        last = ev_at
    return {"it": it, "stage": s, "stage_said": STAGE[s], "scope": scope, "steps": len(steps), "done": sum(1 for x in steps if x.done_at),
            "next": nxt, "last": last, "status": it.status}


def items(db: Session, history: bool = False) -> list[dict]:
    open_ = rules.ROADMAP_SECTIONS
    q = select(FftItem).where(FftItem.standing.is_(False))
    q = q.where(FftItem.section.not_in(open_)) if history else q.where(FftItem.section.in_(open_))
    rows = [row(db, it) for it in db.scalars(q.order_by(rules.item_rank(), FftItem.place, FftItem.id))]
    if history:
        rows.sort(key=lambda r: r["it"].shipped_at or r["it"].created_at, reverse=True)
    return rows


def discuss(it: FftItem, sc: FftScope | None) -> dict:
    """Discuss with Claude (issue 54, Brett's pick Nov 20): a new Claude Code session with a message about this item
    filled in for him to read and send, on this Mac (claude://code/new, in the project's folder: Claude's app asks him to
    confirm it) or on claude.ai/code with the project's repo (a phone, the web). That session reads the item and writes
    what they decided back onto it, which reaches this session's inbox. Links: support.claude.com articles 14729294 and
    14898120."""
    n = it.id
    where = (f"its scope (version {sc.version}, " + ("waiting for my OK" if sc.agreed_at is None and sc.changes_at is None else
             "with changes I asked for" if sc.agreed_at is None else "agreed") + "), my comments, " if sc else "")
    msg = (f'Let\'s discuss askdnd\'s Roadmap item {n}, "{it.title}".\n\n'
           f"First read it: uv run python scripts/feedback.py roadmap {n} ({where}its steps). Then talk it through with me.\n\n"
           f"When we're done, write back onto the item what we decided: each point of mine as an addition "
           f'(feedback.py roadmap {n} add "…" --where discussion) with your answer (roadmap {n} answer …), and the scope\'s next '
           f'version with what changed (roadmap {n} scope … --changed "From our discussion: …"). Never say the scope looks '
           f"right: that's mine, in askdnd.")
    return links(msg)


def links(msg: str) -> dict:
    """The two ways to start a session with a message filled in: this Mac's Claude app, or claude.ai/code."""
    mac = {"q": msg} | ({"folder": config.DISCUSS_FOLDER} if config.DISCUSS_FOLDER else {})
    return {"message": msg, "mac": "claude://code/new?" + urlencode(mac), "web": "https://claude.ai/code/new?" + urlencode({"q": msg, "repo": config.DISCUSS_REPO})}


@router.get("/manage/roadmap/{item_id:int}/discuss")
def discuss_window(request: Request, item_id: int, db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    it = db.get(FftItem, item_id)
    if it is None or it.standing:
        return HTMLResponse("This Roadmap item isn't here any more.", status_code=404)
    return templates.TemplateResponse(request, "_roadmap_discuss.html", {"label": f"Roadmap item {it.id}", "back_to": "this item",
                                                                         "d": discuss(it, rules.latest_scope(db, it))})


@router.get("/manage/roadmap")
def page(request: Request, history: int = 0, db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    rows = items(db, bool(history))
    groups = [] if history else [(k, SECTION_SAID[k], [r for r in rows if r["it"].section == k]) for k in rules.ROADMAP_SECTIONS]
    db.commit()
    return templates.TemplateResponse(request, "fft_roadmap.html", {
        "rows": rows, "groups": groups, "history": bool(history), "stage_said": STAGE, "section_said": SECTION_SAID,
        "yours": sum(1 for r in rows if r["next"][0] == "brett"), "status": testing_page.status(db),
        "toast": request.session.pop("toast", None)})


@router.get("/manage/roadmap/new")
def new_window(request: Request):
    user, denied = _admin(request)
    if denied:
        return denied
    return templates.TemplateResponse(request, "_roadmap_new.html", {})


@router.post("/manage/roadmap")
def new(request: Request, title: str = Form(...), words: str = Form(""), section: str = Form("next"), db: Session = Depends(get_db)):
    """+ New idea: it lands as an Idea; Claude scopes it when it's next."""
    user, denied = _admin(request)
    if denied:
        return denied
    me = views.person(db, user)
    try:
        it = rules.new_idea(db, f"user:{me['id']}", title, words, section, user_id=me["id"])
    except rules.RuleError as e:
        raise HTTPException(400, e.words) from e
    db.commit()
    request.session["toast"] = "On the Roadmap as an idea: Claude scopes it when it's next"
    return RedirectResponse(f"{ROADMAP}/{it.id}", status_code=303)


@router.get("/manage/roadmap/{item_id:int}")
def item(request: Request, item_id: int, tab: str = "scope", ver: int = 0, db: Session = Depends(get_db)):
    user, denied = _admin(request)
    if denied:
        return denied
    it = db.get(FftItem, item_id)
    if it is None or it.standing:
        return HTMLResponse("This Roadmap item isn't here any more.", status_code=404)
    tab = tab if tab in dict(TABS) else "scope"
    r = row(db, it)
    scopes = list(db.scalars(select(FftScope).where(FftScope.item_id == it.id).order_by(FftScope.version)))
    shown = next((s for s in scopes if s.version == ver), scopes[-1] if scopes else None)
    adds = list(db.scalars(select(FftAddition).where(FftAddition.item_id == it.id).order_by(FftAddition.held.desc(), FftAddition.id.desc())))
    latest = scopes[-1] if scopes else None
    on_latest = [a for a in adds if latest and a.on_version == latest.version]
    lines: dict = {}
    for a in on_latest:
        if a.on_line and not a.on_line.startswith("q:"):
            lines.setdefault(a.on_line, []).append(a)
    answers = {int(a.on_line[2:]): a for a in reversed(on_latest) if a.on_line.startswith("q:") and a.on_line[2:].isdigit()}
    held = [a for a in adds if a.held]
    steps = list(db.scalars(select(FftStep).where(FftStep.item_id == it.id).order_by(FftStep.place, FftStep.id)))
    pick, frozen = rules.pick_next(db), rules.freeze_state(db)["on"]
    plans = [work_page.plan_row(db, a, pick, frozen)
             for a in db.scalars(select(FftArea).where(FftArea.item_id == it.id, FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id))]
    events = list(db.scalars(select(FftEvent).where(FftEvent.thing == "item", FftEvent.thing_id == it.id).order_by(FftEvent.at.desc()).limit(200)))
    who: dict = {}
    db.commit()
    return templates.TemplateResponse(request, "fft_roadmap_item.html", {
        "it": it, "r": r, "tab": tab, "tabs": TABS, "scopes": scopes, "shown": shown, "latest": latest,
        "line_comments": lines, "answers": answers, "question_keys": [f"q:{i}" for i in range(len(latest.questions) if latest else 0)], "held": held, "waits": rules.waits_on_brett(latest) and it.section in rules.ROADMAP_SECTIONS,
        "open": it.section in rules.ROADMAP_SECTIONS,
        "adds": adds, "steps": steps, "plans": plans, "section_said": SECTION_SAID, "sections": rules.ROADMAP_SECTIONS,
        "events": [(e, views.event_words(e), work_page._who(db, e.actor, who)) for e in events],
        "toast": request.session.pop("toast", None)})


@router.post("/manage/roadmap/{item_id:int}")
def change(request: Request, item_id: int, do: str = Form(...), words: str = Form(""), section: str = Form(""), step: int = Form(0),
           seen: int = Form(0), on: str = Form(""), addition: int = Form(0), db: Session = Depends(get_db)):
    """Brett's presses on an item: a comment on its scope (a line, the whole, an answer to a question), Scope looks right,
    Needs changes…, take back a comment not sent, tick a step of his, Scope it (or Not now), move it, ship it."""
    user, denied = _admin(request)
    if denied:
        return denied
    it = db.get(FftItem, item_id)
    if it is None or it.standing:
        raise HTTPException(404)
    me = views.person(db, user)
    actor = f"user:{me['id']}"
    back = f"{ROADMAP}/{it.id}"
    try:
        if do == "add":
            rules.add_to_item(db, actor, it, words, user_id=me["id"])
            said = "Added: Claude answers it here and writes the scope's next version"
        elif do == "comment":
            a = rules.comment_on_scope(db, actor, it, words, on[:12], user_id=me["id"])
            said = ("Kept: it goes to Claude with your answer to the scope" if a is not None and a.held else
                    "Answer taken back" if a is None else "Sent to Claude: it answers here")
        elif do == "drop":
            a = db.get(FftAddition, addition)
            if a is None or a.item_id != it.id:
                raise HTTPException(404)
            rules.drop_held(db, a)
            said = "Taken back"
        elif do == "changes":
            sc = rules.ask_changes(db, actor, it, words, user_id=me["id"], seen=seen or None)
            said = f"Sent to Claude: it answers each comment here and writes version {sc.version + 1}"
        elif do == "agree":
            sc = rules.agree_scope(db, actor, it, user_id=me["id"], seen=seen or None)
            said = f"Scope version {sc.version} agreed: Claude writes its steps"
        elif do in ("tick", "untick"):
            st = db.get(FftStep, step)
            if st is None or st.item_id != it.id:
                raise HTTPException(404)
            rules.tick_step(db, actor, st, do == "tick")
            said = "Done" if do == "tick" else "Not done after all"
            back += "?tab=steps"
        elif do in ("scope_it", "not_now"):  # (Scope it, Brett's pick Nov 21: first in Claude's queue, or back)
            rules.ask_scope(db, actor, it, do == "scope_it")
            said = "First in Claude's queue: its scope comes to For you for your OK" if do == "scope_it" else "Back in its place: Claude scopes it when it's next"
        elif do in ("hold", "unhold"):  # (Development's line, issue 62)
            rules.hold_item(db, actor, it, do == "hold")
            said = "Held below Development's line" if do == "hold" else "Back above Development's line"
            back = "/manage/work"
        elif do == "move":
            rules.move_item(db, actor, it, section)
            said = f"Moved to {SECTION_SAID[section]}"
        elif do in ("ship", "not_doing"):
            rules.ship_item(db, actor, it, not_doing=do == "not_doing")
            said = "Shipped: it's in the Roadmap's History" if do == "ship" else "Not doing: it's in the Roadmap's History"
            back = ROADMAP
        else:
            raise HTTPException(400)
    except rules.RuleError as e:
        request.session["toast"] = web.notice(e.words, "warn")
        return RedirectResponse(back, status_code=303)
    db.commit()
    request.session["toast"] = said
    return RedirectResponse(back, status_code=303)
