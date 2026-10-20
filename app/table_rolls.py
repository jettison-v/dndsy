"""Table rolls: dice rolled on the server while Game Mode is on, shared with the table.

The page's roll buttons carry the same data as private rolls (data-roll, data-label,
data-mod, data-dmg, data-adv; app/templates/_char.html). With Game Mode on, app.js posts
that data here and the server rolls the dice, so nobody's browser decides a result.

Who sees a roll (Brett, 2026-10-20):
- "table": everyone.
- "dm": the roller and the DM see the number; everyone else only "<character> rolled for
  the DM" (no label, no dice, no total ever leave the server for them).
- "self": the roller only (not even the DM).

Only a character's own player rolls for it here (like stars and notes); anyone else's
click stays a private roll in their browser. Damage after an attack is rolled from the
attack's own row: its dice, doubled when the kept d20 was a natural 20.
"""

import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app import picks, web
from app.auth import current_user, is_dm
from app.db import get_db
from app.models import Character, CharacterSnapshot, TableRoll
from app.templating import templates

router = APIRouter()

D20_KINDS = ("save", "check", "attack")
KINDS = (*D20_KINDS, "damage")
MODES = ("normal", "adv", "dis")
VISIBILITY = ("table", "dm", "self")
LOG_SIZE = 30
MAX_MOD = 40
DICE = re.compile(r"^(\d{1,2})d(\d{1,3})(?:([+-])(\d{1,2}))?$")


def die(sides: int) -> int:
    return secrets.randbelow(sides) + 1


def parse_dice(expr: str) -> tuple[int, int, int] | None:
    """'2d6+3' -> (2, 6, 3). None unless it's a sensible roll (1–20 dice of 2–100 sides)."""
    m = DICE.match((expr or "").replace(" ", "").replace("−", "-"))
    if not m:
        return None
    count, sides = int(m.group(1)), int(m.group(2))
    bonus = (-1 if m.group(3) == "-" else 1) * int(m.group(4) or 0)
    if not (1 <= count <= 20 and 2 <= sides <= 100):
        return None
    return count, sides, bonus


def signed(n: int) -> str:
    return f"+{n}" if n >= 0 else f"−{abs(n)}"


def roll_d20(mod: int, mode: str, roll=None) -> dict:
    """A d20 test: two dice on Advantage or Disadvantage, keeping the higher or lower."""
    roll = roll or die
    dice = [roll(20)] if mode == "normal" else [roll(20), roll(20)]
    kept = max(dice) if mode == "adv" else min(dice) if mode == "dis" else dice[0]
    return {"dice": dice, "kept": kept, "modifier": mod, "total": kept + mod, "formula": f"d20{signed(mod)}"}


def roll_damage(expr: str, crit: bool = False, roll=None) -> dict | None:
    """Damage or healing dice; a critical hit rolls the dice twice (not the bonus)."""
    roll = roll or die
    parsed = parse_dice(expr)
    if not parsed:
        return None
    count, sides, bonus = parsed
    count = count * 2 if crit else count
    dice = [roll(sides) for _ in range(count)]
    formula = f"{count}d{sides}" + (signed(bonus) if bonus else "")
    return {"dice": dice, "kept": None, "modifier": bonus, "total": max(sum(dice) + bonus, 0), "formula": formula}


def _int(s: str) -> int | None:
    try:
        return int(str(s or "0").replace("−", "-").strip() or 0)
    except ValueError:
        return None


# ------------------------------------------------------------------ who sees what

def shown(roll: TableRoll, viewer_id: int | None, viewer_is_dm: bool) -> str | None:
    """'full' (the number), 'hidden' (only that a roll happened) or None (not at all)."""
    mine = viewer_id is not None and roll.user_id == viewer_id
    if roll.visibility == "table" or mine:
        return "full"
    if roll.visibility == "dm":
        return "full" if viewer_is_dm else "hidden"
    return None  # "self": the roller only


def _visible_query(campaign_id: int, viewer_id: int | None):
    """Rows anyone could be shown something about: others' just-me rolls never leave the database."""
    mine = TableRoll.user_id == viewer_id if viewer_id is not None else False
    return select(TableRoll).where(TableRoll.campaign_id == campaign_id,
                                   or_(TableRoll.visibility.in_(("table", "dm")), mine))


def _ago(when: datetime | None) -> str:
    if not when:
        return ""
    s = max((datetime.now(UTC) - when).total_seconds(), 0)
    if s < 10:
        return "now"
    if s < 60:
        return f"{int(s)} s"
    if s < 3600:
        return f"{int(s // 60)} min"
    if s < 86400:
        return f"{int(s // 3600)} h"
    return when.strftime("%b %-d")


def entries(db: Session, rows: list[TableRoll], viewer_id: int | None, viewer_is_dm: bool) -> list[dict]:
    """What a viewer's browser gets for each roll (newest first). A hidden roll carries only who
    and when. Your newest roll, if it's an attack that didn't roll a 1, offers its damage."""
    ids = {r.character_id for r in rows if r.character_id}
    names, pics = {}, {}
    if ids:
        for ch in db.scalars(select(Character).where(Character.id.in_(ids))):
            names[ch.id] = ch.entity.name
        pics = dict(db.execute(select(CharacterSnapshot.character_id, CharacterSnapshot.summary["portrait"].astext)
                               .where(CharacterSnapshot.character_id.in_(ids))).all())
    out, newest_mine = [], True  # rows come newest first; only your newest roll offers damage
    for r in rows:
        how = shown(r, viewer_id, viewer_is_dm)
        if how is None:
            continue
        name = names.get(r.character_id, "Someone")
        e = {"id": r.id, "character_id": r.character_id or 0, "name": name, "initial": name[:1].upper(),
             "portrait": pics.get(r.character_id) or "", "hue": (r.character_id or 0) % 6,
             "mine": viewer_id is not None and r.user_id == viewer_id, "to": r.visibility,
             "at": r.created_at.isoformat() if r.created_at else "", "ago": _ago(r.created_at), "hidden": how == "hidden"}
        if how == "full":
            nat = r.kept if r.kind in D20_KINDS and r.kept in (1, 20) else None
            e |= {"label": r.label, "kind": r.kind, "total": r.total, "dice": list(r.dice), "kept": r.kept,
                  "kept_at": r.dice.index(r.kept) if r.kept in r.dice and len(r.dice) > 1 else -1,
                  "modifier": r.modifier, "mode": r.mode, "formula": r.formula, "crit": r.crit, "nat": nat,
                  "short": r.label.split()[0][:5] if r.kind != "damage" else "Dmg",
                  "damage": r.damage if e["mine"] and newest_mine and r.kind == "attack" and r.damage and r.kept != 1 else ""}
        if e["mine"]:
            newest_mine = False
        out.append(e)
    return out


def _viewer(db: Session, user: dict) -> tuple[int | None, bool]:
    me = picks.user_row(db, user)
    return (me.id if me else None), is_dm(user)


def render(request: Request, items: list[dict]) -> str:
    return templates.get_template("_roll_items.html").render(rolls=items, request=request)


# ------------------------------------------------------------------ routes

@router.get("/rolls")
def roll_log(request: Request, since: int = -1, db: Session = Depends(get_db)):
    """The table's rolls this viewer may see, newest first: the last LOG_SIZE (with a line when
    there are none), or only those after `since` (Game Mode polls every few seconds; nothing
    new is a 204, which htmx skips)."""
    user = current_user(request)
    if not user:
        return HTMLResponse("", status_code=401)
    campaign = web.campaign(db)
    if not campaign:
        return Response(status_code=204)
    viewer_id, dm = _viewer(db, user)
    q = _visible_query(campaign.id, viewer_id)
    if since >= 0:
        q = q.where(TableRoll.id > since)
    rows = list(db.scalars(q.order_by(TableRoll.id.desc()).limit(LOG_SIZE)))
    if not rows and since >= 0:
        return Response(status_code=204)
    return HTMLResponse(render(request, entries(db, rows, viewer_id, dm)))


def _error(text: str, status: int = 400):
    return JSONResponse({"error": text}, status_code=status)


@router.post("/rolls")
def make_roll(request: Request, character: int = Form(0), kind: str = Form(""), label: str = Form(""),
              mod: str = Form(""), dmg: str = Form(""), adv: str = Form(""), mode: str = Form("normal"),
              to: str = Form("table"), after: int = Form(0), db: Session = Depends(get_db)):
    """Roll on the server for the signed-in player's own character and return the result
    (and the log entry's HTML). `after` is an attack's id: roll its damage."""
    user = current_user(request)
    if not user:
        return _error("Sign in to roll.", 401)
    campaign = web.campaign(db)
    me = picks.user_row(db, user)
    if not campaign or not me:
        return _error("Sign in to roll.", 401)
    if after:
        attack = db.get(TableRoll, after)
        if not attack or attack.campaign_id != campaign.id or attack.user_id != me.id or attack.kind != "attack" or not attack.damage:
            return _error("That attack isn't yours to roll damage for.", 403)
        ch = attack.character
        crit = attack.kept == 20
        result = roll_damage(attack.damage, crit)
        kind, label, mode, to = "damage", attack.label, "normal", attack.visibility
    else:
        ch = db.get(Character, character) if character else None
        if not ch or ch.entity.campaign_id != campaign.id:
            return _error("That character isn't in the campaign.", 404)
        if not picks.can_edit(db, user, ch):
            return _error(f"Only {ch.entity.name}'s player rolls for {ch.entity.name} at the table.", 403)
        crit = False
        label = " ".join(label.split())[:120]
        if kind not in KINDS or not label or mode not in MODES or to not in VISIBILITY:
            return _error("That roll is missing something.")
        if kind == "damage":
            result = roll_damage(dmg)
        else:
            m = _int(mod)
            if m is None or abs(m) > MAX_MOD:
                return _error("That bonus doesn't look right.")
            if mode == "normal" and adv:
                mode = "adv"  # Advantage that always applies (data-adv)
            result = roll_d20(m, mode)
        if result is None:
            return _error("Those dice don't look right.")
    damage = dmg.replace(" ", "").replace("\u2212", "-") if kind == "attack" and parse_dice(dmg) else ""
    row = TableRoll(campaign_id=campaign.id, character_id=ch.id if ch else None, user_id=me.id, label=label, kind=kind,
                    mode=mode if kind in D20_KINDS else "normal", visibility=to, crit=crit, damage=damage, **result)
    db.add(row)
    db.commit()
    db.refresh(row)
    entry = entries(db, [row], me.id, is_dm(user))[0]
    return JSONResponse({"roll": {k: entry[k] for k in ("id", "name", "label", "kind", "total", "dice", "kept", "kept_at", "modifier",
                                                       "mode", "formula", "crit", "nat", "to", "damage")},
                         "html": render(request, [entry])})
