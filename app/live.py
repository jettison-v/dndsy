"""The menu bar's table pieces: your character, the Party menu and the Live control.

- Your character (portrait and name) is one click to it, in the mode you used last (Battle / Sheet /
  Plan). Party ▾ lists the campaign's characters, your own first, with class, level and HP, and opens
  the one you pick in the mode you're in (menu bar Option B, Brett 2026-10-22).
- The Live pill answers one question (Brett, 2026-10-30, docs/mockups/table-without-modes.html):
  is your sheet connected? Connected (the bridge's extension heard it in the last
  REACH), what to do to connect, something to make by hand, or when the copy was last read; the
  character on screen, else your own, else the party's slowest sheet (the DM's). Its window holds
  how each sheet is connected, "Refresh <character> now" (anyone signed in, throttled) and "Refresh
  everyone" (reviewers only).
- Every open page at the table calls /live/sync every couple of minutes: the whole party is kept
  fresh, the character on screen first (Brett, 2026-10-23), and the server fetches at most every
  AUTO_MIN_AGE per character, however many people watch.

The menu bar is on every page, so `loader` reads the rows with its own short session (like
app/access.py); tests point it at their session.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import characters as chars
from app import conditions as cond
from app import access, config, vtt, web
from app.auth import current_user, is_dm, is_reviewer
from app.db import get_db
from app.models import BridgeIntent, CampaignCharacter, Character, CharacterSnapshot, User
from app.templating import templates

router = APIRouter()

SYNC_SECONDS = 150  # the page asks every 2.5 minutes…
AUTO_MIN_AGE = timedelta(seconds=110)  # …and the server fetches at most this often per character
MANUAL_MIN_AGE = timedelta(seconds=20)  # "Refresh now"
REACH = timedelta(seconds=90)  # a sheet heard by the bridge this recently can be reached (its extension pulls every 30 seconds)

# /characters/5 is Sheet, /characters/5/battle is Battle, /characters/5/plan is Plan
CHARACTER_PAGE = re.compile(r"^/characters/(\d+)(/battle|/plan)?/?$")
MODES = {"/battle": "battle", "/plan": "plan", None: "sheet"}
SUFFIX = {"battle": "/battle", "sheet": "", "plan": "/plan"}


def rows_from(db: Session) -> list[dict]:
    """Each campaign character: id, name, who plays it, its last D&D Beyond copy, and from that copy its
    portrait, classes and hit points (read straight from the stored summary, not the whole sheet); and with the D&D
    Beyond bridge on, whether its sheet can be reached now (`step`), whether it could be (`connects`), whether it's in a
    D&D Beyond game (`in_game`: its rolls can reach the Game Log), whether the DM's browser makes its changes now
    instead (`via`: its own sheet is closed, app/ddb_bridge.py `carried`) and how many changes wait to be made by hand."""
    from app import ddb_bridge

    campaign = web.campaign(db)
    if not campaign:
        return []
    bridge = config.DDB_BRIDGE and vtt.on(campaign, "ddb_bridge")
    dm_here = ddb_bridge.dm_here(campaign)
    by_hand: dict[int, int] = {}
    on_way: dict[int, list[dict]] = {}
    if bridge:
        waits_for_sheet = BridgeIntent.data["quiet"].astext == "true"  # (made by itself once its sheet is open: ddb_bridge._catch_up)
        by_hand = dict(db.execute(select(BridgeIntent.character_id, func.count())
                                  .where(BridgeIntent.state == "not_yet", func.coalesce(waits_for_sheet, False).is_(False))
                                  .group_by(BridgeIntent.character_id)).all())
        for cid, data in db.execute(select(BridgeIntent.character_id, BridgeIntent.data)
                                    .where(BridgeIntent.kind == "set", BridgeIntent.state.in_(("waiting", "sending")))
                                    .order_by(BridgeIntent.id)):
            on_way.setdefault(cid, []).append(data)
    reach = datetime.now(UTC) - REACH
    summary = CharacterSnapshot.summary
    q = (select(Character.id, Character.name, User.email, Character.ddb_id, Character.copy_of_id, Character.sheet_heard_at,
                CharacterSnapshot.fetched_at, CharacterSnapshot.status, CharacterSnapshot.error,
                summary["portrait"].astext, summary["classes"], summary["hit_points"]["current"].astext,
                summary["hit_points"]["max"].astext, Character.conditions, summary["conditions"], Character.concentration,
                CharacterSnapshot.raw["campaign"]["id"].astext, Character.ddb_campaign_id)
         .join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
         .outerjoin(User, Character.owner_id == User.id)
         .outerjoin(CharacterSnapshot, CharacterSnapshot.character_id == Character.id)
         .where(CampaignCharacter.campaign_id == campaign.id, CampaignCharacter.left_on.is_(None))
         .order_by(Character.name))
    return [{"id": cid, "name": name, "owner": (email or "").lower(), "linked": bool(ddb_id), "ddb_id": ddb_id, "fetched_at": fetched,
             "failed": status == "error", "error": error or "", "portrait": portrait or "",
             "classes": " / ".join(f"{k.get('name')} {k.get('level')}" for k in classes or [] if isinstance(k, dict)),
             "hp": f"{hp}/{hp_max} HP" if hp and hp_max else "",
             # (a test copy shares a real sheet, so the bridge never works on it: ddb_bridge.on_for)
             "step": bool(bridge and ddb_id and copy_of is None and heard and heard >= reach),
             "connects": bool(bridge and ddb_id and copy_of is None), "in_game": bool(bridge and ddb_id and copy_of is None and game),
             "via": bool(bridge and ddb_id and copy_of is None and not (heard and heard >= reach) and dm_here
                         and ddb_bridge.in_its_game(campaign, ddb_game)),
             "step_until": int((heard + REACH).timestamp()) if heard and bridge and ddb_id and copy_of is None else 0,
             "by_hand": by_hand.get(cid, 0) if bridge and copy_of is None else 0,
             # the menu bar's dots: what it's under now (D&D Beyond's with what's on its way and askdnd's own, as on Battle)
             "conditions": ["Concentration"] * bool(conc) + [x["name"] for x in cond.shown(own, cond.with_changes(on_sheet, on_way.get(cid, ())), bool(bridge and copy_of is None))]}
            for cid, name, email, ddb_id, copy_of, heard, fetched, status, error, portrait, classes, hp, hp_max, own, on_sheet, conc, game,
            ddb_game in db.execute(q)]


def _load_from_db() -> list[dict]:
    from app.db import SessionLocal

    with SessionLocal() as db:
        return rows_from(db)


loader: Callable[[], list[dict]] = _load_from_db


def table(user: dict | None, path: str = "", rows: list[dict] | None = None, focus_id: int | None = None,
          last_mode: str | None = None) -> dict:
    """What the menu bar needs: the characters (yours first), the one on screen, the mode, and the pill.
    `last_mode` is the mode this person used last (templating keeps it in their session)."""
    if not user:
        return {}
    if rows is None:
        try:
            rows = loader()
        except Exception:
            rows = []  # database unavailable: the menu bar still works without the table pieces
    email = (user.get("email") or "").lower()
    rows = sorted(({**r, "mine": bool(email) and r["owner"] == email} for r in rows), key=lambda r: not r["mine"])
    by_id = {r["id"]: r for r in rows}
    m = CHARACTER_PAGE.match(path or "")
    here = by_id.get(int(m.group(1))) if m else None
    mode = MODES[m.group(2)] if here else None
    # Your character: in a test campaign a test account plays several (manage_table.one_each), and its own is its first
    # (picks.my_character, by id), never the first by name (Nov 5: a seat opened Test Bard, not Vi)
    mine = min((r for r in rows if r["mine"]), key=lambda r: r["id"], default=None)
    # The pill answers for your own sheet wherever you are (Brett, Nov 3: on Roscoe's page it said "Roscoe Norell: through
    # the DM", read as Cathartic connecting through Roscoe); others' are in the Live window. Without one: the page's
    focus = by_id.get(focus_id) if focus_id else (here if here and here["mine"] else mine or here)  # (another of yours: its sheet)
    linked = [r for r in rows if r["linked"]]
    oldest = min(linked, key=lambda r: r["fetched_at"] or datetime.min.replace(tzinfo=UTC)) if linked else None
    pill = focus if focus and focus["linked"] else oldest
    connects = [r for r in rows if r.get("connects")]
    via = sum(bool(r.get("via")) for r in connects)
    try:
        here_campaign = access.current_campaign(user.get("email"))
    except Exception:
        here_campaign = None  # database unavailable, as for the rows
    return {"characters": rows, "mine": mine, "here": here, "focus": focus, "mode": mode,
            "connectable": len(connects), "connected": sum(bool(r.get("step")) for r in connects), "via": via,
            # The table is playing (the pill goes red, not grey, for a sheet that can't be reached): someone's sheet is
            # connected or the DM's browser is here. A fight running counts too (the pill asks fight_now() itself)
            "playing": any(r.get("step") or r.get("via") for r in connects),
            "dm": bool(here_campaign and is_dm(user, here_campaign["id"])),
            # Characters open in the mode you're in, else the one you used last, else Battle
            "suffix": SUFFIX[mode or (last_mode if last_mode in SUFFIX else None) or "battle"],
            "pill": pill, "party_pill": pill is not None and pill is not focus, "linked": linked,
            "every": SYNC_SECONDS}


def maybe_refresh(db: Session, ch: Character, min_age: timedelta) -> bool:
    """Fetch from D&D Beyond unless someone did in the last `min_age`. True if it fetched."""
    if not ch.ddb_id:
        return False
    snap = ch.snapshot
    last = snap.attempted_at if snap else None
    if last is not None and datetime.now(UTC) - last < min_age:
        return False
    chars.store(db, ch, chars.read_released(db, ch))  # (open pages ask often: never hold the database while D&D Beyond answers)
    db.commit()
    return True


def refresh_party(db: Session, user: dict, focus_id: int | None) -> None:
    """The character on screen (else your own) first, then everyone else linked in the campaign, each at
    most every AUTO_MIN_AGE."""
    tn = table(user, "", rows_from(db), focus_id)
    first = [tn["focus"]["id"]] if tn["focus"] and tn["focus"]["linked"] else []
    for i in first + [r["id"] for r in tn["linked"] if r["id"] not in first]:
        ch = db.get(Character, i)
        if ch is not None:
            maybe_refresh(db, ch, AUTO_MIN_AGE)


def pill(db: Session, user: dict, focus_id: int | None) -> str:
    """The pill's HTML on its own (the page's tick swaps it in): no page around it, so it brings the fight itself."""
    from app import fight

    here = access.current_campaign()
    return templates.get_template("_live_pill.html").render(
        tn=table(user, "", rows_from(db), focus_id),
        fight_now=lambda: fight.loader(here["id"], user.get("email")) if here else None)


def changes(db: Session, user: dict, rows: list[dict]) -> dict[int, list[dict]]:
    """Each character's changes not yet on D&D Beyond, for its player and the DM, with how each stands (ddb_bridge
    `progress`): the Live window lists them under the character, and one that didn't go through has Try again and Undo
    (Nov 3: they were only on a page nothing linked to; Bridge Review: the ones on their way are listed too)."""
    from app import ddb_bridge
    from app.hit_points import can_apply

    ids = [r["id"] for r in rows]
    out: dict[int, list[dict]] = {}
    if not ids:
        return out
    mine: dict[int, list[BridgeIntent]] = {}
    for it in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id.in_(ids), BridgeIntent.state.in_(ddb_bridge.OPEN))
                         .order_by(BridgeIntent.id)):
        mine.setdefault(it.character_id, []).append(it)
    for cid, its in mine.items():
        ch = db.get(Character, cid)
        if not can_apply(db, user, ch):
            continue
        ps = ddb_bridge.progress(db, ch, its)
        out[cid] = [{"id": it.id, "label": it.label, "error": it.error, "progress": ps[it.id]["state"], "says": ddb_bridge.says(ps[it.id])}
                    for it in its]
    return out


def panel(request: Request, db: Session, user: dict, focus_id: int | None, toast: str = "", ids: list[int] = ()):
    """The Live window: how each sheet is connected, refreshing."""
    from app import ddb_bridge

    tn = table(user, "", rows_from(db), focus_id)
    campaign = web.campaign(db)
    backup = ddb_bridge.backup_on(campaign)
    resp = templates.TemplateResponse(request, "_live_panel.html", {"changes": changes(db, user, tn["characters"]),
        "tn": tn, "reviewer": is_reviewer(user), "bridge": config.DDB_BRIDGE and vtt.on(campaign, "ddb_bridge"),
        "backup": backup, "dm_here": ddb_bridge.dm_here(campaign), "ddb_game": campaign.ddb_campaign_id if campaign else None,
        "made_through": ddb_bridge.made_through(db, campaign) if backup else []})
    if toast:
        resp.headers["HX-Trigger"] = json.dumps({"toast": toast, "liveRefreshed": {"ids": list(ids)}})
    return resp


@router.get("/live")
def live_panel(request: Request, c: int = 0, db: Session = Depends(get_db)):
    """The Live popover, loaded fresh each time it opens."""
    user = current_user(request)
    if not user:
        return HTMLResponse("", status_code=401)
    return panel(request, db, user, c or None)


@router.post("/live/sync")
def live_sync(request: Request, c: int = 0, db: Session = Depends(get_db)):
    """Every page's tick: keep the party fresh (the character on screen, else your own, first) and
    return the updated pill. What changed reaches the pages showing it through the live connection (app/realtime.py)."""
    user = current_user(request)
    if not user:
        return HTMLResponse("", status_code=401)
    refresh_party(db, user, c or None)
    return HTMLResponse(pill(db, user, c or None))


@router.post("/live/refresh/{character_id:int}")
def live_refresh_one(request: Request, character_id: int, db: Session = Depends(get_db)):
    """"Refresh <character> now": anyone at the table, at most every MANUAL_MIN_AGE."""
    user = current_user(request)
    if not user:
        return HTMLResponse("", status_code=401)
    ch = db.get(Character, character_id)
    if ch is None or not ch.ddb_id:
        return HTMLResponse("", status_code=404)
    if all(c["id"] != ch.campaign_id for c in access.campaigns_for(user.get("email"))):  # (its table's: tests/test_refusals.py)
        return HTMLResponse("", status_code=403)
    name = ch.name
    if not maybe_refresh(db, ch, MANUAL_MIN_AGE):
        msg = f"{name} was updated a moment ago"
    elif ch.snapshot.status == "ok":
        msg = f"Updated {name} from D&D Beyond"
    else:
        msg = f"Couldn't update {name}; showing the last good copy"
    return panel(request, db, user, character_id, msg, [character_id])


@router.post("/live/refresh-all")
def live_refresh_all(request: Request, c: int = 0, db: Session = Depends(get_db)):
    """"Refresh everyone": reviewers only (D&D Beyond is asked once per linked character)."""
    user = current_user(request)
    if not is_reviewer(user):
        return web.forbidden(request)
    campaign = web.campaign(db)
    ok, failed = chars.refresh_all(db, campaign.id) if campaign else (0, [])
    db.commit()
    msg = f"Updated {ok} from D&D Beyond" + (f"; couldn't update {', '.join(failed)}" if failed else "")
    return panel(request, db, user, c or None, msg, [r["id"] for r in rows_from(db)])
