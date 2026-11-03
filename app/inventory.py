"""Inventory in play (roadmap 1.5): equip, attune and coins, through the bridge. An item's count and charges are counted
in app/resources.py, using one in app/item_use.py.

An item's side panel has Equip, Attune and Move to (another of your bags, or carried); Sheet › Items has Change coins. D&D Beyond keeps all of it, and what it does to
a character's numbers (AC, spells from an item) comes back with its next read. Attunement stops at 3, as the rules do.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import ddb_bridge, web
from app.db import get_db
from app.item_use import _guard as _player, _sheet
from app.templating import templates

router = APIRouter()
COINS = ("cp", "sp", "ep", "gp", "pp")


def _guard(db: Session, request: Request, character_id: int):
    ch, user = _player(db, request, character_id)
    if not ddb_bridge.plays(db, ch):
        raise HTTPException(404)
    return ch, user


def _item(db: Session, ch, item_id: int) -> tuple[dict, dict]:
    sheet = _sheet(db, ch)
    it = next((x for x in sheet.get("inventory") or [] if x["key"] == f"item:{item_id}"), None)
    if it is None:
        raise HTTPException(404)
    return sheet, it


def _set(db: Session, ch, field: str, value: bool | int, said: str) -> Response:
    ddb_bridge.reach(ch)
    n = ddb_bridge.numbers(ch)
    made = ddb_bridge._change(n, {"kind": "set", "field": field, "value": value})
    if not made:
        raise HTTPException(409, "That isn't a change askdnd can make on D&D Beyond.")
    ddb_bridge.add(db, ch, *made, f"{ch.name}: {said}")
    db.commit()
    out = Response(status_code=204)
    out.headers["HX-Trigger"] = web.changed(ch, toast=f"{said}: on its way to D&D Beyond", deliver=True)
    return out


@router.post("/characters/{character_id:int}/items/{item_id:int}/equip")
def equip(request: Request, character_id: int, item_id: int, on: str = Form(""), db: Session = Depends(get_db)):
    ch, _ = _guard(db, request, character_id)
    _, it = _item(db, ch, item_id)
    return _set(db, ch, f"equipped:{item_id}", bool(on), f"{it['name']} {'equipped' if on else 'unequipped'}")


@router.post("/characters/{character_id:int}/items/{item_id:int}/attune")
def attune(request: Request, character_id: int, item_id: int, on: str = Form(""), db: Session = Depends(get_db)):
    ch, _ = _guard(db, request, character_id)
    sheet, it = _item(db, ch, item_id)
    if not it.get("attunement"):
        raise HTTPException(404)
    if on and len(sheet.get("attuned") or []) >= 3:
        raise HTTPException(409, "All 3 attunement slots are in use: end one first.")
    return _set(db, ch, f"attuned:{item_id}", bool(on), f"{it['name']} {'attuned' if on else 'no longer attuned'}")


@router.post("/characters/{character_id:int}/items/{item_id:int}/move")
def move(request: Request, character_id: int, item_id: int, to: str = Form(""), db: Session = Depends(get_db)):
    """Into one of the character's bags, or out of them ("me": carried). A bag itself stays where it is."""
    ch, _ = _guard(db, request, character_id)
    sheet, it = _item(db, ch, item_id)
    if it.get("bag"):
        raise HTTPException(404)
    if to == "me":
        value, where = int((ch.snapshot.raw or {}).get("id") or 0), "carried"
    else:
        bag = next((b for b in sheet.get("inventory") or [] if b["key"] == f"item:{to}" and b.get("bag")), None)
        if bag is None:
            raise HTTPException(404)
        value, where = int(to), f"in {bag['name']}"
    return _set(db, ch, f"container:{item_id}", value, f"{it['name']} {where}")


@router.get("/characters/{character_id:int}/coins")
def coins_window(request: Request, character_id: int, db: Session = Depends(get_db)):
    """What Change coins opens, in the roll window."""
    ch, _ = _guard(db, request, character_id)
    return templates.TemplateResponse(request, "_coins_window.html", {"c": ch, "has": _sheet(db, ch).get("currency") or {}, "coins": COINS,
                                                                      "reachable": ddb_bridge.reachable(ch)})


@router.post("/characters/{character_id:int}/coins")
def coins(request: Request, character_id: int, to: str = Form("spend"), coin: str = Form("gp"), amount: str = Form(""), db: Session = Depends(get_db)):
    """Spend or gain coins (Undo is the other of the two)."""
    ch, _ = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    n = int(amount) if amount.isdigit() else 0
    if coin not in COINS or to not in ("spend", "gain") or not 0 < n <= 100000:
        raise HTTPException(409, "Enter how many coins.")
    if to == "spend" and n > (_sheet(db, ch).get("currency") or {}).get(coin, 0):
        raise HTTPException(409, f"{ch.name} doesn't have {n:,} {coin}.")
    numbers = ddb_bridge.numbers(ch)
    made = ddb_bridge._change(numbers, {"kind": "use", "field": f"coin:{coin}", "delta": n if to == "gain" else -n})
    if not made:
        raise HTTPException(409, "That isn't a change askdnd can make on D&D Beyond.")
    ddb_bridge.add(db, ch, *made, f"{ch.name}: {ddb_bridge.describe(*made, numbers)}")
    db.commit()
    return JSONResponse({"text": f"{'Gained' if to == 'gain' else 'Spent'} {n:,} {coin}", "undo": {"to": "spend" if to == "gain" else "gain", "coin": coin, "amount": n},
                         "undoUrl": f"/characters/{ch.id}/coins", "deliver": web.deliver_now(ch)})
