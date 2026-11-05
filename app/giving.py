"""Handing items over (Brett, 2026-11-02): Give in an item's side panel hands it to another character at the table. It
goes to D&D Beyond through the bridge with the requests the sheet itself sends (app/ddb_fields.py: an item's count,
removing it, adding one), so nothing new is written there. D&D Beyond's own list of items is read here too, for the
item browser (app/item_browser.py: Add item, and the DM's Give loot).

D&D Beyond can't move an item between characters: the giver's copy goes and the receiver gets a fresh one of the same
item. What belonged to that copy (charges used, attunement, a note, a new name) stays behind, and the window says so. A
custom item, a homebrew one or a container with things in it is handed over on D&D Beyond. Both sheets have to be
reachable when it's given. It's two changes, the receiver's first: the giver's copy goes only once D&D Beyond has the
receiver's (ddb_bridge._due; Nov 3, a Rope left Roscoe and didn't reach Cathartic for 3 minutes). If the receiver's is
stopped, Try again makes it and then the giver's; if it's undone, the giver's is undone too and the item stays. So a
given item is at worst briefly on both sheets, never on neither.
"""

import os
import time

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import books, ddb, ddb_bridge, ddb_fields, realtime, web
from app.characters import campaign_characters
from app.db import get_db
from app.ddb_sheet import CORE_SOURCES
from app.hit_points import _guard as _player_or_dm
from app.models import Character
from app.templating import templates

router = APIRouter()
COINS = ("cp", "sp", "ep", "gp", "pp")
# (DDB_ITEMS_URL: tests/browser/test_extension.py's stand-in list, a file; never set on beta)
ITEMS_URL = os.environ.get("DDB_ITEMS_URL") or "https://character-service.dndbeyond.com/character/v5/game-data/items?sharingSetting=2"
CATALOG_SECONDS = 24 * 3600
CATALOG_RETRY = 300  # seconds before a failed read is tried again: D&D Beyond down mustn't hold every item browser for its timeout
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
    return JSONResponse({"text": f"{what} to {other.name}: it leaves {ch.name}'s sheet once {other.name}'s has it", "deliver": web.deliver_now(ch, also=[other])})


# ------------------------------------------------------------------ D&D Beyond's items (the item browser: app/item_browser.py)


FREE_RULES = 148  # D&D Beyond's free 2024 rules, where it keeps the plain weapons and armor (a Longsword, Chain Mail)
ITEM_BOOKS = {**{b.ddb_source_id: b.title for b in books.BOOKS}, FREE_RULES: "Free Rules (2024)"}
KINDS = {"Other Gear": "Adventuring gear", "Weapon": "Weapons", "Armor": "Armor", "Potion": "Potions", "Wondrous item": "Wondrous items",
         "Ring": "Rings", "Wand": "Wands", "Rod": "Rods", "Staff": "Staffs", "Scroll": "Scrolls"}
PICTURES = ("https://www.dndbeyond.com/", "https://media.dndbeyond.com/")  # (only D&D Beyond's own, as with token art)


def _item(i: dict, book: int) -> dict:
    """One of D&D Beyond's items, as the item browser shows it (app/item_browser.py). A price only where D&D Beyond
    has one (plain gear: no magic item has one, and the DM sets those); its picture only from D&D Beyond's own hosts."""
    magic = bool(i.get("magic"))
    cost, damage = i.get("cost"), i.get("damage") or {}
    picture = next((u for u in (i.get("largeAvatarUrl"), i.get("avatarUrl")) if isinstance(u, str) and u.startswith(PICTURES)), "")
    return {"id": i["id"], "entityTypeId": i.get("entityTypeId"), "name": i["name"], "magic": magic,
            "rarity": (i.get("rarity") or "") if magic else "Not magic", "kind": KINDS.get(i.get("filterType"), "Other"),
            "type": i.get("subType") or i.get("type") or "", "attune": bool(i.get("canAttune")), "attune_note": i.get("attunementDescription") or "",
            "cost_cp": round(float(cost) * 100) if isinstance(cost, int | float) and cost > 0 else None,
            "weight": float(i.get("weight") or 0) * float(i.get("weightMultiplier") or 1),
            "damage": f"{damage.get('diceString') or ''} {i.get('damageType') or ''}".strip() if damage.get("diceString") else "",
            "ac": i.get("armorClass"), "properties": [p["name"] + (f" ({p['notes']})" if p.get("notes") else "") for p in i.get("properties") or [] if p.get("name")],
            "picture": picture, "book": ITEM_BOOKS.get(book, ""), "text": ddb.html_to_text(i.get("description"))[:6000], "container": bool(i.get("isContainer")),
            # What it would mean for a character (app/item_fit.py): its armor or weapon kind, Strength and Stealth, the
            # mastery and other properties by name, and what it grants (D&D Beyond's modifiers: AC, saves, a score)
            "armor_type": i.get("armorTypeId"), "str_req": i.get("strengthRequirement"), "stealth_dis": i.get("stealthCheck") == 2,
            "weapon_cat": i.get("categoryId") if i.get("filterType") == "Weapon" else None, "attack_type": i.get("attackType"),
            "base_name": i.get("type") if i.get("filterType") == "Weapon" else (i.get("baseArmorName") or ""),
            "dice": damage.get("diceString") or "", "damage_type": i.get("damageType") or "",
            "props": {p["name"]: p.get("notes") or "" for p in i.get("properties") or [] if p.get("name")},
            "mods": [{"type": m.get("type"), "sub": m.get("subType"), "value": m.get("value"), "attuned": bool(m.get("requiresAttunement"))}
                     for m in i.get("grantedModifiers") or [] if m.get("type") in ("bonus", "set") and m.get("subType")]}


def catalog() -> list[dict]:
    """D&D Beyond's items from the 2024 books (askdnd's rules are 2024 only), with the plain weapons and armor it keeps in
    its free 2024 rules, by name, read once a day: what the item browser lists (app/item_browser.py)."""
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
                book = next((s.get("sourceId") for s in i.get("sources") or [] if s.get("sourceType") == 1 and s.get("sourceId") in CORE_SOURCES | {FREE_RULES}), None)
                if book is not None and not i.get("isLegacy"):
                    core.setdefault(i["name"], _item(i, book))
            _catalog.update(at=time.time(), items=sorted(core.values(), key=lambda x: x["name"]))
    return _catalog["items"]
