"""Changing prepared spells (Brett, 2026-11-02): a spell's side panel has Prepare or Unprepare, confirmed in the roll
window, and the change goes to D&D Beyond through the bridge (app/ddb_fields.py "prep", the request D&D Beyond's own
sheet sends, seen on the test sheet the same day).

Only for a class that prepares from a list (a cleric, a druid, a wizard from the spellbook), and only a spell of 1st
level or higher. The window says how many are prepared and the class's number at its level; going over is allowed, as
D&D Beyond allows it, and said so: when and how many is the DM's ruling, not askdnd's.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import ddb_bridge, web
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
