"""Initiative from askdnd (Labs piece "initiative"; Brett, Nov 4: docs/mockups/initiative/, DECISIONS).

The table's way, kept: the DM adds the tokens in D&D Beyond's VTT, everyone rolls their own Initiative before Start
Combat (in askdnd now, their creatures' too), and after it the order is the DM's, changed by dragging a row in askdnd
(Party's Rows, askdnd's table) or typing in the VTT. Once askdnd's own VTT runs, none of this is sent anywhere.

How a number reaches D&D Beyond's VTT (captured on the Mac Mini, Nov 4):

- **A character's own roll** goes through the Game Log, as a roll from the sheet does (app/gamelog.py): the DM's open
  VTT turns it into the number. It's also queued here, so it lands when the player's sheet isn't open.
- **Everything else** (a familiar's own roll, a Homunculus put right after its master, the DM's drag) is queued on the
  fight (`Campaign.fight["sets"]`) for the DM's open VTT page to make (extension 0.12.0, vtt-page.js): it asks every
  `TICK` seconds (`POST /bridge/vtt/<game>`, app/ddb_bridge.py) and sends D&D Beyond's own UPDATE_INITIATIVE on its
  game connection. Only the DM's (or an admin's) page is given any: in D&D Beyond only the DM changes the order.
- A number is **made** once the VTT's order shows it (the next report, app/fight.py `heard`); until then the rows show
  it, marked on its way. One the VTT hasn't shown after `GIVE_UP` is dropped and the VTT's own number shows again.

The order's entries carry where the VTT keeps each (`group`, `gkey`: its group in the combat sidebar and its key there),
which only extension 0.12.0 reports: without them nothing can be set.
"""

import copy
import json
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Campaign, Character

TICK = 3  # seconds between a DM's open VTT page asking for numbers to set
IDLE = 60  # anyone else's, or no fight
RESEND = timedelta(seconds=8)
GIVE_UP = timedelta(seconds=90)
HERE = timedelta(seconds=30)  # the DM's VTT page asked this recently: it's open


def on(campaign: Campaign | None) -> bool:
    """Initiative from askdnd is on for the campaign (Labs, with Sync with D&D Beyond)."""
    from app import vtt

    return bool(campaign) and vtt.on(campaign, "initiative") and vtt.on(campaign, "ddb_bridge")


def num(n):
    """A number as the VTT keeps it: 14, 13.5."""
    if n is None:
        return None
    n = round(float(n), 2)
    return int(n) if n.is_integer() else n


def shown(n) -> str:
    """A number as a person reads it."""
    return "—" if n is None else str(num(n))


def _now() -> datetime:
    return datetime.now(UTC)


def _at(s) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except (TypeError, ValueError):
        return None


def sortable(order: list[dict]) -> None:
    """Higher first, as the VTT orders them (entries without a number last; its own tie-breaks aren't known here)."""
    order.sort(key=lambda x: -(x["initiative"]) if isinstance(x.get("initiative"), (int, float)) else float("inf"))


def want(f: dict, key: str, initiative) -> bool:
    """Ask for the VTT's entry `key` to be `initiative` (the fight is held: fight.lock). Shown at once, marked on its
    way. False: the VTT doesn't say where it keeps that entry (an extension before 0.12.0), or it's that already."""
    entry = next((x for x in f.get("order") or [] if x.get("key") == key), None)
    if not entry or not entry.get("group") or not entry.get("gkey"):
        return False
    initiative, sets = num(initiative), f.get("sets") or []
    old = next((s for s in sets if s["key"] == key), None)
    vtt_has = old["from"] if old else entry.get("initiative")  # (what the VTT's own order says)
    if not old and vtt_has == initiative:
        return False
    f["sets"] = [s for s in sets if s["key"] != key]
    if vtt_has != initiative:  # (asked back to what the VTT has, as Undo does: nothing to send)
        f["sets"].append({"id": secrets.token_hex(4), "key": key, "group": entry["group"], "gkey": entry["gkey"],
                          "initiative": initiative, "from": vtt_has, "at": _now().isoformat()})
    entry["initiative"], entry["pending"] = initiative, vtt_has != initiative
    sortable(f["order"])
    return True


def overlay(now: dict, prev: dict | None) -> None:
    """The VTT's order just heard (`now`), with what askdnd asked for and the VTT doesn't show yet: kept, shown as on its
    way. One the VTT shows is made; one it hasn't after GIVE_UP is dropped."""
    keep, by_key = [], {x["key"]: x for x in now.get("order") or []}
    for s in (prev or {}).get("sets") or []:
        entry = by_key.get(s["key"])
        if not entry or entry.get("initiative") == s["initiative"]:
            continue
        if (_at(s["at"]) or _now()) + GIVE_UP < _now():
            continue
        entry["initiative"], entry["pending"] = s["initiative"], True
        keep.append(s)
    now["sets"] = keep
    if keep:
        sortable(now["order"])


_sent: dict[str, datetime] = {}  # when each was last handed to a VTT page (here, not on the fight: saving the fight redraws every page)


def due(f: dict | None) -> list[dict]:
    """What the DM's VTT page should send now (each again after RESEND until the VTT shows it): D&D Beyond's own words
    for it, {group, key, initiative}, with askdnd's id. Sending one twice does no harm."""
    out, now = [], _now()
    for s in (f or {}).get("sets") or []:
        if (sent := _sent.get(s["id"])) and sent + RESEND > now:
            continue
        _sent[s["id"]] = now
        out.append({"id": s["id"], "group": s["group"], "key": s["gkey"], "initiative": s["initiative"]})
    for k in [k for k, at in _sent.items() if at + GIVE_UP < now]:
        del _sent[k]
    return out


def dm_here(campaign: Campaign) -> bool:
    """The DM's VTT page asked lately (extension 0.12.0): numbers reach the VTT now."""
    return bool(campaign.vtt_heard_at and campaign.vtt_heard_at + HERE > _now())


# ---- Creatures (Your creatures): a familiar rolls its own; one that acts right after its master follows it

def follow_masters(db: Session, campaign: Campaign, f: dict) -> None:
    """Each creature that takes its turn right after its master's (a Homunculus Servant, a Steel Defender), where the VTT
    has its own token: just below its master's number (13.5 after 14), so it goes right after it."""
    from app import fight

    here = fight.creatures_here(db, campaign)
    if not here:
        return
    masters = {x["character"]: x.get("initiative") for x in f.get("order") or [] if x.get("character")}
    for key, h in fight.matched(f.get("order") or [], here).items():
        m = masters.get(h["master"].id)
        if h["k"]["own_initiative"] or not isinstance(m, (int, float)):
            continue
        target = num(m - 0.5)
        entry = next(x for x in f["order"] if x["key"] == key)
        if entry.get("initiative") != target and not any(s["key"] == key for s in f.get("sets") or []):
            want(f, key, target)


def rolled(db: Session, campaign: Campaign, ch: Character, creature: str, total) -> bool:
    """An Initiative roll made in askdnd, before Start Combat: the number for that token in the VTT's sidebar (the
    character's own; or its creature `creature`'s token, by name). True when one was asked for."""
    from app import fight

    if not on(campaign):
        return False
    fight.lock(db, campaign)
    f = copy.deepcopy(campaign.fight)  # (changed whole and saved: a change inside the saved one isn't seen)
    if not f or not f.get("waiting"):
        return False
    if creature:
        found = fight.matched(f["order"], [h for h in fight.creatures_here(db, campaign)
                                           if h["master"].id == ch.id and h["k"]["name"] == creature])
        key = next(iter(found), None)
    else:
        key = next((x["key"] for x in f["order"] if x.get("character") == ch.id), None)
    if not key or not want(f, key, total):
        return False
    follow_masters(db, campaign, f)
    campaign.fight = f
    db.flush()  # (the next one reads the fight again: fight.lock)
    return True


def familiars(db: Session, campaign: Campaign, ch: Character) -> list[tuple[str, int]]:
    """The character's creatures that are here and roll their own Initiative (a familiar), with its modifier: one press
    of the character's Initiative rolls theirs too (Brett, Nov 4), each its own roll as the rules have it."""
    from app import fight

    if not on(campaign):
        return []
    out = []
    for h in fight.creatures_here(db, campaign):
        k = h["k"]
        if h["master"].id == ch.id and k["own_initiative"]:
            try:
                out.append((k["name"], int(str(k["initiative"]).replace("−", "-"))))
            except ValueError:
                out.append((k["name"], 0))
    return out


def note(campaign: Campaign | None, ch: Character, mine: list[dict], creature: dict | None = None) -> str:
    """What the Initiative roll window says (Initiative in askdnd, boards 2 and 4): after Start Combat a roll doesn't
    change the order; before it, a character's Initiative rolls its familiars' too."""
    from app import creatures, fight

    if not on(campaign):
        return ""
    f = fight.shown(campaign, True)
    if f and not f.get("waiting"):
        return "Combat has started, so this won't change the order. The DM changes it."
    if creature:
        return ""
    pets = [c["name"] for c in mine if c.get("group_id") == creatures.FAMILIAR and creatures.where(ch, c) == "here"]
    return f"Rolls {' and '.join(pets)}'s too, each its own roll." if pets else ""


# ---- The DM's drag (board 5): the number a row gets where it's dropped

def _follows(x: dict) -> bool:
    c = x.get("creature")
    return bool(c and not c.get("own"))


def _groups(order: list[dict]) -> list[list[dict]]:
    """Each fighter with the creatures that act right after it."""
    gs: list[list[dict]] = []
    for x in order:
        if _follows(x) and gs and gs[-1][0].get("character") == x["creature"]["master"]:
            gs[-1].append(x)
        else:
            gs.append([x])
    return gs


def _low(g: list[dict]):
    ns = [x["initiative"] for x in g if isinstance(x.get("initiative"), (int, float))]
    return min(ns) if ns else None


def plan(order: list[dict], key: str, slot: int) -> dict | None:
    """Where the fighter `key` lands when dropped at `slot` (a gap between fighters, 0 the top; its creatures that act
    right after it move with it): {"initiative": its number, "moves": {VTT key: number} for everyone that changes}.
    A whole number between its new neighbours when there's room (between 15 and 12, 13), else half way (between 12 and
    11, 11.5); between two that share a number, the one below drops by a half and it goes between. None: no move."""
    gs = _groups(order)
    frm = next((i for i, g in enumerate(gs) if g[0]["key"] == key), None)
    if frm is None or slot in (frm, frm + 1) or not 0 <= slot <= len(gs):
        return None
    rest = [g for i, g in enumerate(gs) if i != frm]
    k = slot - 1 if slot > frm else slot
    prev, nxt = (rest[k - 1] if k > 0 else None), (rest[k] if k < len(rest) else None)
    hi, lo = (_low(prev) if prev else None), (nxt[0].get("initiative") if nxt else None)
    lo = lo if isinstance(lo, (int, float)) else None
    moves: dict[str, float] = {}
    if hi is None and lo is None:
        return None
    if hi is None:
        ini = int(lo) + 1
    elif lo is None:
        ini = -(-hi // 1) - 1  # (the whole number below)
    else:
        if hi == lo:  # between two that share a number: the one below (and any more at it) drops by a half
            for g in rest[k:]:
                if g[0].get("initiative") != hi:
                    break
                for x in g:
                    if isinstance(x.get("initiative"), (int, float)):
                        moves[x["key"]] = num(x["initiative"] - 0.5)
            lo = hi - 0.5
        mid = (hi + lo) / 2
        ini = next(n for n in (int(mid), -(-mid // 1), round(mid * 2) / 2, mid) if lo < n < hi)
    ini = num(ini)
    moves[key] = ini
    for x in gs[frm][1:]:  # its creatures, right after it
        moves[x["key"]] = num(ini - 0.5) if lo is None or ini - 0.5 > lo else num((ini + lo) / 2)
    return {"initiative": ini, "moves": {x: n for x, n in moves.items() if not x.startswith("cr:")}}


# ---- The DM changes the order: a drag (`slot`), a typed number (`to`) or Undo (`back`)

router = APIRouter()


@router.post("/fight/initiative")
def change_order(request: Request, key: str = Form(""), slot: int = Form(-1), to: str = Form(""), back: str = Form(""),
                 db: Session = Depends(get_db)):
    """The DM (or an admin) moves a fighter in the fight's order: dropped at `slot` (plan), given the number `to`, or
    put back (`back`: Undo, [{key, initiative}]). Shown at once and sent to D&D Beyond's VTT through the DM's open VTT
    page; answers the corner card's words and what Undo sends."""
    from app import access, fight, web
    from app.auth import current_user

    user = current_user(request)
    campaign = web.campaign(db)
    if not user or not campaign:
        return JSONResponse({"error": "Sign in to change the order."}, status_code=401)
    if not on(campaign) or not access.allows("fight_order", access.level(user["email"]), access.role(user["email"], campaign.id)):
        return JSONResponse({"error": "Only the DM changes the order."}, status_code=403)
    fight.lock(db, campaign)
    f = copy.deepcopy(campaign.fight)  # (changed whole and saved: a change inside the saved one isn't seen)
    if not fight.shown(campaign, True):
        return JSONResponse({"error": "There's no fight in D&D Beyond's VTT to change."}, status_code=409)
    names = {x["key"]: x["name"] for x in f["order"]}
    before = {x["key"]: x.get("initiative") for x in f["order"]}
    if back:
        try:
            moves = {str(m["key"]): num(m["initiative"]) for m in json.loads(back) if str(m["key"]) in names}
        except (ValueError, TypeError, KeyError):
            return JSONResponse({"error": "That Undo didn't make sense."}, status_code=400)
    elif to:
        try:
            n = num(float(to.replace(",", ".")))
        except ValueError:
            return JSONResponse({"error": "That isn't a number."}, status_code=400)
        if key not in names or not -10 <= n <= 60:
            return JSONResponse({"error": "That isn't a number for the order."}, status_code=400)
        moves = {key: n}
    else:
        p = plan(fight.with_creatures(db, campaign, f["order"]), key, slot)
        if not p:
            return JSONResponse({"text": "", "back": []})
        moves = p["moves"]
    made = [k for k, n in moves.items() if want(f, k, n)]
    if not made:
        return JSONResponse({"error": "D&D Beyond's VTT doesn't say where to change that: the DM's VTT needs the askdnd "
                                      "extension 0.12.0 (reload the VTT after updating)."}, status_code=409)
    follow_masters(db, campaign, f)
    campaign.fight = f  # (saved: every page at the table shows the new order, app/realtime.py)
    db.commit()
    said = " · ".join(f"{names[k]}: {shown(before[k])} → {shown(moves[k])}" for k in made)
    sending = any(s["key"] in made for s in f.get("sets") or [])
    where = ("on its way to D&D Beyond" if dm_here(campaign) else "made once the DM's D&D Beyond VTT is open") if sending \
        else "as D&D Beyond's VTT has it"
    return JSONResponse({"text": f"{said} · {where}", "back": [{"key": k, "initiative": before[k]} for k in made]})
