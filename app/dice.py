"""Each person's dice (Brett, 2026-10-23; docs/mockups/dice-two-ways.html): thrown 3D dice in their own set.

The dice are @3d-dice/dice-box-threejs 0.0.12 (MIT), vendored in app/static/vendor/; app.js throws them. A roll's
numbers still come from askdnd (the server for table rolls, the browser for private ones); the dice are made to land
on them. Where they're thrown:
- your own roll: across the whole page, which dims behind them;
- someone else's roll on a character page: a small tray in the bottom-left corner;
- with the VTT piece "table_dice" (app/vtt.py) on: everyone's rolls are thrown across the page.
Everyone sees your rolls in your set; damage dice can take their damage type's look instead (`by_type`).

How the dice move and how long they stay is the same for everyone: admins set it on Manage › askdnd › Dice tuning
(Brett, 2026-10-24; docs/mockups/dice-tuning.html), one setting for each of the three places (`tuning()`).
"""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, web
from app.auth import is_admin
from app.db import get_db
from app.models import ToolSetting, User
from app.templating import templates

router = APIRouter()

# The library's own colorsets on offer: (key, name). Their swatch colors are tokens in app.css (--set-<key>).
SETS = [("astralsea", "Astral Sea"), ("bloodmoon", "Blood Moon"), ("dragons", "Here be Dragons"), ("starynight", "Starry Night"),
        ("glitterparty", "Glitter Party"), ("bronze", "Thylean Bronze"), ("fire", "Fire"), ("ice", "Ice"), ("radiant", "Radiant"),
        ("necrotic", "Necrotic"), ("poison", "Poison"), ("black", "Black"), ("white", "White"), ("rainbow", "Rainbow")]
MATERIALS = ["glass", "plastic", "metal", "wood"]
# Until someone chooses, each person gets one of these (by account), so the table's dice differ from the start
DEFAULTS = ["dragons", "starynight", "bloodmoon", "bronze", "astralsea", "glitterparty"]


# Dice tuning: each knob's (label, what it does, lowest, highest, step, how its value reads: x, %, pct (0.7 → 70%), px, s)
KNOBS = {
    "strength": ("Throw strength", "How hard the dice are thrown. Higher bounces further and tumbles longer.", 0.4, 3, 0.1, "x"),
    "gravity": ("Gravity", "Lower is floatier: the dice hang and take longer to settle (suspense). Higher drops them fast.", 100, 800, 10, ""),
    "size": ("Dice size", "How big the dice look.", 40, 160, 5, "%"),
    "shadows": ("Shadows under the dice", "Off is lighter work for slower computers.", None, None, None, "toggle"),
    "light": ("Light", "How brightly the dice are lit.", 0.3, 1.5, 0.05, "pct"),
    "dim": ("Darkness", "How much the page darkens behind the dice. 0 leaves it as it is.", 0, 90, 5, "%"),
    "blur": ("Blur", "How much the page blurs behind the dice.", 0, 8, 1, "px"),
    "fade_in": ("Fades in over", "The dice, the backdrop and the result appear.", 0, 1, 0.05, "s"),
    "stay": ("Result stays up for", "After the dice land: how long the dice and the total stay before they go.", 0.5, 8, 0.1, "s"),
    "fade_out": ("Fades out over", "Everything goes away.", 0, 1.5, 0.05, "s"),
    "slide": ("Tray slides in and out over", "The dice are thrown once the tray is up.", 0, 1, 0.05, "s"),
}
# The three places dice are thrown: (key, name, when, the knobs in groups)
_PAGE = [("The throw", ["strength", "gravity", "size"]), ("Light", ["shadows", "light"]),
         ("Shadow box: the page behind the dice", ["dim", "blur"]), ("Timing", ["fade_in", "stay", "fade_out"])]
PLACES = [
    ("mine", "Your roll", "You rolled, on any page: your dice are thrown across the whole page, the page behind them goes dark, "
     "and the total lands at the bottom.", _PAGE),
    ("tray", "Others' rolls in the tray", "Someone else rolled while you're on a character page: a small tray slides up in the "
     "corner, their dice tumble in it, and it shows who and the total.",
     [("The throw", ["strength", "gravity", "size"]), ("Light", ["shadows", "light"]), ("Timing", ["slide", "stay"])]),
    ("vtt", "Others' rolls on the VTT", "Someone else rolled while their campaign has the VTT's table dice on: their dice cross "
     "the whole screen with a tag saying who rolled.", _PAGE),
]
# askdnd's own tuning (what it did before the Dice tuning page)
TUNING = {
    "mine": {"strength": 1.4, "gravity": 300, "size": 95, "shadows": True, "light": 0.7, "dim": 55, "blur": 2, "fade_in": 0.2, "stay": 3.2, "fade_out": 0.3},
    "tray": {"strength": 1, "gravity": 400, "size": 60, "shadows": False, "light": 0.7, "slide": 0.3, "stay": 2.6},
    "vtt": {"strength": 1.4, "gravity": 300, "size": 95, "shadows": True, "light": 0.7, "dim": 35, "blur": 0, "fade_in": 0.2, "stay": 3.2, "fade_out": 0.3},
}
TUNING_KEY = "dice_tuning"


def clean_tuning(raw) -> dict:
    """Every place with every knob, each within its range; askdnd's own value where one is missing or unreadable."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for place, knobs in TUNING.items():
        got = raw.get(place) if isinstance(raw.get(place), dict) else {}
        out[place] = {}
        for k, default in knobs.items():
            v = got.get(k, default)
            if KNOBS[k][5] == "toggle":
                out[place][k] = v if isinstance(v, bool) else default
                continue
            try:
                v = float(v)
            except (TypeError, ValueError):
                v = default
            lo, hi, step = KNOBS[k][2:5]
            v = round(round(min(max(v, lo), hi) / step) * step, 2)
            out[place][k] = int(v) if float(v).is_integer() and isinstance(default, int) else v
    return out


def tuning_from(db: Session) -> dict:
    row = db.get(ToolSetting, TUNING_KEY)
    try:
        return clean_tuning(json.loads(row.value) if row and row.value else {})
    except ValueError:
        return clean_tuning({})


def tuning() -> dict:
    """The dice tuning, for every page's data-dice-tuning (from the access cache, so no extra read per page)."""
    return access._rows().get(access.TUNING) or clean_tuning({})


def shown(value, how: str) -> str:
    """A knob's value as people read it (app.js shows the same)."""
    if how == "toggle":
        return "on" if value else "off"
    if how == "x":
        return f"{value:.1f}×"
    if how == "pct":
        return f"{round(value * 100)}%"
    if how in ("s", "px"):
        return f"{value:g} {how}"
    return f"{value:g}{how}"


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


# ------------------------------------------------------------------ Dice tuning (admins)
@router.get("/manage/dice")
def tuning_page(request: Request, db: Session = Depends(get_db)):
    """Manage › askdnd › Dice tuning: sliders for each place dice are thrown, a Throw preview, and Save for everyone."""
    _, stop = web.require(request, is_admin, "Dice tuning is for admins.")
    if stop:
        return stop
    return templates.TemplateResponse(request, "manage_dice.html", {
        "places": PLACES, "knobs": KNOBS, "now": tuning_from(db), "original": TUNING, "shown": shown,
        "toast": request.session.pop("toast", None)})


@router.post("/manage/dice")
async def save_tuning(request: Request, db: Session = Depends(get_db)):
    """Save the sliders for everyone (fields "<place>.<knob>"), or `reset` to askdnd's own tuning."""
    _, stop = web.require(request, is_admin, "Dice tuning is for admins.")
    if stop:
        return stop
    form = await request.form()
    row = db.get(ToolSetting, TUNING_KEY) or ToolSetting(key=TUNING_KEY)
    if form.get("reset"):
        row.value = ""
        request.session["toast"] = "Dice tuning is back to askdnd's own."
    else:
        raw: dict = {}
        for name, value in form.items():
            place, _, knob = name.partition(".")
            if place in TUNING and knob in TUNING[place]:
                raw.setdefault(place, {})[knob] = (value == "1") if KNOBS[knob][5] == "toggle" else value
        row.value = json.dumps(clean_tuning(raw))
        request.session["toast"] = "Saved. Everyone's next roll uses it."
    db.add(row)
    db.commit()
    access.invalidate()
    return RedirectResponse("/manage/dice", status_code=303)
