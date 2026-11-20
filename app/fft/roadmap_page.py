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

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import web
from app.db import get_db
from app.fft import rules, testing_page, views, work_page
from app.fft.models import FftAddition, FftArea, FftEvent, FftItem, FftScope, FftStep
from app.templating import templates

router = APIRouter()
ROADMAP = "/manage/roadmap"
SECTION_SAID = {"now": "Now", "next": "Next", "later": "Later", "paused": "Paused", "shipped": "Shipped", "not_doing": "Not doing"}
STAGE = {"idea": ("Idea", "quiet"), "scoping": ("Scope: your OK", "ask"), "agreed": ("Scope agreed", "claude"),
         "building": ("Building", "claude"), "paused": ("Paused", "quiet"), "shipped": ("Shipped", "passed"),
         "not_doing": ("Not doing", "quiet")}
TABS = (("scope", "Scope"), ("steps", "Steps"), ("plans", "Plans"), ("updates", "Updates"))


def _admin(request: Request):
    return testing_page._admin(request)


def stage(db: Session, it: FftItem, scope: FftScope | None) -> str:
    if it.section in ("shipped", "not_doing", "paused"):
        return it.section
    if scope is None:
        return "idea"
    if scope.agreed_at is None:
        return "scoping"
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
    elif s == "idea":
        nxt = ("claude", "Scope it")
    elif first:
        nxt = (first.whose, first.text)
    else:
        nxt = ("", "")
    last = it.created_at
    for ev_at in db.scalars(select(FftEvent.at).where(FftEvent.thing == "item", FftEvent.thing_id == it.id).order_by(FftEvent.at.desc()).limit(1)):
        last = ev_at
    return {"it": it, "stage": s, "stage_said": STAGE[s], "scope": scope, "steps": len(steps), "done": sum(1 for x in steps if x.done_at),
            "next": nxt, "last": last, "status": it.status or (SECTION_SAID.get(it.section, "") if s in ("shipped", "not_doing") else "")}


def items(db: Session, history: bool = False) -> list[dict]:
    open_ = rules.ROADMAP_SECTIONS
    q = select(FftItem).where(FftItem.standing.is_(False))
    q = q.where(FftItem.section.not_in(open_)) if history else q.where(FftItem.section.in_(open_))
    rows = [row(db, it) for it in db.scalars(q.order_by(rules.item_rank(), FftItem.place, FftItem.id))]
    if history:
        rows.sort(key=lambda r: r["it"].shipped_at or r["it"].created_at, reverse=True)
    return rows


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
    adds = list(db.scalars(select(FftAddition).where(FftAddition.item_id == it.id).order_by(FftAddition.id.desc())))
    steps = list(db.scalars(select(FftStep).where(FftStep.item_id == it.id).order_by(FftStep.place, FftStep.id)))
    pick, frozen = rules.pick_next(db), rules.freeze_state(db)["on"]
    plans = [work_page.plan_row(db, a, pick, frozen)
             for a in db.scalars(select(FftArea).where(FftArea.item_id == it.id, FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id))]
    events = list(db.scalars(select(FftEvent).where(FftEvent.thing == "item", FftEvent.thing_id == it.id).order_by(FftEvent.at.desc()).limit(200)))
    who: dict = {}
    db.commit()
    return templates.TemplateResponse(request, "fft_roadmap_item.html", {
        "it": it, "r": r, "tab": tab, "tabs": TABS, "scopes": scopes, "shown": shown, "latest": scopes[-1] if scopes else None,
        "adds": adds, "steps": steps, "plans": plans, "section_said": SECTION_SAID, "sections": rules.ROADMAP_SECTIONS,
        "events": [(e, views.event_words(e), work_page._who(db, e.actor, who)) for e in events],
        "toast": request.session.pop("toast", None)})


@router.post("/manage/roadmap/{item_id:int}")
def change(request: Request, item_id: int, do: str = Form(...), words: str = Form(""), section: str = Form(""), step: int = Form(0),
           seen: int = Form(0), db: Session = Depends(get_db)):
    """Brett's presses on an item: Add to this item…, Scope looks right, tick a step of his, move it, ship it."""
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
