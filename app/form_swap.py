"""Swap a Wild Shape form (roadmap step 5, Brett's pick 1 on docs/mockups/choices-in-askdnd/, Nov 13): a Druid knows a
number of Beast forms, and after a Long Rest can replace one of them with another eligible form (2024 Player's Handbook,
Wild Shape's Known Forms). Until now that was done only on D&D Beyond.

The window lists the forms the Druid knows (one to let go of) and the ones they could learn now (one to learn, from the
list Sheet › Wild Shape already shows), and makes the change on the sheet through the bridge: D&D Beyond's own requests
for a known form, a creature in group 13 (`ddb_fields` "wildshape", recorded on Levi's test seat, Nov 14). It says the
rule and never enforces it: when, and how many, is the DM's ruling. Learning one with a form free, or letting one go, is
allowed too (Make says which). Undo puts both back, sealed so the page can't change it (web.seal).

A form is learned by its D&D Beyond monster id (the 2024 Monster Manual's, `rules_data.pictures`); one without an id
(a homebrew Beast) is learned on D&D Beyond itself, and the window says so.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import ddb_bridge, rules_data, web
from app import wild_shape as ws
from app.db import get_db
from app.inventory import _guard
from app.item_use import _sheet
from app.templating import templates

router = APIRouter()
RULE = ("After a Long Rest you can replace one of your known forms with another eligible Beast (2024 Player's Handbook). "
        "askdnd doesn't check when; that's the DM's call.")


def _ids() -> dict[str, str]:
    """D&D Beyond's monster id for each Beast askdnd knows, by its key ("dire-wolf")."""
    return {k: str(v["ddb_id"]) for k, v in rules_data.pictures().items() if v.get("ddb_id")}


def options(db: Session, ch, sheet: dict) -> dict | None:
    """What the window offers: {"druid", "known": [{"mid", "name", "cr_label", "going"}], "learn": [{"mid", "name",
    "cr_label", "summary", "image"}], "no_id": [names]}, or None when the character has no Wild Shape."""
    d = ws.druid(sheet)
    if not d:
        return None
    sync = sheet.get("sync") or {}
    beasts = ws.beasts(db, ch.campaign_id)
    ids = _ids()
    known = []
    for c in sheet.get("creatures") or []:
        if c.get("group") == "Wild Shape form" and c.get("monster_id"):
            b = ws.catalog_beast(c["kind"], beasts) or {}
            known.append({"mid": str(c["monster_id"]), "name": c["kind"], "cr_label": ws.cr_label(c.get("cr") or 0),
                          "image": b.get("image", ""), "going": sync.get(f"wildshape:{c['monster_id']}") == "on"})
    have = {k["name"].lower() for k in known}
    learn, no_id = [], []
    for f in ws.forms(sheet, set(), beasts=beasts):
        if f["known"] or f["why_not"] or f["name"].lower() in have:
            continue
        b = ws.catalog_beast(f["name"], beasts) or {}
        mid = ids.get(b.get("key", ""))
        if not mid:
            no_id.append(f["name"])
            continue
        learn.append({"mid": mid, "name": f["name"], "cr": f["cr"], "cr_label": f["cr_label"], "summary": f["summary"], "image": f["image"],
                      "moves": f["move_labels"], "going": sync.get(f"wildshape:{mid}") == "on"})
    known.sort(key=lambda k: k["name"])
    return {"druid": d, "known": known, "learn": learn, "no_id": no_id}


@router.get("/characters/{character_id:int}/wild-shape/forms")
def window(request: Request, character_id: int, db: Session = Depends(get_db)):
    """Swap a form: from Sheet › Wild Shape and the Long Rest window."""
    ch, _ = _guard(db, request, character_id)
    opts = options(db, ch, _sheet(db, ch))
    if opts is None:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "_form_swap.html", {"c": ch, **opts, "rule": RULE, "reachable": ddb_bridge.reachable(ch)})


def _name(opts: dict, mid: str) -> str:
    return next((x["name"] for x in opts["known"] + opts["learn"] if x["mid"] == mid), "")


@router.post("/characters/{character_id:int}/wild-shape/forms")
def swap(request: Request, character_id: int, out: str = Form(""), into: str = Form("", alias="in"), out_name: str = Form(""),
         in_name: str = Form(""), sig: str = Form(""), db: Session = Depends(get_db)):
    """Let go of `out` (a known form's monster id) and learn `in` (one the Druid could learn), either or both. With `sig`,
    an Undo: exactly what askdnd handed back (the names too: a form just learned isn't listed until D&D Beyond has it)."""
    ch, _ = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    sheet = _sheet(db, ch)
    opts = options(db, ch, sheet)
    if opts is None:
        raise HTTPException(404)
    undoing = bool(sig)
    if undoing and not web.sealed({"out": out, "in": into, "out_name": out_name, "in_name": in_name}, f"form-swap:{ch.id}", sig):
        raise HTTPException(409, "That Undo isn't one askdnd gave.")
    if not out and not into:
        raise HTTPException(409, "Pick a form to let go of, one to learn, or both.")
    on_way = sheet.get("sync") or {}
    if out and out not in {k["mid"] for k in opts["known"]} and not (undoing and on_way.get(f"wildshape:{out}") == "on"):
        raise HTTPException(409, "That isn't one of the forms you know (changed on D&D Beyond meanwhile?).")
    if into and into not in {k["mid"] for k in opts["learn"]} and not undoing:
        raise HTTPException(409, "That isn't a form you can learn now.")
    if out and out == into:
        raise HTTPException(409, "Pick two different forms.")
    names = {"out": (out_name if undoing else _name(opts, out)) or "a form", "in": (in_name if undoing else _name(opts, into)) or "a form"}
    said = []
    if out:
        ddb_bridge.add(db, ch, "set", {"field": f"wildshape:{out}", "value": 0}, f"{ch.name}: Wild Shape form {names['out']} let go")
        said.append(f"{names['out']} let go")
    if into:
        ddb_bridge.add(db, ch, "set", {"field": f"wildshape:{into}", "value": 1}, f"{ch.name}: Wild Shape form {names['in']} learned")
        said.append(f"{names['in']} learned")
    db.commit()
    back = {"out": into, "in": out, "out_name": names["in"] if into else "", "in_name": names["out"] if out else ""}
    back["sig"] = web.seal(back, f"form-swap:{ch.id}")
    text = f"{ch.name}'s Wild Shape: {' and '.join(said)}, on its way to D&D Beyond"
    return JSONResponse({"text": text, "undo": back, "undoUrl": f"/characters/{ch.id}/wild-shape/forms", "deliver": web.deliver_now(ch)})
