"""Counting things in play (roadmap 1.3): a class resource, a feat's uses, a spell slot spent by hand, each through the bridge.

Battle's Resources row (and the spell bar's slots) opens a small window like an item's (app.js "using an item"): how many
are left, when they come back, Use one and Give one back. D&D Beyond keeps the count; askdnd says what it asked for and
shows it as made until D&D Beyond has it, as with any bridge change. Nothing here decides when a resource is spent.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import ddb_bridge, hit_points, web
from app.character_views import ordinal
from app.db import get_db
from app.item_use import _guard as _player, _sheet
from app.templating import templates

router = APIRouter()


def _guard(db: Session, request: Request, character_id: int):
    ch, user = _player(db, request, character_id)
    if not ddb_bridge.plays(db, ch):
        raise HTTPException(404)
    return ch, user


def count(sheet: dict, field: str) -> dict | None:
    """{"name", "left", "max", "back"} of what `field` counts, as shown, or None: uses:<action id>, slot:<level>, pact:<level>."""
    kind, _, arg = field.partition(":")
    ss = sheet.get("spell_slots") or {}
    if kind == "uses":
        a = next((a for a in sheet.get("actions") or [] if a.get("uses") and str(a.get("id")) == arg), None)
        return {"name": a["name"], "left": a["uses"]["left"], "max": a["uses"]["max"], "back": a["uses"].get("reset_phrase", "")} if a else None
    if kind == "slot":
        s = next((s for s in ss.get("slots") or [] if str(s["level"]) == arg and s.get("max")), None)
        return {"name": f"{ordinal(s['level'])}-level", "left": s["max"] - s["used"], "max": s["max"], "back": "back after a Long Rest"} if s else None
    if kind == "charges":
        it = next((x for x in sheet.get("inventory") or [] if x["key"] == f"item:{arg}" and x.get("charges")), None)
        return {"name": it["name"], "left": it["charges"]["left"], "max": it["charges"]["max"], "back": it["charges"].get("reset_phrase", "")} if it else None
    if kind == "item":
        it = next((x for x in sheet.get("inventory") or [] if x["key"] == field), None)
        return {"name": it["name"], "left": it["count"], "max": None, "back": ""} if it else None
    if kind == "pact":
        p = ss.get("pact")
        if p and str(p["level"]) == arg:
            return {"name": f"Pact Magic ({ordinal(p['level'])}-level)", "left": p["max"] - p["used"], "max": p["max"], "back": "back after a Short or Long Rest"}
    return None


@router.get("/characters/{character_id:int}/count")
def window(request: Request, character_id: int, field: str, db: Session = Depends(get_db)):
    """What a resource opens, in the roll window."""
    ch, _ = _guard(db, request, character_id)
    n = count(_sheet(db, ch), field)
    if not n:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "_count_window.html", {"c": ch, "n": n, "reachable": ddb_bridge.reachable(ch)})


@router.post("/characters/{character_id:int}/count")
def change(request: Request, character_id: int, field: str, to: str = Form("use"), db: Session = Depends(get_db)):
    """Use one, or give one back (Undo is the other of the two)."""
    ch, _ = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    n = count(_sheet(db, ch), field)
    if not n or to not in ("use", "back"):
        raise HTTPException(404)
    if (to == "use" and n["left"] <= 0) or (to == "back" and n["max"] is not None and n["left"] >= n["max"]):
        raise HTTPException(409, f"{n['name']}: none left." if to == "use" else f"{n['name']}: none to give back.")
    delta = 1 if to == "use" else -1
    numbers = ddb_bridge.numbers(ch)
    if field.startswith("item:"):  # (an item's count goes down as it's used, where the others count what's used)
        made = "item", {"item": int(field.split(":", 1)[1]), "delta": -delta, "name": n["name"]}
    else:
        made = ddb_bridge._change(numbers, {"kind": "use", "field": field, "delta": delta})
    if not made:
        raise HTTPException(409, "That isn't a change askdnd can make on D&D Beyond.")
    ddb_bridge.add(db, ch, *made, f"{ch.name}: {n['name']} {'used' if to == 'use' else 'back'}")
    db.commit()
    left = n["left"] - delta
    return JSONResponse({"text": f"{n['name']}: {left}" + (f" of {n['max']}" if n["max"] else "") + " left", "undo": {"to": "back" if to == "use" else "use"},
                         "undoUrl": f"/characters/{ch.id}/count?field={field}", "deliver": web.deliver_now(ch)})


@router.get("/characters/{character_id:int}/inspiration")
def inspiration_window(request: Request, character_id: int, db: Session = Depends(get_db)):
    """Heroic Inspiration's star: spend it or give it, confirmed in the roll window. The player, or the DM, who awards it."""
    ch, _ = hit_points._guard(db, request, character_id)
    return templates.TemplateResponse(request, "_insp_window.html", {
        "c": ch, "have": bool(_sheet(db, ch).get("inspiration")), "reachable": ddb_bridge.reachable(ch)})


@router.post("/characters/{character_id:int}/inspiration")
def inspiration_change(request: Request, character_id: int, to: str = Form(...), db: Session = Depends(get_db)):
    """Spend it or give it (Undo is the other of the two)."""
    ch, _ = hit_points._guard(db, request, character_id)
    ddb_bridge.reach(ch)
    if to not in ("spend", "gain"):
        raise HTTPException(404)
    have = to == "gain"
    if bool(_sheet(db, ch).get("inspiration")) == have:
        raise HTTPException(409, f"{ch.name} {'already has' if have else 'no longer has'} Heroic Inspiration.")
    made = ddb_bridge._change(ddb_bridge.numbers(ch), {"kind": "set", "field": "inspiration", "value": have})
    if not made:
        raise HTTPException(409, "That isn't a change askdnd can make on D&D Beyond.")
    text = f"{ch.name}: Heroic Inspiration {'given' if have else 'spent'}"
    ddb_bridge.add(db, ch, *made, text)
    db.commit()
    return JSONResponse({"text": text, "undo": {"to": "spend" if have else "gain"}, "undoUrl": f"/characters/{ch.id}/inspiration",
                         "deliver": web.deliver_now(ch)})

