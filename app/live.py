"""The menu bar's table pieces: the character switcher and the Live control.

- The switcher ("Cole ▾") lists the campaign's characters, your own first, and opens the
  same mode (Battle / Sheet / Plan) for the one you pick.
- The Live pill says when the D&D Beyond copy was last updated: the character on screen,
  else your own, else the party's oldest copy. Its popover holds Game Mode (a switch per
  browser, kept in localStorage by app.js), each character's last refresh and failures,
  "Refresh <character> now" (anyone signed in, throttled) and "Refresh everyone"
  (reviewers only).
- While Game Mode is on, app.js asks every couple of minutes: on Battle it swaps in the updated
  page body (character_pages.game_mode_sync), elsewhere it calls /live/sync and swaps the pill.
  The server fetches at most every AUTO_MIN_AGE per character, however many people watch.

The menu bar is on every page, so `loader` reads the rows with its own short session (like
app/access.py); tests point it at their session.
"""

import json
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import characters as chars
from app import web
from app.auth import current_user, is_reviewer
from app.db import get_db
from app.models import CampaignCharacter, Character, CharacterSnapshot, User
from app.templating import templates

router = APIRouter()

GAME_MODE_SECONDS = 150  # the page asks every 2.5 minutes…
AUTO_MIN_AGE = timedelta(seconds=110)  # …and the server fetches at most this often per character
MANUAL_MIN_AGE = timedelta(seconds=20)  # "Refresh now"

# /characters/5 is Sheet, /characters/5/battle is Battle, /characters/5/plan is Plan
CHARACTER_PAGE = re.compile(r"^/characters/(\d+)(/battle|/plan)?/?$")
MODES = {"/battle": "battle", "/plan": "plan", None: "sheet"}
SUFFIX = {"battle": "/battle", "sheet": "", "plan": "/plan"}


def rows_from(db: Session) -> list[dict]:
    """Each campaign character: id, name, who plays it, and its last D&D Beyond copy."""
    campaign = web.campaign(db)
    if not campaign:
        return []
    q = (select(Character.id, Character.name, User.email, Character.ddb_id,
                CharacterSnapshot.fetched_at, CharacterSnapshot.status, CharacterSnapshot.error)
         .join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
         .outerjoin(User, Character.owner_id == User.id)
         .outerjoin(CharacterSnapshot, CharacterSnapshot.character_id == Character.id)
         .where(CampaignCharacter.campaign_id == campaign.id, CampaignCharacter.left_on.is_(None))
         .order_by(Character.name))
    return [{"id": cid, "name": name, "owner": (email or "").lower(), "linked": bool(ddb_id), "fetched_at": fetched,
             "failed": status == "error", "error": error or ""}
            for cid, name, email, ddb_id, fetched, status, error in db.execute(q)]


def _load_from_db() -> list[dict]:
    from app.db import SessionLocal

    with SessionLocal() as db:
        return rows_from(db)


loader: Callable[[], list[dict]] = _load_from_db


def table(user: dict | None, path: str = "", rows: list[dict] | None = None, focus_id: int | None = None) -> dict:
    """What the menu bar needs: the characters (yours first), the one on screen, the mode, and the pill."""
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
    mine = next((r for r in rows if r["mine"]), None)
    focus = by_id.get(focus_id) if focus_id else (here or mine)
    linked = [r for r in rows if r["linked"]]
    oldest = min(linked, key=lambda r: r["fetched_at"] or datetime.min.replace(tzinfo=UTC)) if linked else None
    pill = focus if focus and focus["linked"] else oldest
    return {"characters": rows, "mine": mine, "here": here, "focus": focus, "mode": mode,
            "suffix": SUFFIX[mode or "battle"],  # the switcher keeps the mode; from elsewhere it opens Battle
            "pill": pill, "party_pill": pill is not None and pill is not focus, "linked": linked,
            "every": GAME_MODE_SECONDS}


def maybe_refresh(db: Session, ch: Character, min_age: timedelta) -> bool:
    """Fetch from D&D Beyond unless someone did in the last `min_age`. True if it fetched."""
    if not ch.ddb_id:
        return False
    snap = ch.snapshot
    last = snap.attempted_at if snap else None
    if last is not None and datetime.now(UTC) - last < min_age:
        return False
    chars.refresh(db, ch)
    db.commit()
    return True


def pill(db: Session, user: dict, focus_id: int | None) -> str:
    """The pill's HTML on its own (Game Mode's tick away from Battle swaps it in)."""
    return templates.get_template("_live_pill.html").render(tn=table(user, "", rows_from(db), focus_id))


def _panel(request: Request, db: Session, user: dict, focus_id: int | None, toast: str = "", ids: list[int] = ()):
    tn = table(user, "", rows_from(db), focus_id)
    resp = templates.TemplateResponse(request, "_live_panel.html", {"tn": tn, "reviewer": is_reviewer(user)})
    if toast:
        resp.headers["HX-Trigger"] = json.dumps({"toast": toast, "liveRefreshed": {"ids": list(ids)}})
    return resp


@router.get("/live")
def live_panel(request: Request, c: int = 0, db: Session = Depends(get_db)):
    """The Live popover, loaded fresh each time it opens."""
    user = current_user(request)
    if not user:
        return HTMLResponse("", status_code=401)
    return _panel(request, db, user, c or None)


@router.post("/live/sync")
def live_sync(request: Request, c: int = 0, db: Session = Depends(get_db)):
    """Game Mode away from Battle: keep the character on screen fresh (else your own, else
    everyone's) and return the updated pill."""
    user = current_user(request)
    if not user:
        return HTMLResponse("", status_code=401)
    tn = table(user, "", rows_from(db), c or None)
    ids = [tn["focus"]["id"]] if tn["focus"] else [r["id"] for r in tn["linked"]]
    for ch in filter(None, (db.get(Character, i) for i in ids)):
        maybe_refresh(db, ch, AUTO_MIN_AGE)
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
    name = ch.name
    if not maybe_refresh(db, ch, MANUAL_MIN_AGE):
        msg = f"{name} was updated a moment ago"
    elif ch.snapshot.status == "ok":
        msg = f"Updated {name} from D&D Beyond"
    else:
        msg = f"Couldn't update {name}; showing the last good copy"
    return _panel(request, db, user, character_id, msg, [character_id])


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
    return _panel(request, db, user, c or None, msg, [r["id"] for r in rows_from(db)])
