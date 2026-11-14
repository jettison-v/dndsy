"""Changing prepared spells (Brett, 2026-11-02): a spell's side panel has Prepare or Unprepare, confirmed in the roll
window, and the change goes to D&D Beyond through the bridge (app/ddb_fields.py "prep", the request D&D Beyond's own
sheet sends, seen on the test sheet the same day). Prepare spells (`/characters/<id>/spells/prepare`, Brett 2026-11-02,
docs/mockups/prepare-spells/) is a large modal like the Spell Book for the lot: tick and untick with the count in view
and your notes on each spell, then one Make for all the changes.

Only for a class that prepares from a list (a cleric, a druid, a wizard from the spellbook), and only a spell of 1st
level or higher. The window says how many are prepared and the class's number at its level; going over is allowed, as
D&D Beyond allows it, and said so: when and how many is the DM's ruling, not askdnd's.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import components, ddb_bridge, picks, web
from app import spellbook as sb
from app.db import get_db
from app.inventory import _guard
from app.item_use import _sheet
from app.templating import templates

router = APIRouter()


def _find(sheet: dict, key: str) -> tuple[dict, dict]:
    """The spell (with what preparing it names) and its class's list, or Not found."""
    for book in sheet.get("spellbook") or []:
        for sp in book.get("spells") or []:
            if sp.get("key") == key and sp.get("prep"):
                return sp, book
    raise HTTPException(404)


def _count(book: dict) -> str:
    have, most = book.get("prepared_count") or 0, book.get("prepared_max")
    return f"{have} of {most} prepared" if most else f"{have} prepared"


@router.get("/characters/{character_id:int}/prepare")
def prepare_window(request: Request, character_id: int, key: str, db: Session = Depends(get_db)):
    """Prepare or Unprepare, from the spell's side panel."""
    ch, _ = _guard(db, request, character_id)
    sp, book = _find(_sheet(db, ch), key)
    on = sp["state"] == "prepared"
    most = book.get("prepared_max")
    over = not on and most and (book.get("prepared_count") or 0) >= most
    return templates.TemplateResponse(request, "_prepare_window.html", {
        "c": ch, "sp": sp, "book": book, "on": on, "count": _count(book), "over": over, "reachable": ddb_bridge.reachable(ch)})


@router.post("/characters/{character_id:int}/prepare")
def prepare(request: Request, character_id: int, key: str, to: str = Form(...), db: Session = Depends(get_db)):
    """Prepare it or unprepare it (Undo is the other of the two)."""
    ch, _ = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    if to not in ("prepare", "unprepare"):
        raise HTTPException(404)
    sp, book = _find(_sheet(db, ch), key)
    want = to == "prepare"
    if (sp["state"] == "prepared") == want:
        raise HTTPException(409, f"{sp['name']} is {'already' if want else 'not'} prepared.")
    data = {**sp["prep"], "value": want, "name": sp["name"]}
    text = f"{ch.name}: {ddb_bridge.describe('prepare', data, {})}"
    ddb_bridge.add(db, ch, "prepare", data, text)
    db.commit()
    return JSONResponse({"text": text, "undo": {"to": "unprepare" if want else "prepare"},
                         "undoUrl": f"/characters/{ch.id}/prepare?key={quote(sp['key'])}", "deliver": web.deliver_now(ch)})


# ------------------------------------------------------------------ the Prepare spells screen

# When a class may change its prepared spells, by the 2024 Player's Handbook (said, never enforced: the DM rules)
RULES = {
    "Cleric": "After a Long Rest you can change any of your prepared spells, choosing from Cleric spells of a level you have slots for.",
    "Druid": "After a Long Rest you can change any of your prepared spells, choosing from Druid spells of a level you have slots for.",
    "Wizard": "After a Long Rest you can change any of your prepared spells, choosing from the spells in your spellbook.",
    "Paladin": "After a Long Rest you can replace one spell on your list with another Paladin spell.",
    "Ranger": "After a Long Rest you can replace one spell on your list with another Ranger spell.",
    "Bard": "When you gain a Bard level you can replace one spell on your list.",
    "Sorcerer": "When you gain a Sorcerer level you can replace one spell on your list.",
    "Warlock": "When you gain a Warlock level you can replace one spell on your list.",
}
# The same, in the few words the window's header has room for (the whole sentence on hover)
SHORT = {"Cleric": "change any after a Long Rest", "Druid": "change any after a Long Rest",
         "Wizard": "change any from your spellbook after a Long Rest", "Paladin": "replace one after a Long Rest",
         "Ranger": "replace one after a Long Rest", "Bard": "replace one when you gain a level",
         "Sorcerer": "replace one when you gain a level", "Warlock": "replace one when you gain a level"}
ORDINAL = {1: "1st", 2: "2nd", 3: "3rd"}


def books_to_prepare(sheet: dict) -> list[dict]:
    """The classes whose spells can be prepared from askdnd (any of their spells names what preparing it needs)."""
    return [b for b in sheet.get("spellbook") or [] if any(sp.get("prep") for sp in b.get("spells") or [])]


def _what(sp: dict) -> str:
    return " · ".join(x for x in (sp.get("damage") or (f"heals {sp['healing']}" if sp.get("healing") else ""), sp.get("range") or "") if x)


@router.get("/characters/{character_id:int}/spells/prepare")
def prepare_screen(request: Request, character_id: int, cls: str = "", db: Session = Depends(get_db)):
    ch, user = _guard(db, request, character_id)
    sheet = _sheet(db, ch)
    books = books_to_prepare(sheet)
    if not books:
        raise HTTPException(404)
    book = next((b for b in books if b["class"] == cls), books[0])
    noting = picks.can_see(user, ch)
    mine = picks.picks(db, ch, user) if noting else {"fav": [], "notes": {}}
    fav, notes = set(mine["fav"]), mine.get("notes") or {}
    on_way = {k for k, v in (sheet.get("sync") or {}).items() if k.startswith("prep:") and v == "on"}
    rows, comp_rules = [], components.rules_for(ch.campaign_id)
    for sp in book["spells"]:
        if not sp["level"] or not (sp.get("prep") or sp["state"] == "always"):
            continue
        p = sp.get("prep") or {}
        rows.append({"key": sp["key"], "name": sp["name"], "level": sp["level"], "time": {"Bonus action": "Bonus"}.get(sp.get("casting_time"), sp.get("casting_time") or ""),
                     "effect": dict(sb.EFFECTS).get(sb.effect_of(sp), ""), "conc": sp.get("concentration"), "what": _what(sp),
                     "always": sp["state"] == "always", "on": sp["state"] in ("prepared", "always"), "fav": sp["key"] in fav,
                     "note": notes.get(sp["key"], ""), "need": components.need(sp, sheet, comp_rules),
                     "going": f"prep:{p.get('cls')}:{p.get('entry')}" in on_way})
    levels = sorted({r["level"] for r in rows})
    return templates.TemplateResponse(request, "_prepare_spells.html", {
        "c": ch, "book": book, "books": books, "rows": rows, "levels": [(lv, ORDINAL.get(lv, f"{lv}th")) for lv in levels],
        "effects": [label for _, label in sb.EFFECTS if any(r["effect"] == label for r in rows)],
        "rule": RULES.get(book["class"], ""), "short": SHORT.get(book["class"], ""), "reachable": ddb_bridge.reachable(ch),
        "noting": noting})


@router.post("/characters/{character_id:int}/spells/prepare")
def prepare_many(request: Request, character_id: int, body=web.JsonBody, db: Session = Depends(get_db)):
    """Make the screen's changes, one bridge change each (they go to D&D Beyond together, as one batch)."""
    ch, _ = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    wanted = body.get("changes") if isinstance(body, dict) else None
    if not isinstance(wanted, list) or not wanted or len(wanted) > 60:
        raise HTTPException(409, "Nothing to change.")
    sheet = _sheet(db, ch)
    made, gone = [], 0
    for w in wanted:
        if not isinstance(w, dict) or not isinstance(w.get("key"), str) or not isinstance(w.get("on"), bool):
            raise HTTPException(409, "That isn't a change askdnd can make on D&D Beyond.")
        try:
            sp, _book = _find(sheet, w["key"])
        except HTTPException:
            gone += 1  # (a cantrip, or no longer on the class's list: changed on D&D Beyond meanwhile)
            continue
        if (sp["state"] == "prepared") == w["on"]:
            continue  # (already so: someone made it on D&D Beyond meanwhile)
        data = {**sp["prep"], "value": w["on"], "name": sp["name"]}
        ddb_bridge.add(db, ch, "prepare", data, f"{ch.name}: {ddb_bridge.describe('prepare', data, {})}")
        made.append(sp["name"] if w["on"] else f"not {sp['name']}")
    db.commit()
    n = len(made)
    text = f"{n} change{'s' if n != 1 else ''} on its way to D&D Beyond" if n else "Nothing to change: D&D Beyond has it already"
    if gone:
        text += f"; {gone} spell{'s' if gone != 1 else ''} can't be prepared from askdnd, left as {'they are' if gone != 1 else 'it is'}"
    return {"text": text, "deliver": web.deliver_now(ch)}
