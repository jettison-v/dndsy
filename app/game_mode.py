"""Game Mode, one switch for the whole table (decided 2026-10-28, docs/mockups/game-mode-and-bridge.html).

Game Mode means "we're playing": everyone's rolls are shared in Table rolls, askdnd reads every sheet from D&D Beyond
every few minutes, and the D&D Beyond bridge stays awake however quiet the table is. It used to be a switch kept in
each browser, so a player who forgot it rolled privately without knowing; now it's the campaign's:

- **Anyone at the table** (anyone with a role in the campaign, or an admin) starts it or ends it, from the Live window
  (`_live_panel.html`); ending asks first. It lasts the bridge's Game Mode timer (6 hours unless an admin changed it,
  Manage › askdnd › D&D Beyond bridge) or until someone ends it; Keep going starts the timer again. Closing askdnd
  doesn't end it.
- **Every page draws it** (base.html: `body.gm-on`, `data-game-until`), and a change reaches every open page through
  the live connection like any other (realtime.TABLE_SEES: the campaign's `game_until`), where app.js shows the page's
  new copy the one way (`showInPlace`).
- **Between games the bridge keeps its own rules** (app/ddb_bridge.py: awake while anyone uses askdnd or a sheet), so
  nothing a player does then waits for Game Mode.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app import access, picks, web
from app.auth import current_user
from app.db import get_db
from app.models import Campaign, User

router = APIRouter()
OFF = {"on": False, "until": None, "by": ""}


def _load_from_db(campaign_id: int) -> dict:
    from app.db import SessionLocal

    with SessionLocal() as db:
        return state(db, db.get(Campaign, campaign_id))


# Every page draws Game Mode (base.html), so its read has its own short session, like the menu bar's (app/live.py);
# tests point it at their session
loader: Callable[[int], dict] = _load_from_db


def state(db: Session, campaign: Campaign | None) -> dict:
    """{"on", "until", "by", "warn"}: whether Game Mode is on for this campaign, until when, who started it, and how many
    seconds before the end every page warns (with Keep going)."""
    now = datetime.now(UTC)
    until = campaign.game_until if campaign is not None else None
    if not until or until <= now:
        return dict(OFF)
    from app import ddb_bridge  # (its timers: how long before the end the table is warned)

    who = db.get(User, campaign.game_by_id) if campaign.game_by_id else None
    return {"on": True, "until": until, "by": (who.name or who.email) if who else "", "warn": ddb_bridge.timers(db)["warn"]}


def can_switch(user: dict | None, campaign: Campaign | None) -> bool:
    """Anyone at the table: a role in this campaign, or an admin."""
    email = (user or {}).get("email")
    return bool(campaign and email) and (access.role(email, campaign.id) is not None or access.level(email) == access.ADMIN)


def start(db: Session, campaign: Campaign, user: dict) -> None:
    """On for the table for the Game Mode timer (or Keep going: the timer starts again)."""
    from app import ddb_bridge  # (it reads Game Mode's timer and wakes for the game)

    me = picks.user_row(db, user)
    campaign.game_until = datetime.now(UTC) + timedelta(seconds=ddb_bridge.timers(db)["game"])
    campaign.game_by_id = me.id if me else None
    ddb_bridge.game(db, True)


def end(db: Session, campaign: Campaign) -> None:
    from app import ddb_bridge

    campaign.game_until, campaign.game_by_id = None, None
    ddb_bridge.game(db, False)


@router.post("/live/game")
def switch(request: Request, on: str = Form(""), c: int = 0, db: Session = Depends(get_db)):
    """Start (or Keep going) or end Game Mode for the table; answers with the Live window again."""
    from app.live import panel

    user = current_user(request)
    campaign = web.campaign(db)
    if not can_switch(user, campaign):
        return HTMLResponse("", status_code=403)
    if on == "1":
        start(db, campaign, user)
    else:
        end(db, campaign)
    db.commit()
    return panel(request, db, user, c or None)
