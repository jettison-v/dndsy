"""Inventory in play (roadmap 1.5): equip, attune and coins, through the bridge. An item's count and charges are counted
in app/resources.py, using one in app/item_use.py.

An item's side panel has Equip, Attune and Move to (another of your bags, or carried); Sheet › Items' purse opens the Coins window (app/coins.py: carried and in bags, Spend · Gain · Move). D&D Beyond keeps all of it, and what it does to
a character's numbers (AC, spells from an item) comes back with its next read. Attunement stops at 3, as the rules do.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import coins, ddb_bridge, web
from app.db import get_db
from app.item_use import _guard as _player, _sheet
from app.templating import templates

router = APIRouter()


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


DOING = ("spend", "gain", "move")


@router.get("/characters/{character_id:int}/coins")
def coins_window(request: Request, character_id: int, do: str = "spend", db: Session = Depends(get_db)):
    """The Coins window, in the roll window: Spend, Gain or Move (docs/mockups/coins/, Brett chose A). A place is chosen
    only once a bag holds coins: until then it's carried coins, as before."""
    ch, _ = _guard(db, request, character_id)
    sheet = _sheet(db, ch)
    every = coins.places(sheet)
    holding = [p for p in every if p["has"]]
    bags_hold = any(p["key"] != coins.CARRIED for p in holding)
    do = do if do in DOING and (do != "move" or len(every) > 1) else "spend"
    pick = holding if do == "spend" else [p for p in every if p["key"] == coins.CARRIED or p["has"]]
    return templates.TemplateResponse(request, "_coins_window.html", {
        "c": ch, "do": do, "every": every, "holding": holding, "pick": pick if bags_hold else [], "can_move": len(every) > 1,
        "coins": coins.LARGEST, "reachable": ddb_bridge.reachable(ch),
        "data": {p["key"]: {"name": p["name"], "coins": p["coins"]} for p in every}})


def _amount(coin: str, amount: str) -> int:
    n = int(amount) if amount.isdigit() else 0
    if coin not in coins.COINS or not 0 < n <= coins.MOST:
        raise HTTPException(409, "Enter how many coins.")
    return n


@router.post("/characters/{character_id:int}/coins")
def change_coins(request: Request, character_id: int, to: str = Form("spend"), coin: str = Form("gp"), amount: str = Form(""),
                 place: str = Form(coins.CARRIED), source: str = Form("", alias="from"), into: str = Form(""), deltas: str = Form(""),
                 db: Session = Depends(get_db)):
    """Spend or gain coins in one place, move them between two, or undo one of those (its corner card's Undo). One
    change for D&D Beyond whatever it takes (app/coins.py): spending a coin the place hasn't got makes change."""
    ch, _ = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    sheet = _sheet(db, ch)
    if to == "undo":
        back = coins.checked(sheet, deltas)
        if back is None:
            raise HTTPException(409, "That can't be undone here.")
        return _made(db, ch, back, "Undone", undo=False)
    n = _amount(coin, amount)
    if to == "move":
        a, b = coins.place(sheet, source), coins.place(sheet, into)
        if a is None or b is None or a is b or a["key"] == b["key"]:
            raise HTTPException(409, "Pick where the coins come from and where they go.")
        if a["coins"][coin] < n:
            raise HTTPException(409, f"{a['name']} has {a['coins'][coin]:,} {coin}.")
        return _made(db, ch, {coins.field(a["key"], coin): -n, coins.field(b["key"], coin): n}, f"Moved {n:,} {coin} from {_where(a)} to {_where(b)}")
    here = coins.place(sheet, place)
    if here is None or to not in ("spend", "gain"):
        raise HTTPException(409, "That bag isn't one of yours.")
    whose = "" if here["key"] == coins.CARRIED else (" from " if to == "spend" else " into ") + here["name"]
    if to == "gain":
        return _made(db, ch, {coins.field(here["key"], coin): n}, f"Gained {n:,} {coin}{whose}")
    spent = coins.spend(here, coin, n)
    if spent is None:
        raise HTTPException(409, f"{ch.name} doesn't have {n:,} {coin}" + ("" if here["key"] == coins.CARRIED else f" in {here['name']}") + ", even making change.")
    return _made(db, ch, spent, f"Spent {n:,} {coin}{whose}{coins.made_change(spent, coin)}")


def _where(p: dict) -> str:
    return "carried" if p["key"] == coins.CARRIED else p["name"]


def _made(db: Session, ch, deltas: dict, said: str, undo: bool = True) -> JSONResponse:
    coins.make(db, ch, deltas, said[0].lower() + said[1:])
    db.commit()
    return JSONResponse({"text": said, **({"undo": coins.undo_of(deltas), "undoUrl": f"/characters/{ch.id}/coins"} if undo else {}),
                         "deliver": web.deliver_now(ch)})
