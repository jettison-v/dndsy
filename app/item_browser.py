"""The item browser (Brett, 2026-11-03; docs/mockups/item-browser/): one large window over D&D Beyond's 2024 items, from
Sheet › Items. A character's own player opens it as **Add item** (bought in town, found on the road, paying from the
purse if they choose); its DM as **Give loot** (no cost, coins too). Search and filter by kind, rarity, attunement and
book, see what an item is before adding it, put several in Adding, choose the bag, then one Add makes them all on D&D
Beyond through the bridge (app/giving.py's add_item, the request the sheet itself sends).

Prices only where D&D Beyond has one (plain gear, from the books): no magic item has one, and nothing is suggested
(Brett: the DM sets them and may not want ranges shown). What's paid is a box the player types in, for whatever the DM
agrees. Not yet: homebrew, an item changed for the campaign, and the DM's shops, which the browser is laid out to take
(docs/mockups/item-browser/ board 4).
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import coins as purse_coins
from app import ddb_bridge, item_fit, picks, realtime, web
from app.auth import current_user, is_admin, is_dm
from app.coins import COINS, money, parse_money
from app.db import get_db
from app.giving import catalog
from app.item_use import _sheet
from app.models import Character
from app.templating import templates

router = APIRouter()
RARITY_ORDER = ("Not magic", "Common", "Uncommon", "Rare", "Very Rare", "Legendary", "Artifact", "Varies")


def _mode(db: Session, request: Request, character_id: int) -> tuple[Character, dict, str]:
    """"add" for the character's own player, "loot" for its DM (or an admin); only where the bridge plays."""
    user = current_user(request)
    ch = db.get(Character, character_id)
    if not user or ch is None or not ddb_bridge.plays(db, ch):
        raise HTTPException(404)
    if picks.can_edit(db, user, ch):
        return ch, user, "add"
    if is_admin(user) or is_dm(user, ch.campaign_id):
        return ch, user, "loot"
    raise HTTPException(404)


# For the character (feedback 13, Brett, Nov 4: "filter by whether you are proficient and can use the item"): the row's
# icon as a filter. A catch is a cost the rules attach (not proficient, Strength, attunement…), never "can't" (item_fit)
NO_CATCH, CATCH = "No catch", "Has a catch"


def _have(sheet: dict) -> dict[int, int]:
    """How many of each D&D Beyond item the character has, by its definition."""
    have: dict[int, int] = {}
    for it in sheet.get("inventory") or []:
        if did := it.get("definition_id"):
            have[did] = have.get(did, 0) + (it.get("count") or 0)
    return have


def _row(i: dict, have: dict[int, int], sheet: dict | None = None, who: str = "") -> dict:
    """One item as the browser lists it, with what it would mean for the character (app/item_fit.py: the row's icon, the
    details' For <character>)."""
    fit = item_fit.fit(sheet, i, who)
    return {**i, "have": have.get(i["id"], 0), "price": money(i["cost_cp"]) if i.get("cost_cp") else "", "fit": fit,
            "weight_label": f"{i['weight']:g} lb" if i.get("weight") else "",
            "f": {"kind": i["kind"], "rarity": i["rarity"], "attune": "Needs attunement" if i["attune"] else "No attunement", "book": i["book"],
                  "fit": CATCH if fit["icon"] == "warn" else NO_CATCH}}


@router.get("/characters/{character_id:int}/items/browse")
def browse(request: Request, character_id: int, db: Session = Depends(get_db)):
    """The browser, in a large window: Add item (the player's own) or Give loot (the DM's)."""
    ch, _, mode = _mode(db, request, character_id)
    sheet = _sheet(db, ch)
    have, who = _have(sheet), ch.name.split()[0]
    rows = [_row(i, have, sheet, who) for i in catalog()]
    groups = [{"key": "kind", "label": "Kind", "values": sorted({r["f"]["kind"] for r in rows})},
              {"key": "fit", "label": f"For {who}", "values": [NO_CATCH, CATCH]},  # (feedback 13: what the character can use)
              {"key": "rarity", "label": "Rarity", "values": [v for v in RARITY_ORDER if any(r["f"]["rarity"] == v for r in rows)]},
              {"key": "attune", "label": "Attunement", "values": ["Needs attunement", "No attunement"]},
              {"key": "book", "label": "Book", "values": sorted({r["f"]["book"] for r in rows if r["f"]["book"]}), "more": True}]
    bags = [b for b in sheet.get("inventory") or [] if b.get("bag") and b["key"].startswith("item:")]
    holding = [p for p in purse_coins.places(sheet) if p["has"]]  # (Pay from: a choice once a bag holds coins too)
    return templates.TemplateResponse(request, "_item_browser.html", {
        "c": ch, "mode": mode, "rows": rows, "groups": groups, "bags": bags, "sheet": sheet, "coins": purse_coins.LARGEST,
        "pay_places": holding if any(p["key"] != purse_coins.CARRIED for p in holding) else [],
        "reachable": ddb_bridge.reachable(ch), "loaded": bool(rows)})


@router.get("/characters/{character_id:int}/items/browse/{definition_id:int}")
def detail(request: Request, character_id: int, definition_id: int, db: Session = Depends(get_db)):
    """What one item is, beside the list: its picture, numbers, book and D&D Beyond's own words."""
    ch, _, mode = _mode(db, request, character_id)
    item = next((i for i in catalog() if i["id"] == definition_id), None)
    if item is None:
        raise HTTPException(404)
    sheet = _sheet(db, ch)
    return templates.TemplateResponse(request, "_item_browser_detail.html", {"c": ch, "mode": mode, "i": _row(item, _have(sheet), sheet, ch.name.split()[0])})


@router.post("/characters/{character_id:int}/items/add")
def add(request: Request, character_id: int, body=web.JsonBody, db: Session = Depends(get_db)):
    """Everything in Adding at once: each item into the chosen bag (or carried), then what's paid off the purse (Add
    item, if ticked) or the coins given with it (Give loot). All through the bridge, as one batch."""
    ch, _, mode = _mode(db, request, character_id)
    ddb_bridge.reach(ch)
    body = body if isinstance(body, dict) else {}
    by_id = {i["id"]: i for i in catalog()}
    wanted = []
    for row in body.get("items") or []:
        try:
            did, n = int(row.get("id")), int(row.get("n"))
        except (TypeError, ValueError, AttributeError):
            raise HTTPException(409, "Something in Adding isn't an item.") from None
        if did not in by_id or not 0 < n <= 100:
            raise HTTPException(409, "Pick items from the list, 1 to 100 of each.")
        wanted.append((by_id[did], n))
    sheet = _sheet(db, ch)
    into = str(body.get("into") or "")
    bag = next((b for b in sheet.get("inventory") or [] if b.get("bag") and b["key"] == f"item:{into}"), None) if into else None
    if into and bag is None:
        raise HTTPException(409, "That bag isn't one of yours.")
    cp, paid, coins, payer = 0, {}, None, None  # (worked out before anything's made, so a refusal makes nothing)
    if mode == "add" and body.get("pay"):
        cp = parse_money(str(body.get("pay")))
        if cp is None:
            raise HTTPException(409, "Write what you pay as coins: 2 gp 1 sp, 21 sp or 2.1 gp.")
        payer = purse_coins.place(sheet, str(body.get("from") or purse_coins.CARRIED))  # (Pay from: carried, or a bag)
        if payer is None:
            raise HTTPException(409, "That bag isn't one of yours.")
        after = purse_coins.pay_from(payer["coins"], cp) if cp else payer["coins"]
        if after is None:
            raise HTTPException(409, f"{ch.name} doesn't have {money(cp)}" + ("." if payer["key"] == purse_coins.CARRIED else f" in {payer['name']}."))
        paid = {purse_coins.field(payer["key"], c): after[c] - payer["coins"][c] for c in COINS if cp and after[c] != payer["coins"][c]}
    if mode == "loot" and str(body.get("amount") or "").strip():
        m, coin = str(body["amount"]).strip(), str(body.get("coin") or "gp")
        if not m.isdigit() or coin not in COINS or not 0 < int(m) <= 100000:
            raise HTTPException(409, "Enter how many coins.")
        coins = (coin, int(m))
    if not wanted and not coins:
        raise HTTPException(409, "Add something first: + on an item puts it in Adding.")
    numbers = ddb_bridge.numbers(ch)
    changes = [ddb_bridge._change(numbers, {"kind": "use", "field": f"coin:{coins[0]}", "delta": coins[1]})] if coins else []
    if not all(changes):
        raise HTTPException(409, "That isn't a change askdnd can make on D&D Beyond.")
    said = []
    for item, n in wanted:
        what = item["name"] + (f" ×{n}" if n > 1 else "")
        data = {"definition": item["id"], "entityTypeId": item["entityTypeId"], "quantity": n, "name": item["name"], **({"container": int(into)} if bag else {})}
        ddb_bridge.add(db, ch, "add_item", data, f"{ch.name} got {what}" + (" from the DM" if mode == "loot" else ""))
        said.append(what)
    if paid:
        purse_coins.make(db, ch, paid, f"paid {money(cp)}" + ("" if payer["key"] == purse_coins.CARRIED else f" from {payer['name']}"))
    for made in changes:
        ddb_bridge.add(db, ch, *made, f"{ch.name} got {coins[1]:,} {coins[0]} from the DM")
    if coins:
        said.append(f"{coins[1]:,} {coins[0]}")
    realtime.announce(db, ch.campaign_id, "character", id=ch.id)
    db.commit()
    where = f" into {bag['name']}" if bag else ""
    text = (f"{' and '.join(said)} to {ch.name}" if mode == "loot" else f"{ch.name} got {', '.join(said)}{where}" + (f", paid {money(cp)}" + ("" if payer["key"] == purse_coins.CARRIED else f" from {payer['name']}") if paid else ""))
    return JSONResponse({"text": text + ": on its way to D&D Beyond", "deliver": web.deliver_now(ch)})
