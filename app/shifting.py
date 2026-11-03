"""Shifting into a Wild Shape form, and leaving it (Brett, 2026-11-03; docs/artifacts/wild-shape-review.html,
docs/mockups/wild-shape-play/ Shift): a form's pill on Battle's Wild Shape row opens a window, like Cast, that says what
shifting takes and does, and Shift makes it.

D&D Beyond has no "in a form" state, so the form itself is askdnd's (`Character.wild_shape`, which every page at the
table hears). What D&D Beyond does keep goes through the bridge: one Wild Shape use spent, and the form's Temporary Hit
Points (your Druid level, 3 × with Circle Forms; they don't add up, so the window offers to keep the ones you have when
they're more). Where the sheet can't be reached, the form still changes and the card says to mark the rest on D&D
Beyond. Leaving is a Bonus Action and changes nothing on D&D Beyond: leftover Temporary Hit Points stay until used (the
2024 rules don't end them with the form). Undo puts back all of it: the form, the use and the Temporary Hit Points.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import characters as chars
from app import ddb_bridge, picks, web
from app import wild_shape as ws
from app.auth import current_user
from app.db import get_db
from app.models import Character
from app.templating import templates

router = APIRouter()


def _guard(db: Session, request: Request, character_id: int) -> tuple[Character, dict]:
    """The character's own player (the form is theirs to take, as on D&D Beyond)."""
    user = current_user(request)
    ch = db.get(Character, character_id)
    if not user or ch is None or not picks.can_edit(db, user, ch):
        raise HTTPException(404)
    return ch, user


def _state(db: Session, ch: Character) -> dict:
    """What shifting works with: the sheet as shown, the druid's Wild Shape, its use's field and the known forms."""
    sheet = ddb_bridge.as_shown(db, ch, chars.character_summary(ch)) or {}
    d = ws.druid(sheet)
    if not d:
        raise HTTPException(404)
    action = next((a for a in sheet.get("actions") or [] if a["name"] == "Wild Shape" and a.get("uses")), None)
    beasts = ws.beasts(db, ch.campaign_id)
    return {"sheet": sheet, "druid": d, "field": f"uses:{action['id']}" if action and action.get("id") else None,
            "uses": action["uses"] if action else None, "known": {f["name"].lower(): f["name"] for f in ws.known_forms(sheet, beasts)},
            "temp": int((sheet.get("hit_points") or {}).get("temp") or 0), "bridge": ddb_bridge.plays(db, ch) and ddb_bridge.reachable(ch)}


@router.get("/characters/{character_id:int}/wild-shape")
def window(request: Request, character_id: int, form: str = "", db: Session = Depends(get_db)):
    """Shift into a known form (`form`), or leave the one you're in (no `form`): what it takes and does."""
    ch, _ = _guard(db, request, character_id)
    st = _state(db, ch)
    name = st["known"].get(form.lower()) if form else None
    if form and not name:
        raise HTTPException(404)
    if not form and not ch.wild_shape:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "_shift_window.html", {
        "c": ch, "name": name, "now": ch.wild_shape, "d": st["druid"], "uses": st["uses"], "temp": st["temp"], "bridge": st["bridge"],
        "conc": (ch.concentration or {}).get("spell", "")})


@router.post("/characters/{character_id:int}/wild-shape")
def shift(request: Request, character_id: int, form: str = Form(""), to: str = Form("shift"), temp: str = Form("take"),
          was: str = Form(""), spent: str = Form(""), temp_was: str = Form(""), db: Session = Depends(get_db)):
    """Shift (`to` "shift", into `form`), leave ("leave"), or put back what one of those did ("undo", with what it
    answered)."""
    ch, _ = _guard(db, request, character_id)
    form = form or request.query_params.get("form", "")  # (the window posts to its own address: ?form=…)
    st = _state(db, ch)
    numbers = ddb_bridge.numbers(ch) if st["bridge"] else None

    def bridge(kind: str, data: dict, label: str) -> bool:
        """A change for D&D Beyond where the sheet can be reached: a count through _change (as Resources does),
        Temporary Hit Points as the hit points window makes them."""
        if not numbers:
            return False
        made = (kind, data) if kind == "temp" else ddb_bridge._change(numbers, {"kind": kind, **data})
        if made:
            ddb_bridge.add(db, ch, *made, label)
        return bool(made)

    if to == "undo":
        ch.wild_shape = st["known"].get(was.lower()) if was else None
        if spent and st["field"]:
            bridge("use", {"field": st["field"], "delta": -1}, f"{ch.name}: Wild Shape use back")
        if temp_was.isdigit():
            bridge("temp", {"value": int(temp_was)}, f"{ch.name}: {temp_was} Temporary Hit Points")
        db.commit()
        return JSONResponse({"text": f"Undone: {ch.name} is {'a ' + ch.wild_shape if ch.wild_shape else 'back in their own form'}",
                             "deliver": web.deliver_now(ch)})
    if to == "leave":
        if not ch.wild_shape:
            raise HTTPException(409, f"{ch.name} isn't in a form.")
        left = ch.wild_shape
        ch.wild_shape = None
        db.commit()
        stay = f"; {st['temp']} Temporary Hit Points stay" if st["temp"] else ""
        return JSONResponse({"text": f"{ch.name} left the {left} form{stay}", "undo": {"to": "undo", "was": left},
                             "undoUrl": f"/characters/{ch.id}/wild-shape"})
    name = st["known"].get(form.lower())
    if to != "shift" or not name:
        raise HTTPException(404)
    uses = st["uses"]
    if uses is not None and uses.get("left", 0) <= 0:
        raise HTTPException(409, "No Wild Shape uses left: they come back on a Rest (one on a Short Rest, all on a Long Rest).")
    before, gives = ch.wild_shape, st["druid"]["temp_hp"]
    take = temp != "keep" and gives > st["temp"]
    ch.wild_shape = name
    used = bool(st["field"]) and bridge("use", {"field": st["field"], "delta": 1}, f"{ch.name}: Wild Shape used ({name})")
    gave = take and bridge("temp", {"value": gives}, f"{ch.name}: {gives} Temporary Hit Points (Wild Shape)")
    db.commit()
    if st["bridge"]:
        text = f"{ch.name} is a {name}: 1 Wild Shape use spent" + (f", {gives} Temporary Hit Points" if gave else f", kept {st['temp']} Temporary Hit Points")
    else:
        text = (f"{ch.name} is a {name}. The sheet can't be reached: mark 1 Wild Shape use" + (f" and {gives} Temporary Hit Points" if take else "")
                + " on D&D Beyond")
    undo = {"to": "undo", "was": before or "", "spent": "1" if used else "", "temp_was": str(st["temp"]) if gave else ""}
    return JSONResponse({"text": text, "undo": undo, "undoUrl": f"/characters/{ch.id}/wild-shape", "deliver": web.deliver_now(ch)})


def shown_name(ch: Character) -> str:
    """How the table names a character: "Cole (Polar Bear)" in a form (Party, the fight's rows, Table rolls)."""
    return f"{ch.name} ({ch.wild_shape})" if ch.wild_shape else ch.name

