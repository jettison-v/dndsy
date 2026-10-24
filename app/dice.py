"""Each person's dice (Brett, 2026-10-23; docs/mockups/dice-two-ways.html): thrown 3D dice in their own set.

The dice are @3d-dice/dice-box-threejs 0.0.12 (MIT), vendored in app/static/vendor/; app.js throws them. A roll's
numbers still come from askdnd (the server for table rolls, the browser for private ones); the dice are made to land
on them. Where they're thrown:
- your own roll: across the whole page, which dims behind them;
- someone else's roll on a character page: a small tray in the bottom-left corner;
- with the VTT piece "table_dice" (app/vtt.py) on: everyone's rolls are thrown across the page.
Everyone sees your rolls in your set; damage dice can take their damage type's look instead (`by_type`).
"""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, web
from app.db import get_db
from app.models import User
from app.templating import templates

router = APIRouter()

# The library's own colorsets on offer: (key, name). Their swatch colors are tokens in app.css (--set-<key>).
SETS = [("astralsea", "Astral Sea"), ("bloodmoon", "Blood Moon"), ("dragons", "Here be Dragons"), ("starynight", "Starry Night"),
        ("glitterparty", "Glitter Party"), ("bronze", "Thylean Bronze"), ("fire", "Fire"), ("ice", "Ice"), ("radiant", "Radiant"),
        ("necrotic", "Necrotic"), ("poison", "Poison"), ("black", "Black"), ("white", "White"), ("rainbow", "Rainbow")]
MATERIALS = ["glass", "plastic", "metal", "wood"]
# Until someone chooses, each person gets one of these (by account), so the table's dice differ from the start
DEFAULTS = ["dragons", "starynight", "bloodmoon", "bronze", "astralsea", "glitterparty"]


def prefs(user: User | None) -> dict:
    """Their dice: {"set", "material", "by_type"}; askdnd's default where they haven't chosen."""
    d = (user.dice if user is not None else None) or {}
    keys = {k for k, _ in SETS}
    default = DEFAULTS[(user.id or 0) % len(DEFAULTS)] if user is not None else "white"
    return {"set": d.get("set") if d.get("set") in keys else default,
            "material": d.get("material") if d.get("material") in MATERIALS else "glass",
            "by_type": d.get("by_type", True) is not False}


def mine() -> dict:
    """The dice of the person asking (from the access cache), for the page's data-dice."""
    row = access._rows().get(access.viewer.get() or "", {})
    return row.get("dice") or prefs(None)


def _me(db: Session, request: Request) -> tuple[User | None, HTMLResponse | None]:
    user, denied = web.require(request)
    if denied:
        return None, denied
    return db.scalar(select(User).where(func.lower(User.email) == user["email"].lower())), None


@router.get("/dice")
def picker(request: Request, db: Session = Depends(get_db)):
    """Choose your dice (a window from the Table rolls sidebar or your account menu)."""
    me, stop = _me(db, request)
    if stop:
        return stop
    return templates.TemplateResponse(request, "_dice_picker.html", {"d": prefs(me), "sets": SETS, "materials": MATERIALS})


@router.post("/dice")
def save(request: Request, set: str = Form(""), material: str = Form(""), by_type: str = Form(""), db: Session = Depends(get_db)):
    me, stop = _me(db, request)
    if stop:
        return stop
    if me is None:
        return web.forbidden(request, "Sign in again to choose your dice.")
    me.dice = {"set": set if set in {k for k, _ in SETS} else prefs(me)["set"],
               "material": material if material in MATERIALS else "glass", "by_type": bool(by_type)}
    db.commit()
    access.invalidate()
    name = dict(SETS)[me.dice["set"]]
    resp = HTMLResponse("")
    resp.headers["HX-Trigger"] = json.dumps({"toast": f"Your dice: {name}", "diceChanged": prefs(me)})  # app.js closes the window
    return resp
