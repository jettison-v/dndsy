"""askdnd runs the fight (askdnd's table, slice 7; docs/plans/2026-11-06-table-build-plan.md, docs/mockups/table-slices/
Fight; askdnd Runs the Fight, Nov 3).

**Start a fight** takes in every token on the place's map (D&D Beyond's "Add All Tokens"; hidden ones stay hidden). The
players roll their own Initiative from Battle or the table, as they do today (app/table_rolls.py hands the number here);
creatures are rolled for the DM with their Initiative bonus, shown only to her, one roll per group of the same creature
added together (Brett, Nov 6), and she can give any of them its own number. She orders it (Party's Rows and the table's
rows: drag, ↑ ↓, a number; app/initiative.py change_order), then **Begin**, then **Next turn** (a player's End turn
on their own turn too). Every step can be undone (Undo, the last 20).

It's kept where D&D Beyond's fight is kept (`Campaign.fight`, `"source": "askdnd"`) and settled the same way
(app/fight.py settle), so the fight band, Rows, reminders, conditions that end, Concentration's rounds, a familiar's
turn and your turn's bar follow it unchanged. While it runs, what D&D Beyond's VTT reports is ignored.

**Battle settings** (kept for the campaign, `Campaign.table_settings`): what players see of a creature's Hit Points
(Healthy, Bloodied or Down by default; the numbers; nothing), whether a group rolls once or each its own, and whether
new creatures start seen or hidden.
"""

import copy
import json
import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import fight, places, rules_data, web
from app.db import get_db
from app.models import Campaign, Character, Place, TableRoll, Token
from app.table_rolls import roll_d20

router = APIRouter()

SETTINGS = {"enemy_hp": ("status", "numbers", "none"), "group": ("once", "each"), "new": ("seen", "hidden")}
DEFAULTS = {"enemy_hp": "status", "group": "once", "new": "seen"}
UNDO = 20


def settings(campaign: Campaign | None) -> dict:
    s = (campaign.table_settings if campaign else None) or {}
    return {k: s.get(k) if s.get(k) in SETTINGS[k] else DEFAULTS[k] for k in SETTINGS}


def ours(campaign: Campaign | None) -> bool:
    """askdnd runs this campaign's fight now."""
    return bool(campaign and campaign.fight and campaign.fight.get("source") == "askdnd")


def _mod(entry: dict | None) -> int:
    if not entry:
        return 0
    if isinstance(entry.get("initiative"), int):
        return entry["initiative"]
    return ((entry.get("abilities") or {}).get("dex", 10) - 10) // 2


def _entry(t: Token, ch: Character | None) -> dict:
    """A token as one of the fight's fighters, in the shape app/fight.py keeps (`key` is the token's)."""
    kind = "character" if t.kind == "character" else "companion" if t.kind == "creature" else "monster"
    return {"key": f"t{t.id}", "token": t.id, "name": t.name, "kind": kind, "character": t.character_id if t.kind == "character" else None,
            "monster": None, "initiative": None, "hidden": t.hidden, "active": False,
            "image": (t.monster or {}).get("image") or None, "group": t.group, "gkey": None}


def _sorted(order: list[dict]) -> list[dict]:
    """Highest Initiative first; ties keep their place (the DM settles a tie); those without a number last."""
    return sorted(order, key=lambda x: -x["initiative"] if isinstance(x.get("initiative"), (int, float)) else 999)


def _roll_for(db: Session, campaign: Campaign, user_id: int | None, t: Token, n: int | None = None) -> int:
    """A creature's Initiative, rolled for the DM (only she sees it in Table rolls)."""
    entry = rules_data.find("monster", (t.monster or {}).get("key", ""), db, campaign.id)
    r = roll_d20(_mod(entry), "normal")
    name = t.name if n is None or n < 2 else f"{(t.monster or {}).get('name') or t.name} × {n}"
    db.add(TableRoll(campaign_id=campaign.id, character_id=None, user_id=user_id, label="Initiative", kind="check", mode="normal",
                     visibility="dm", damage="", spec=None, extras=[], who=name[:80], parts=[],
                     **{k: r[k] for k in ("dice", "kept", "modifier", "total", "formula")}))
    from app import realtime

    realtime.announce(db, campaign.id, "rolls")
    return r["total"]


def _save(db: Session, campaign: Campaign, now: dict | None, undo: bool = True) -> None:
    """The fight changed: kept for Undo, then settled as every fight is (turns, reminders, your turn's bar)."""
    prev = copy.deepcopy(campaign.fight) if campaign.fight else None
    if now is not None and undo and prev and prev.get("source") == "askdnd":
        back = {k: v for k, v in prev.items() if k != "undo"}
        now["undo"] = ((prev.get("undo") or []) + [back])[-UNDO:]
    fight.settle(db, campaign, prev, now)


def _user_id(db: Session, user: dict) -> int | None:
    from app import picks

    me = picks.user_row(db, user)
    return me.id if me else None


def _answer(text: str, kind: str = "ok") -> Response:
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"tableChanged": True, "toast": web.notice(text, kind)})})


@router.post("/table/places/{place_id:int}/fight")
def start(request: Request, place_id: int, db: Session = Depends(get_db)):
    """Start a fight with every token on the map; creatures rolled for the DM, players roll their own."""
    user, campaign = places.here(request, db)
    p = places._place(db, campaign, place_id)
    fight.lock(db, campaign)
    if ours(campaign):
        return _answer("A fight is running already. End it first.", "warn")
    toks = list(db.scalars(select(Token).where(Token.place_id == p.id).order_by(Token.id)))
    if not toks:
        return _answer("There's no one on the map to fight.", "warn")
    me, group_rolls, order = _user_id(db, user), {}, []
    per_group = settings(campaign)["group"] == "once"
    for t in toks:
        e = _entry(t, db.get(Character, t.character_id) if t.character_id else None)
        if t.kind == "monster":
            if per_group and t.group:
                if t.group not in group_rolls:
                    members = sum(1 for x in toks if x.group == t.group)
                    group_rolls[t.group] = _roll_for(db, campaign, me, t, members)
                e["initiative"] = group_rolls[t.group]
            else:
                e["initiative"] = _roll_for(db, campaign, me, t)
        order.append(e)
    now = {"source": "askdnd", "place": p.id, "round": 0, "turn": 0, "waiting": True, "order": _sorted(order),
           "id": secrets.token_hex(4)}
    if campaign.shown_place_id is None:
        campaign.shown_place_id = p.id
    _save(db, campaign, now, undo=False)
    db.commit()
    return _answer("Roll for Initiative! The creatures have rolled; the players roll theirs.")


def rolled(db: Session, campaign: Campaign, ch: Character, creature: str, total) -> bool:
    """A player's Initiative roll lands in askdnd's fight (before or after Begin: before, it places them; after, only the
    DM moves anyone). True when it did."""
    if not ours(campaign):
        return False
    fight.lock(db, campaign)
    f = copy.deepcopy(campaign.fight)
    if not f.get("waiting"):
        return False
    hit = False
    for x in f["order"]:
        if creature and x["kind"] == "companion" and x["name"] == creature and _master(db, x) == ch.id:
            x["initiative"], hit = total, True
        elif not creature and x.get("character") == ch.id:
            x["initiative"], hit = total, True
    if hit:
        f["order"] = _sorted(f["order"])
        _save(db, campaign, f)
        db.flush()
    return hit


def _master(db: Session, x: dict) -> int | None:
    t = db.get(Token, x.get("token")) if x.get("token") else None
    return t.character_id if t else None


def set_numbers(db: Session, campaign: Campaign, moves: dict[str, float]) -> list[str]:
    """The DM's numbers (a drag, a typed number, Undo of either): each fighter's Initiative, the order sorted again with
    whose turn it is kept. Returns the keys changed."""
    f = copy.deepcopy(campaign.fight)
    made = []
    for x in f["order"]:
        if x["key"] in moves:
            x["initiative"] = moves[x["key"]]
            made.append(x["key"])
    if made:
        f["order"] = _sorted(f["order"])
        _save(db, campaign, f)
    return made


@router.post("/table/fight/begin")
def begin(request: Request, db: Session = Depends(get_db)):
    """Round 1, the first in the order goes (anyone who hasn't rolled goes last until the DM says otherwise)."""
    _, campaign = places.here(request, db)
    fight.lock(db, campaign)
    if not ours(campaign) or not campaign.fight.get("waiting"):
        return _answer("There's no fight waiting to begin.", "warn")
    f = copy.deepcopy(campaign.fight)
    f["order"] = _sorted(f["order"])
    for i, x in enumerate(f["order"]):
        x["active"] = i == 0
    f["waiting"], f["round"], f["turn"] = False, 1, 1
    _save(db, campaign, f)
    db.commit()
    return _answer(f"Round 1: {f['order'][0]['name']}'s turn.")


def _advance(f: dict, step: int = 1) -> None:
    n = len(f["order"])
    i = next((k for k, x in enumerate(f["order"]) if x.get("active")), -1)
    j = (i + step) % n
    if step > 0 and j <= i:
        f["round"] = int(f.get("round") or 1) + 1
    for k, x in enumerate(f["order"]):
        x["active"] = k == j
    f["turn"] = j + 1


@router.post("/table/fight/next")
def next_turn(request: Request, db: Session = Depends(get_db)):
    """Next turn: the DM's, or a player's End turn on their own character's turn."""
    from app import picks

    user, campaign = places.here(request, db, need_runs=False)
    fight.lock(db, campaign)
    if not ours(campaign) or campaign.fight.get("waiting"):
        return _answer("There's no turn to end.", "warn")
    f = copy.deepcopy(campaign.fight)
    now = next((x for x in f["order"] if x.get("active")), None)
    if not places.runs(user, campaign):
        ch = db.get(Character, now["character"]) if now and now.get("character") else None
        if ch is None or not picks.can_edit(db, user, ch):
            raise HTTPException(403, "It isn't your turn to end.")
    _advance(f)
    _save(db, campaign, f)
    db.commit()
    nxt = next((x for x in f["order"] if x.get("active")), None)
    return _answer(f"Round {f['round']}: {nxt['name']}'s turn." if nxt else "Next turn.")


@router.post("/table/fight/undo")
def undo(request: Request, db: Session = Depends(get_db)):
    """The fight as it was before its last change (a turn, a number, Begin)."""
    _, campaign = places.here(request, db)
    fight.lock(db, campaign)
    if not ours(campaign) or not campaign.fight.get("undo"):
        return _answer("There's nothing to undo.", "warn")
    stack = list(campaign.fight["undo"])
    back = copy.deepcopy(stack.pop())
    back["undo"] = stack
    back["reminders"], back["seq"] = campaign.fight.get("reminders") or [], campaign.fight.get("seq", 0)
    back["done"], back["last"] = campaign.fight.get("done") or [], campaign.fight.get("last")  # (a turn counts once a fight)
    from datetime import UTC, datetime

    campaign.fight, campaign.fight_at = back, datetime.now(UTC)
    db.commit()
    return _answer("Undone.")


@router.post("/table/fight/end")
def end(request: Request, db: Session = Depends(get_db)):
    _, campaign = places.here(request, db)
    fight.lock(db, campaign)
    if not ours(campaign):
        return _answer("There's no fight to end.", "warn")
    fight.settle(db, campaign, campaign.fight, None)
    db.commit()
    return _answer("The fight is over.")


def joined(db: Session, campaign: Campaign, toks: list[Token], user_id: int | None) -> None:
    """Tokens put on the map mid-fight join it (creatures rolled for the DM, one roll per group)."""
    if not ours(campaign) or not toks:
        return
    fight.lock(db, campaign)
    f = copy.deepcopy(campaign.fight)
    if f.get("place") != toks[0].place_id:
        return
    have = {x["key"] for x in f["order"]}
    per_group = settings(campaign)["group"] == "once"
    rolls: dict[str, int] = {}
    for t in toks:
        if f"t{t.id}" in have:
            continue
        e = _entry(t, None)
        if t.kind == "monster":
            if per_group and t.group:
                if t.group not in rolls:
                    rolls[t.group] = _roll_for(db, campaign, user_id, t, sum(1 for x in toks if x.group == t.group))
                e["initiative"] = rolls[t.group]
            else:
                e["initiative"] = _roll_for(db, campaign, user_id, t)
        f["order"].append(e)
    f["order"] = _sorted(f["order"])
    _save(db, campaign, f)


def left(db: Session, campaign: Campaign, token_id: int) -> None:
    """A token taken off the map leaves the fight (whose turn it was passes to the next)."""
    if not ours(campaign):
        return
    f = copy.deepcopy(campaign.fight)
    gone = next((x for x in f["order"] if x.get("token") == token_id), None)
    if gone is None:
        return
    if gone.get("active") and len(f["order"]) > 1:
        _advance(f)
    f["order"] = [x for x in f["order"] if x.get("token") != token_id]
    _save(db, campaign, f if f["order"] else None)


@router.post("/table/settings")
def save_settings(request: Request, enemy_hp: str = Form(""), group: str = Form(""), new: str = Form(""),
                  db: Session = Depends(get_db)):
    """The DM's battle settings, kept for the campaign."""
    _, campaign = places.here(request, db)
    s = settings(campaign)
    for k, v in (("enemy_hp", enemy_hp), ("group", group), ("new", new)):
        if v in SETTINGS[k]:
            s[k] = v
    campaign.table_settings = s
    db.commit()
    return _answer("Battle settings saved.")


def place_of(campaign: Campaign) -> int | None:
    return (campaign.fight or {}).get("place") if ours(campaign) else None


def in_fight(campaign: Campaign, place: Place | None) -> bool:
    return bool(place) and place_of(campaign) == place.id
