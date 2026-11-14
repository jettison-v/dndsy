"""Healing given to another player's character (Brett chose A on Healing and Costs, Nov 14,
docs/mockups/healing-and-costs/): the one healed is asked, with a corner card that stays until they answer.

A heal with a named target (Lay on Hands for someone, app/feature_use.py; a potion given, app/item_use.py) is a Table
rolls entry of kind "heal" whose `spec` says whom it's `for`. A player changes only their own sheet (the standing rule),
so it waits for that character's player: every askdnd page they have open shows a green card (app.js "healing for
you") with Apply, which heals through the hit points window's own route, and Not now, which hides it until the next
page. Table rolls marks the entry Waiting for them (`hit_points.apply_info`), and the DM sees what still waits under
Needs you (`manage.needs`) and can apply it from Table rolls. An entry the healer undid (total 0) waits for no one.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import ddb_bridge, picks, web
from app.auth import current_user
from app.db import get_db
from app.models import Character, TableRoll

router = APIRouter()

KEEP = timedelta(days=2)  # (a heal no one answered in two days has been settled at the table some other way)


def for_of(roll: TableRoll) -> int | None:
    """Whom a heal is for, when it was given to someone."""
    v = (roll.spec or {}).get("for") if isinstance(roll.spec, dict) else None
    return int(v) if isinstance(v, int) or (isinstance(v, str) and v.isdigit()) else None


def open_heals(db: Session, campaign_id: int) -> list[tuple[TableRoll, Character]]:
    """Every heal given to someone in the campaign that they haven't applied yet, oldest first."""
    from app.hit_points import applied

    since = datetime.now(UTC) - KEEP
    rows = db.scalars(select(TableRoll).where(TableRoll.campaign_id == campaign_id, TableRoll.kind == "heal",
                                              TableRoll.parent_id.is_(None), TableRoll.created_at >= since)
                      .order_by(TableRoll.id)).all()
    out = []
    for r in rows:
        tid = for_of(r)
        if not tid or not r.total:
            continue
        tgt = db.get(Character, tid)
        if tgt and tid not in applied(db, r):
            out.append((r, tgt))
    return out


def waiting(db: Session, user: dict | None, campaign_id: int) -> list[dict]:
    """The heals waiting for this person: for characters they play, never someone else's (the DM's are on Needs you)."""
    if not user:
        return []
    from app import characters as chars

    out = []
    for r, tgt in open_heals(db, campaign_id):
        if not picks.can_edit(db, user, tgt):
            continue
        hp = (ddb_bridge.as_shown(db, tgt, chars.character_summary(tgt)) or {}).get("hit_points") or {}  # (a change on its way counts)
        now, top = hp.get("current"), hp.get("max")
        out.append({"id": r.id, "for": tgt.id, "name": tgt.name, "from": r.character.name if r.character else "Someone",
                    "label": r.label, "amount": r.total,
                    "hp": f"{now} to {min(top, now + r.total)} of {top}" if now is not None and top else ""})
    return out


@router.get("/heals/waiting")
def waiting_route(request: Request, db: Session = Depends(get_db)):
    """What the healing card shows on this person's pages (app.js "healing for you")."""
    campaign = web.campaign(db)
    return JSONResponse({"heals": waiting(db, current_user(request), campaign.id) if campaign else []})
