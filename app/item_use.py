"""Using an item in play (the rest of roadmap step 5; Brett, 2026-10-30, docs/mockups/potions-and-charges.html).

A column on Battle has an Items section that follows pinning, the rest in the side panel (character_views.battle_columns).
An item's button opens a small window like a roll (app.js "using an item"), and using it makes the change on D&D Beyond
through the bridge, only while the sheet can be reached:

- **What one use changes** (conditions.item_spends): an item's count or its charges, as D&D Beyond counts them.
- **Healing** rolls in Table rolls for all to see. Drink heals you at once: there's no ruling to make. Give spends the
  giver's potion and leaves Apply to on the roll, like any other healing roll.
- **An effect** (conditions.on_use: a Potion of Water Breathing) starts when it's used.
- **Undo** on the corner card takes it back, except a heal that brought someone up from 0: that also ended Unconscious
  and cleared the death save marks, so it's undone by hand.

Nothing here decides what an item does beyond its numbers: other effects are the table's to play out.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import character_views as views
from app import characters as chars
from app import conditions as cond
from app import ddb_bridge, ddb_sheet, hit_points, live, picks, realtime, table_rolls, web
from app.auth import current_user, is_dm
from app.db import get_db
from app.models import Character, TableRoll
from app.templating import templates

router = APIRouter()


def _guard(db: Session, request: Request, character_id: int) -> tuple[Character, dict]:
    user, ch = current_user(request), db.get(Character, character_id)
    if not user or not ch or not picks.can_edit(db, user, ch) or not ddb_bridge.on_for(db, ch):
        raise HTTPException(404)
    return ch, user


def _sheet(db: Session, ch: Character) -> dict:
    return ddb_bridge.as_shown(db, ch, chars.character_summary(ch)) or {}


def _item(db: Session, ch: Character, item_id: int) -> tuple[dict, dict]:
    """The item and its option on Battle, as shown: with what's on its way."""
    sheet, key = _sheet(db, ch), f"item:{item_id}"
    it = next((x for x in sheet.get("inventory") or [] if x["key"] == key), None)
    o = next((x for x in views.options(sheet, set()) if x["key"] == key and x.get("use")), None) if it else None
    if not o:
        raise HTTPException(404)
    return it, o


def _others(db: Session, ch: Character) -> list[str]:
    """Who a potion can go to: the rest of the table."""
    return [r["name"] for r in live.rows_from(db) if r["id"] != ch.id]


def _spend(db: Session, ch: Character, it: dict, how: str, back: bool = False) -> None:
    item_id = int(it["key"].split(":", 1)[1])
    label = f"{ch.name}: {it['name']}" + (" put back" if back else " used")
    if how == "charges":
        most = ddb_sheet.most(ch.snapshot.raw, "charges", item_id)
        ddb_bridge.add(db, ch, "use", {"field": f"charges:{item_id}", "delta": -1 if back else 1, "max": most}, label)
    else:
        ddb_bridge.add(db, ch, "item", {"item": item_id, "delta": 1 if back else -1, "name": it["name"]}, label)


def _start(db: Session, ch: Character, it: dict, ou: dict) -> None:
    name = ou["starts"]
    if any(c.get("name") == name for c in cond.shown(ch.conditions, _sheet(db, ch).get("conditions"), True)):
        return
    if name in cond.ON_DDB:
        ddb_bridge.add(db, ch, "set", {"field": cond.ddb_field(name), "value": True}, f"{ch.name}: {name} ({it['name']})")
    ch.conditions = cond.add(ch.conditions, name, it["name"], ou.get("note", ""))


def _end(db: Session, ch: Character, name: str) -> None:
    if name in cond.ON_DDB:
        ddb_bridge.add(db, ch, "set", {"field": cond.ddb_field(name), "value": False}, f"{ch.name}: no longer {name}")
    ch.conditions = cond.end(ch.conditions, name) or None


@router.get("/characters/{character_id:int}/use/{item_id:int}")
def window(request: Request, character_id: int, item_id: int, db: Session = Depends(get_db)):
    """What the item's button opens, in the roll window."""
    ch, _ = _guard(db, request, character_id)
    it, o = _item(db, ch, item_id)
    return templates.TemplateResponse(request, "_use_window.html", {"c": ch, "it": it, "o": o, "others": _others(db, ch) if o["use"]["gives"] else [],
                                                                    "reachable": ddb_bridge.reachable(ch), "starts": (cond.on_use(it) or {}).get("starts", "")})


@router.post("/characters/{character_id:int}/use/{item_id:int}")
def use(request: Request, character_id: int, item_id: int, to: str = Form(""), db: Session = Depends(get_db)):
    """Use one: the window's Drink, Read or Use, or Give (`to`: who, for the table to read)."""
    ch, user = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    it, o = _item(db, ch, item_id)
    if not o["use"]["left"]:
        raise HTTPException(409, f"{it['name']}: none left, {o['use']['back'] or 'gone once used'}.")
    if not o["use"]["gives"] or (to and to not in _others(db, ch)):
        to = ""
    me = picks.user_row(db, user)
    how = cond.item_spends(it)
    _spend(db, ch, it, how)
    undo: dict | None = {"spent": how}
    verb = {"Drink": "Drank", "Read": "Read", "Use": "Used"}[o["use"]["verb"]]
    text = f"Gave {to} {it['name']}" if to else f"{verb} {it['name']}"
    row = None
    if o["use"]["gives"] and o.get("heal") and o.get("dice"):
        row = table_rolls.add_roll(db, ch, me.id, f"{it['name']} for {to}" if to else it["name"], o["dice"])
    if row and not to:
        w = hit_points.working(db, ch, "heal", [{"amount": row.total, "type": ""}])
        said = hit_points.make(db, ch, user, row, "heal", w)
        text += f": {said}"
        undo = None if w["up"] else {**undo, "heal": w["hp_after"] - w["hp_before"], "roll": row.id}
    elif row:
        text += f" ({row.total} on the roll, for {to} to apply)"
    if (ou := cond.on_use(it)):
        _start(db, ch, it, ou)
        text += f": {ou['starts']}"
        undo = undo and {**undo, "cond": ou["starts"]}
    db.commit()
    out = {"text": text, "undo": undo, "undoUrl": f"/characters/{ch.id}/use/{item_id}/undo", "deliver": web.deliver_now(ch)}
    if row:
        db.refresh(row)
        out |= table_rolls.reply_body(request, db, row, me.id, is_dm(user))
    return JSONResponse(out)


@router.post("/characters/{character_id:int}/use/{item_id:int}/undo")
def undo_use(request: Request, character_id: int, item_id: int, spent: str = Form(""), heal: int = Form(0), roll: int = Form(0),
             cond_name: str = Form("", alias="cond"), db: Session = Depends(get_db)):
    """The corner card's Undo: the same changes the other way."""
    ch, _ = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    it = next((x for x in _sheet(db, ch).get("inventory") or [] if x["key"] == f"item:{item_id}"), None)
    if not it or spent not in ("charges", "item"):
        raise HTTPException(404)
    _spend(db, ch, it, spent, back=True)
    if heal > 0:
        ddb_bridge.add(db, ch, "hp", {"amount": -heal, "undo": True}, f"{ch.name}: {it['name']} undone")
    if cond_name in cond.KNOWN:
        _end(db, ch, cond_name)
    r = db.get(TableRoll, roll) if roll else None
    if r and r.character_id == ch.id and (done := hit_points.applied(db, r).get(ch.id)):
        done.label, done.total = f"Undone: {done.label}"[:120], 0
        realtime.announce(db, ch.campaign_id, "rolls")
    db.commit()
    return JSONResponse({"text": f"{it['name']} put back", "deliver": web.deliver_now(ch)})
