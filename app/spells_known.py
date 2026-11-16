"""Your spells: cantrips swapped, spells learned, a Wizard's spellbook (roadmap step 5, Brett's picks 3–4 on
docs/mockups/choices-in-askdnd/, Nov 13). Until now these were changed only on D&D Beyond.

One window for the three, each the same change on the sheet: a spell on the class's list or not (`ddb_fields` "learn",
D&D Beyond's own Manage Spells request, POST and DELETE spell, recorded on Levi's test seat, Nov 14):

- **Cantrips**: let one go and learn another from the class's list (a Wizard after a Long Rest; the others when they gain
  a level in the class).
- **Spells**: for a class that learns its spells (a Bard, a Sorcerer, a Warlock: D&D Beyond's classes that don't
  prepare from a list), let one go and learn another when you gain a level.
- **Spellbook** (a Wizard): copy a spell into it; each level takes 2 hours and 50 GP, said, not taken.

It says the rule and never enforces it: when, how many and the gold are the DM's ruling. Undo puts it back, sealed.
"""

import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import ddb_bridge, web
from app.db import get_db
from app.inventory import _guard
from app.item_use import _sheet
from app.templating import templates

router = APIRouter()
KINDS = ("cantrips", "spells")
# When each may change, by the 2024 Player's Handbook (in its own few words; askdnd never checks when: the DM rules)
CANTRIPS = {"Wizard": "after a Long Rest, replace one Wizard cantrip"}
CANTRIPS_DEFAULT = "when you gain a {cls} level, replace one cantrip with another from the {cls} list"
SPELLS = {"Warlock": "when you gain a Warlock level, replace one spell with another Warlock spell of an eligible level"}
SPELLS_DEFAULT = "when you gain a {cls} level, replace one spell with another {cls} spell you have slots for"
COPY = "Copying a spell found on a scroll or in a book: for each of its levels, 2 hours and 50 GP (not taken from your purse)."


def books(sheet: dict) -> list[dict]:
    """The classes with something to change here: cantrips, spells it learns, or a spellbook."""
    out = []
    for b in sheet.get("spellbook") or []:
        spells = [sp for sp in b.get("spells") or [] if sp.get("learn")]
        kinds = [k for k in KINDS if (k == "cantrips" and any(not sp["level"] for sp in spells))
                 or (k == "spells" and (b.get("learns") or b.get("spellbook")) and any(sp["level"] for sp in spells))]
        if kinds:
            out.append({**b, "kinds": kinds})
    return out


def lists(book: dict, kind: str) -> tuple[list[dict], list[dict]]:
    """(what the class has, one to let go of; what it could learn), for cantrips or leveled spells."""
    cantrip = kind == "cantrips"
    mine = ("known",) if cantrip else ("prepared", "spellbook", "known")
    have, can = [], []
    for sp in book.get("spells") or []:
        if not sp.get("learn") or bool(sp["level"]) == cantrip or sp["state"] == "always":
            continue
        row = {"key": sp["key"], "name": sp["name"], "level": sp["level"], "entry": str(sp["learn"]["entry"])}
        (have if sp["state"] in mine else can if sp["state"] == "available" else []).append(row)
    return have, can


def _rule(book: dict, kind: str) -> str:
    cls = book["class"]
    if kind == "cantrips":
        return CANTRIPS.get(cls, CANTRIPS_DEFAULT.format(cls=cls))
    if book.get("spellbook"):
        return "your spellbook holds the spells you prepare from"
    return SPELLS.get(cls, SPELLS_DEFAULT.format(cls=cls))


def _book(sheet: dict, cls: str) -> dict:
    found = books(sheet)
    if not found:
        raise HTTPException(404)
    return next((b for b in found if b["class"] == cls), found[0])


@router.get("/characters/{character_id:int}/spells/learn")
def window(request: Request, character_id: int, cls: str = "", kind: str = "", db: Session = Depends(get_db)):
    """Your spells: from Sheet › Spells and the level-up card."""
    ch, _ = _guard(db, request, character_id)
    sheet = _sheet(db, ch)
    book = _book(sheet, cls)
    kind = kind if kind in book["kinds"] else book["kinds"][0]
    have, can = lists(book, kind)
    going = {k for k, v in (sheet.get("sync") or {}).items() if k.startswith("learn:") and v == "on"}
    for r in can:
        r["going"] = any(g.endswith(f":{r['entry']}") for g in going)
    return templates.TemplateResponse(request, "_spells_known.html", {
        "c": ch, "book": book, "books": books(sheet), "kind": kind, "have": have, "can": can, "rule": _rule(book, kind),
        "copy": COPY if kind == "spells" and book.get("spellbook") else "", "reachable": ddb_bridge.reachable(ch)})


def _find(book: dict, entry: str) -> dict | None:
    return next((sp for sp in book.get("spells") or [] if sp.get("learn") and str(sp["learn"]["entry"]) == entry), None)


@router.post("/characters/{character_id:int}/spells/learn")
def change(request: Request, character_id: int, cls: str = "", kind: str = "", out: str = Form(""), into: str = Form("", alias="in"),
           spells: str = Form(""), sig: str = Form(""), db: Session = Depends(get_db)):
    """Let go of `out` and learn `in` (each a spell's entry on the class's list), either or both. With `sig`, an Undo:
    exactly what askdnd handed back, `spells` naming each (one let go of isn't on the shown list until D&D Beyond has it)."""
    ch, _ = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    sheet = _sheet(db, ch)
    book = _book(sheet, cls)
    kind = kind if kind in book["kinds"] else book["kinds"][0]  # (as the window it came from: its first, unless named)
    undoing = bool(sig)
    if undoing and not web.sealed({"out": out, "in": into, "spells": spells, "cls": book["class"], "kind": kind}, f"spells-known:{ch.id}", sig):
        raise HTTPException(409, "That Undo isn't one askdnd gave.")
    if not out and not into:
        raise HTTPException(409, "Pick a spell to let go of, one to learn, or both.")
    if out and out == into:
        raise HTTPException(409, "Pick two different spells.")
    if undoing:
        try:
            named = json.loads(spells)
        except ValueError:
            raise HTTPException(409, "That Undo isn't one askdnd gave.") from None
    else:
        have, can = lists(book, kind)
        if out and out not in {r["entry"] for r in have}:
            raise HTTPException(409, "That isn't one of your spells (changed on D&D Beyond meanwhile?).")
        if into and into not in {r["entry"] for r in can}:
            raise HTTPException(409, "That isn't a spell you can learn here.")
        named = {e: {**_find(book, e)["learn"], "name": _find(book, e)["name"]} for e in (out, into) if e}
    said = []
    for entry, value in ((out, False), (into, True)):
        if not entry:
            continue
        sp = named.get(entry)
        if not sp:
            raise HTTPException(409, "That isn't a spell askdnd can change here.")
        data = {**sp, "value": value}
        ddb_bridge.add(db, ch, "learn", data, f"{ch.name}: {ddb_bridge.describe('learn', data, {})}")
        said.append(f"{sp['name']} {'learned' if value else 'let go'}")
    db.commit()
    back = {"out": into, "in": out, "spells": json.dumps(named, sort_keys=True), "cls": book["class"], "kind": kind}
    back["sig"] = web.seal(back, f"spells-known:{ch.id}")
    url = f"/characters/{ch.id}/spells/learn?cls={book['class']}&kind={kind}"
    return JSONResponse({"text": f"{ch.name}'s {book['class']} {kind}: {' and '.join(said)}, on its way to D&D Beyond",
                         "undo": {k: v for k, v in back.items() if k in ("out", "in", "spells", "sig")}, "undoUrl": url, "deliver": web.deliver_now(ch)})
