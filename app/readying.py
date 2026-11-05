"""Ready, kept on Battle (feedback 14, Trent, Nov 5; docs/mockups/hide-ready.html, Brett chose the recommendations).

Ready's side panel opens the Ready window (`_ready_window.html`, the item window: app.js "using an item"): what you'll
do (an attack or a spell from Battle's Action column, or moving up to your Speed) and the trigger. It's kept on the
character (`Character.readied`) and waits at the top of Battle's Reaction column (Brett's choice 2), as its own row with
its own Roll or Cast, plus Used and Let it go. A readied spell spends its slot now and is held with Concentration: the
window says so, and its Cast is where the slot is spent. A readied action lasts until the character's next turn starts:
in a fight askdnd hears, it's cleared then with a corner card (app/fight.py follow). askdnd only keeps track; when the
trigger happens is the DM's.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import character_views as views
from app import characters as chars
from app import ddb_bridge, picks
from app.auth import current_user
from app.db import get_db
from app.models import Character
from app.templating import templates

router = APIRouter()
MOVE = "move"  # (moving up to your Speed instead of an action)


def _player(db: Session, request: Request, character_id: int) -> Character:
    user, ch = current_user(request), db.get(Character, character_id)
    if not user or not ch or not picks.can_edit(db, user, ch):
        raise HTTPException(404)
    return ch


def _sheet(db: Session, ch: Character) -> dict:
    return ddb_bridge.as_shown(db, ch, chars.character_summary(ch)) or {}


def choices(sheet: dict) -> list[dict]:
    """What can be readied: the attacks and the spells cast as an action on Battle's Action column (all of them, pinned
    or not), each {"key", "name", "kind", "level"}."""
    col = views.battle_columns(sheet, set(), [], pinned_only=False).get("Action") or {}
    return [{"key": o["key"], "name": o["name"], "kind": o["kind"], "level": o.get("level") or 0}
            for o in col.get("all") or [] if o.get("kind") in ("attack", "spell")]


def shown(sheet: dict, ch: Character) -> dict | None:
    """What's readied, as Battle's Reaction column shows it: {"name", "trigger", "option"} (the row as Battle draws it,
    so its own Roll or Cast is there), or None."""
    r = ch.readied
    if not r:
        return None
    col = views.battle_columns(sheet, set(), [], pinned_only=False).get("Action") or {}
    o = next((x for x in col.get("all") or [] if x["key"] == r.get("key")), None)
    return {**r, "option": o}


@router.post("/characters/{character_id:int}/ready/clear")
def clear(request: Request, character_id: int, to: str = Form("drop"), db: Session = Depends(get_db)):
    """Battle's Used it or Let it go: the page shows its new copy in place (web.changed)."""
    from fastapi import Response

    from app import web

    ch = _player(db, request, character_id)
    name = (ch.readied or {}).get("name") or "Readied"
    ch.readied = None
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": web.changed(ch, f"{name}: used" if to == "used" else f"{name}: let go")})


@router.get("/characters/{character_id:int}/ready")
def window(request: Request, character_id: int, db: Session = Depends(get_db)):
    ch = _player(db, request, character_id)
    sheet = _sheet(db, ch)
    return templates.TemplateResponse(request, "_ready_window.html", {"c": ch, "choices": choices(sheet), "speed": (sheet.get("speed") or {}).get("walk"),
                                                                      "readied": ch.readied})


@router.post("/characters/{character_id:int}/ready")
def ready(request: Request, character_id: int, what: str = Form(""), trigger: str = Form(""), db: Session = Depends(get_db)):
    """Ready it (`what`: a choice's key, or "move"), with `trigger`."""
    ch = _player(db, request, character_id)
    trigger = " ".join(trigger.split())[:200]
    if not trigger:
        raise HTTPException(409, "Say when: the trigger.")
    sheet = _sheet(db, ch)
    if what == MOVE:
        speed = (sheet.get("speed") or {}).get("walk")
        pick = {"key": MOVE, "name": f"Move up to {speed} ft" if speed else "Move up to your Speed", "kind": MOVE, "level": 0}
    else:
        pick = next((x for x in choices(sheet) if x["key"] == what), None)
        if pick is None:
            raise HTTPException(409, "Pick what you'll do.")
    ch.readied = {**pick, "trigger": trigger}
    db.commit()
    held = pick["kind"] == "spell" and pick["level"]
    return JSONResponse({"text": f"Readied: {pick['name']}, when {trigger}" + (". Cast it now: its slot is spent and it's held with Concentration" if held else ""),
                         "character": ch.id})
