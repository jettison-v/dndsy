"""Handing items over (Brett, 2026-11-02): Give in an item's side panel hands it to another character at the table, and
the DM's Give loot on a character's Sheet › Items adds an item from D&D Beyond's own list, or coins. Both go to D&D
Beyond through the bridge with the requests the sheet itself sends (app/ddb_fields.py: an item's count, removing it,
adding one), so nothing new is written there.

D&D Beyond can't move an item between characters: the giver's copy goes and the receiver gets a fresh one of the same
item. What belonged to that copy (charges used, attunement, a note, a new name) stays behind, and the window says so. A
custom item, a homebrew one or a container with things in it is handed over on D&D Beyond. Both sheets have to be
reachable when it's given. It's two changes, the receiver's first: the giver's copy goes only once D&D Beyond has the
receiver's (ddb_bridge._due; Nov 3, a Rope left Roscoe and didn't reach Cathartic for 3 minutes). If the receiver's is
stopped, Try again makes it and then the giver's; if it's undone, the giver's is undone too and the item stays. So a
given item is at worst briefly on both sheets, never on neither.
"""

import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import ddb, ddb_bridge, ddb_fields, realtime, web
from app.auth import current_user, is_admin, is_dm
from app.characters import campaign_characters
from app.db import get_db
from app.ddb_sheet import CORE_SOURCES
from app.hit_points import _guard as _player_or_dm
from app.models import Character
from app.templating import templates

router = APIRouter()
COINS = ("cp", "sp", "ep", "gp", "pp")
ITEMS_URL = "https://character-service.dndbeyond.com/character/v5/game-data/items?sharingSetting=2"
CATALOG_SECONDS = 24 * 3600
CATALOG_RETRY = 300  # seconds before a failed read is tried again: D&D Beyond down mustn't hold every Give loot for its timeout
_catalog: dict = {"at": 0.0, "tried": 0.0, "items": []}


def _guard(db: Session, request: Request, character_id: int) -> tuple[Character, dict]:
    ch, user = _player_or_dm(db, request, character_id)
    if not ddb_bridge.plays(db, ch):
        raise HTTPException(404)
    return ch, user


def _row(ch: Character, item_id: int) -> dict:
    """D&D Beyond's own row for this item, from askdnd's copy of the sheet."""
    raw = ch.snapshot.raw if ch.snapshot else None
    row = ddb_fields.pick(raw or {}, ["inventory", {"id": item_id}])
    if not row or not (row.get("definition") or {}).get("id"):
        raise HTTPException(404)
    return row


def _why_not(ch: Character, row: dict) -> str:
    """Why this one can't be handed over from askdnd, or nothing."""
    d = row.get("definition") or {}
    if not d.get("entityTypeId"):
        return "D&D Beyond doesn't say what kind of item it is: hand it over on D&D Beyond."
    if d.get("isHomebrew"):
        return "It's a homebrew item: hand it over on D&D Beyond."
    inside = [i for i in (ch.snapshot.raw or {}).get("inventory") or [] if str(i.get("containerEntityId")) == str(row.get("id"))]
    if inside:
        return f"It holds {len(inside)} other item{'s' if len(inside) != 1 else ''}: take {'them' if len(inside) != 1 else 'it'} out first, or hand it over on D&D Beyond."
    return ""


def _left_behind(row: dict) -> list[str]:
    out = []
    if (row.get("limitedUse") or {}).get("numberUsed"):
        out.append("its charges used")
    if row.get("isAttuned"):
        out.append("attunement")
    return out


def _receivers(db: Session, ch: Character) -> list[Character]:
    return [x for x in campaign_characters(db, ch.campaign_id) if x.id != ch.id and x.ddb_id and ddb_bridge.on_for(db, x)]


@router.get("/characters/{character_id:int}/items/{item_id:int}/give")
def give_window(request: Request, character_id: int, item_id: int, db: Session = Depends(get_db)):
    """Give, from an item's side panel."""
    ch, _ = _guard(db, request, character_id)
    row = _row(ch, item_id)
    return templates.TemplateResponse(request, "_give_window.html", {
        "c": ch, "item_id": item_id, "name": ddb_fields.item_name(ch.snapshot.raw, item_id), "count": row.get("quantity") or 0,
        "why_not": _why_not(ch, row), "left_behind": _left_behind(row),
        "to": [{"id": x.id, "name": x.name, "open": ddb_bridge.reachable(x)} for x in _receivers(db, ch)],
        "reachable": ddb_bridge.reachable(ch)})


@router.post("/characters/{character_id:int}/items/{item_id:int}/give")
def give(request: Request, character_id: int, item_id: int, receiver: str = Form(""), quantity: str = Form("1"), db: Session = Depends(get_db)):
    """Take it (or some of a stack) off this sheet and add the same item to the other."""
    ch, _ = _guard(db, request, character_id)
    row = _row(ch, item_id)
    if why := _why_not(ch, row):
        raise HTTPException(409, why)
    other = next((x for x in _receivers(db, ch) if str(x.id) == receiver), None)
    if other is None:
        raise HTTPException(409, "Pick who gets it.")
    count = row.get("quantity") or 0
    n = int(quantity) if quantity.isdigit() else 0
    if not 0 < n <= count:
        raise HTTPException(409, f"{ch.name} has {count}.")
    ddb_bridge.reach(ch)
    ddb_bridge.reach(other, f"{other.name}'s D&D Beyond sheet can't be reached: they open it in Chrome with the askdnd bridge, "
                            "or it's handed over on D&D Beyond. Nothing was taken from " + ch.name + ".")
    d = row["definition"]
    name = ddb_fields.item_name(ch.snapshot.raw, item_id)
    what = name + (f" ×{n}" if n > 1 else "")
    got = ddb_bridge.add(db, other, "add_item", {"definition": d["id"], "entityTypeId": d["entityTypeId"], "quantity": n, "name": d.get("name") or name},
                         f"{other.name} got {what} from {ch.name}")
    after = {"after": got}  # (the giver's copy goes once D&D Beyond has the receiver's: ddb_bridge._due)
    if n >= count:
        ddb_bridge.add(db, ch, "remove_item", {"item": item_id, "name": name, **after}, f"{ch.name} gave {other.name} {what}")
    else:
        ddb_bridge.add(db, ch, "item", {"item": item_id, "delta": -n, "name": name, **after}, f"{ch.name} gave {other.name} {what}")
    realtime.announce(db, other.campaign_id, "character", id=other.id)
    db.commit()
    return JSONResponse({"text": f"{what} to {other.name}: it leaves {ch.name}'s sheet once {other.name}'s has it", "deliver": web.deliver_now(ch)})


# ------------------------------------------------------------------ loot from the DM


def catalog() -> list[dict]:
    """D&D Beyond's items from the 2024 core books (askdnd's rules are 2024 only), by name, read once a day."""
    now = time.time()
    if (now - _catalog["at"] > CATALOG_SECONDS or not _catalog["items"]) and now - _catalog["tried"] > CATALOG_RETRY:
        _catalog["tried"] = now
        try:
            payload = ddb._get_json(ITEMS_URL, 15)
        except (OSError, ValueError):
            payload = None
        rows = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(rows, list):
            core = {}
            for i in rows:
                if not isinstance(i, dict) or i.get("isHomebrew") or not i.get("name") or not i.get("id"):
                    continue
                if {s.get("sourceId") for s in i.get("sources") or [] if s.get("sourceType") == 1} & CORE_SOURCES:
                    core.setdefault(i["name"], {"id": i["id"], "entityTypeId": i.get("entityTypeId"), "name": i["name"],
                                                "magic": bool(i.get("magic")), "rarity": i.get("rarity") or ""})
            _catalog.update(at=time.time(), items=sorted(core.values(), key=lambda x: x["name"]))
    return _catalog["items"]


def _dm(db: Session, request: Request, character_id: int) -> Character:
    user = current_user(request)
    ch = db.get(Character, character_id)
    if not user or not ch or not ddb_bridge.plays(db, ch) or not (is_admin(user) or is_dm(user, ch.campaign_id)):
        raise HTTPException(404)
    return ch


@router.get("/characters/{character_id:int}/loot")
def loot_window(request: Request, character_id: int, db: Session = Depends(get_db)):
    """The DM's Give loot: an item from D&D Beyond's list, coins, or both."""
    ch = _dm(db, request, character_id)
    items = catalog()
    return templates.TemplateResponse(request, "_loot_window.html", {"c": ch, "items": items, "coins": COINS, "reachable": ddb_bridge.reachable(ch)})


@router.post("/characters/{character_id:int}/loot")
def loot(request: Request, character_id: int, item: str = Form(""), quantity: str = Form("1"), amount: str = Form(""), coin: str = Form("gp"),
         db: Session = Depends(get_db)):
    ch = _dm(db, request, character_id)
    ddb_bridge.reach(ch)
    item, said = item.strip(), []
    if item:
        found = next((i for i in catalog() if i["name"].lower() == item.lower()), None)
        if not found:
            raise HTTPException(409, f"D&D Beyond's 2024 books have no item called {item}. Pick one from the list.")
        n = int(quantity) if quantity.isdigit() else 0
        if not 0 < n <= 100:
            raise HTTPException(409, "Give 1 to 100 of it.")
        what = found["name"] + (f" ×{n}" if n > 1 else "")
        ddb_bridge.add(db, ch, "add_item", {"definition": found["id"], "entityTypeId": found["entityTypeId"], "quantity": n, "name": found["name"]},
                       f"{ch.name} got {what} from the DM")
        said.append(what)
    if amount.strip():
        m = int(amount) if amount.isdigit() else 0
        if coin not in COINS or not 0 < m <= 100000:
            raise HTTPException(409, "Enter how many coins.")
        numbers = ddb_bridge.numbers(ch)
        made = ddb_bridge._change(numbers, {"kind": "use", "field": f"coin:{coin}", "delta": m})
        if not made:
            raise HTTPException(409, "That isn't a change askdnd can make on D&D Beyond.")
        ddb_bridge.add(db, ch, *made, f"{ch.name} got {m:,} {coin} from the DM")
        said.append(f"{m:,} {coin}")
    if not said:
        raise HTTPException(409, "Pick an item or enter coins.")
    realtime.announce(db, ch.campaign_id, "character", id=ch.id)
    db.commit()
    return JSONResponse({"text": f"{' and '.join(said)} to {ch.name}: on its way to D&D Beyond", "deliver": web.deliver_now(ch)})
