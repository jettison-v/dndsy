"""Casting a spell in play (roadmap 1.2; Brett, 2026-10-30: build it, the interface is reviewed afterwards).

A spell's Cast opens a small window like an item's (app.js "using an item"): the ways it can be cast now, and Cast. Only
where the bridge works and only for the character's own player, as with items:

- **A slot** spends that level's spell slot or Pact Magic slot on D&D Beyond (a spell can always use a higher slot).
- **As a Ritual** and **No slot** spend nothing: a Ritual for a spell that has the tag, No slot for anything else that
  pays for it (a feature, an item). askdnd doesn't decide which applies.
- **Concentration** starts by itself and ends the one before, as at the table; the window says so first.
- **Undo** on the corner card gives the slot back and puts the earlier Concentration back.

Rolling stays its own step: casting isn't always a roll, and a roll isn't always a cast.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import ddb_bridge, ddb_sheet, web
from app import spellbook as sb
from app.character_views import ordinal
from app.db import get_db
from app.item_use import _guard, _sheet
from app.models import Character
from app.templating import templates

router = APIRouter()
RITUAL, NO_SLOT = "ritual", "none"


def ways(sheet: dict, e: dict) -> list[dict]:
    """How this spell can be cast now, the lowest slot first: {"way", "label", "level"}, with what a higher slot rolls."""
    out = []
    for s in sb.slot_levels(sheet):
        if e["level"] and s["level"] >= e["level"] and s["left"] > 0:
            a = e["avgs"].get(s["level"])
            kind = "pact" if s.get("pact") else "slot"
            out.append({"way": f"{kind}:{s['level']}", "level": s["level"], "name": f"{ordinal(s['level'])}-level",
                        "label": f"{ordinal(s['level'])}-level{' Pact' if s.get('pact') else ''} ({s['left']} left)" + (f" · {a['dice']}" if a else "")})
    if e["ritual"]:
        out.append({"way": RITUAL, "level": e["level"], "name": "a Ritual", "label": "As a Ritual (no slot, 10 minutes longer)"})
    if e["level"]:
        out.append({"way": NO_SLOT, "level": e["level"], "name": "", "label": "No slot"})
    return out


def _spell(db: Session, ch: Character, key: str) -> tuple[dict, dict]:
    sheet = _sheet(db, ch)
    e = next((x for x in sb.entries(sheet) if x["key"] == key), None)
    if e is None:
        raise HTTPException(404)
    return sheet, e


@router.get("/characters/{character_id:int}/cast")
def window(request: Request, character_id: int, key: str, db: Session = Depends(get_db)):
    """What a spell's Cast opens, in the roll window."""
    ch, _ = _guard(db, request, character_id)
    sheet, e = _spell(db, ch, key)
    return templates.TemplateResponse(request, "_cast_window.html", {"c": ch, "e": e, "ways": ways(sheet, e), "reachable": ddb_bridge.reachable(ch),
                                                                     "ends": ch.concentration if e["conc"] and ch.concentration and ch.concentration.get("key") != key else None})


@router.post("/characters/{character_id:int}/cast")
def cast(request: Request, character_id: int, key: str, way: str = Form(""), db: Session = Depends(get_db)):
    """Cast it: the slot on its way to D&D Beyond, Concentration begun."""
    ch, _ = _guard(db, request, character_id)
    sheet, e = _spell(db, ch, key)
    can = ways(sheet, e)
    chosen = next((w for w in can if w["way"] == way), None)
    if can and not chosen:
        raise HTTPException(409, f"{e['name']}: that slot isn't left.")
    undo = {"key": key}
    said = f"Cast {e['name']}" + (f" as {chosen['name']}" if chosen and chosen["way"] == RITUAL else f" at {chosen['name']}" if chosen and chosen["name"] else "")
    if chosen and chosen["way"] not in (RITUAL, NO_SLOT):
        ddb_bridge.reach(ch)
        _spend(ch, db, chosen["way"], 1, f"{ch.name}: {e['name']}, {chosen['name']} slot")
        undo["spent"] = chosen["way"]
    if e["conc"]:
        was = ch.concentration
        ch.concentration = sb.concentrating(e, chosen["level"] if chosen else e["level"]) | ({"was": {k: v for k, v in was.items() if k != "was"}} if was else {})
        said += f": Concentrating on {e['name']}" + (f", {was['spell']} ended" if was and was.get("key") != key else "")
    db.commit()
    return JSONResponse({"text": said, "undo": undo, "undoUrl": f"/characters/{ch.id}/cast/undo", "deliver": web.deliver_now(ch)})


def _spend(ch: Character, db: Session, way: str, delta: int, label: str) -> None:
    kind, level = way.split(":", 1)
    ddb_bridge.add(db, ch, "use", {"field": way, "delta": delta, "max": ddb_sheet.most(ch.snapshot.raw, kind, level)}, label)


@router.post("/characters/{character_id:int}/cast/undo")
def undo_cast(request: Request, character_id: int, key: str = Form(...), spent: str = Form(""), db: Session = Depends(get_db)):
    """The corner card's Undo: the slot back, and Concentration as it was."""
    ch, _ = _guard(db, request, character_id)
    _, e = _spell(db, ch, key)
    if spent:
        if spent.split(":", 1)[0] not in ("slot", "pact"):
            raise HTTPException(404)
        ddb_bridge.reach(ch)
        _spend(ch, db, spent, -1, f"{ch.name}: {e['name']} undone")
    if ch.concentration and ch.concentration.get("key") == key:
        ch.concentration = ch.concentration.get("was")
    db.commit()
    return JSONResponse({"text": f"{e['name']} undone", "deliver": web.deliver_now(ch)})
