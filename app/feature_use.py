"""The Use window (the action widgets, roadmap 8; Brett chose A on Use Window, Nov 13, docs/mockups/use-window/): one
window for what a feature spends, who it's for and what it does, drawn from the feature's data, so a new feature is a
line of data and not a window of its own.

A Battle row gets **Use** when it costs something (`character_views.pays`: its own use, or the resource it says it
expends) and has no roll of its own (a roll spends its cost on the roll card instead): Patient Defense, Step of the
Wind, Divine Sense, Action Surge. Its window says the cost, what's left and the feature's words; Use spends it on D&D
Beyond through Use one's count (app/resources.py), with Undo.

A feature whose rules-book entry has a `use` (app/data/rules/phb-2024.json) says more: Lay On Hands is a pool (How
many), for one creature (For: the party, with their Hit Points), in ways (Heal, chosen; End Poisoned, 5 points).
Heal on yourself, or as the DM, heals through the hit points window's own rules (`hit_points.make`); on another's
character it goes to Table rolls for that character's player to apply (Apply to), as a potion given to someone does:
a player changes only their own sheet. Ending a condition is the same. Undo puts back everything it changed.

`spec(sheet, o)` is what the window draws; the routes below make it. Who may: the character's player, or the DM
(item_use._guard), only where askdnd plays the sheet (resources._guard).
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import character_views as views
from app import conditions as cond
from app import ddb_bridge, hit_points, rules_book, web
from app.db import get_db
from app.item_use import _end, _sheet
from app.models import Character
from app.resources import _guard, count
from app.templating import templates

router = APIRouter()

# (a row under Other is a note, not something to press; a Reaction's cost is often a choice, Deflect Attack's Focus
# Point only to redirect, so a Reaction gets Use only from its data)
COSTS = ("Action", "Bonus action")
ELSEWHERE = {"Wild Shape"}  # (its forms' window spends it: app/shifting.py)
POOL = 10  # (more than this to count, Lay On Hands' 5 × level: How many, not one at a time; as Use one's window)


def _use(name: str) -> dict | None:
    """The rules book's `use` for a feature by its Battle name ("Lay On Hands: Heal" is Lay On Hands')."""
    e = rules_book.entry("feature", name.split(":")[0].strip())
    return (e or {}).get("use")


def spec(sheet: dict, o: dict) -> dict | None:
    """What the Use window asks for this Battle row, or None (nothing to spend, a roll that spends it, or another
    window's): {"pay": what it spends with its count now, "pool", "for", "ways": [{key, name, heal?, spend?, ends?}]}."""
    pay = [p | {"count": c} for p in o.get("pay") or [] if (c := count(sheet, p["field"]))]
    if not pay or o["name"].split(":")[0].strip() in ELSEWHERE:
        return None
    use = _use(o["name"])
    if not use and (o.get("cost") not in COSTS or any(r.get("button") for r in views.option_rolls(o))):
        return None
    first = pay[0]["count"]
    # (without data, the button says what it spends: Patient Defense's Disengage is free, its Focus Point buys the Dodge too)
    ways = (use or {}).get("ways") or [{"key": "use", "name": f"Spend {pay[0]['label']}"}]
    row = o["name"].split(":", 1)[1].strip() if ":" in o["name"] else ""  # (D&D Beyond's row for one way: "Lay On Hands: Purify Poison")
    ways = sorted(ways, key=lambda w: w.get("row") != row)
    return {"pay": pay, "pool": bool(first["max"] and first["max"] > POOL), "for": (use or {}).get("for"), "ways": ways}


def _row(sheet: dict, key: str) -> tuple[dict, dict]:
    o = next((x for x in views.options(sheet) if x["key"] == key), None)
    s = spec(sheet, o) if o else None
    if not s:
        raise HTTPException(404)
    return o, s


def _whom(db: Session, user: dict, ch: Character) -> list[dict]:
    """Who a feature for one creature can be for: the party (everyone whose sheet askdnd reaches in the campaign), each
    with their Hit Points and how many they're missing, the caster first. `own`: changed here (theirs, or the DM's)."""
    from sqlalchemy import select

    from app import characters as chars

    rows = db.scalars(select(Character).where(Character.copy_of_id.is_(None)).order_by(Character.name)).all()
    out = []
    for c in sorted((c for c in rows if c.campaign_id == ch.campaign_id and ddb_bridge.on_for(db, c)), key=lambda c: c.id != ch.id):
        hp = (ddb_bridge.as_shown(db, c, chars.character_summary(c)) or {}).get("hit_points") or {}
        out.append({"id": c.id, "name": c.name, "hp": f"{hp.get('current', 0)}/{hp['max']}" if hp.get("max") else "",
                    "needs": max(0, (hp.get("max") or 0) - (hp.get("current") or 0)), "own": hit_points.can_apply(db, user, c)})
    return out


@router.get("/characters/{character_id:int}/feature")
def window(request: Request, character_id: int, key: str, db: Session = Depends(get_db)):
    """What a feature's Use opens, in the roll window."""
    ch, user = _guard(db, request, character_id)
    sheet = _sheet(db, ch)
    o, s = _row(sheet, key)
    whom = _whom(db, user, ch) if s["for"] else []
    first = next((w for w in whom if w["needs"]), whom[0] if whom else None)
    left = s["pay"][0]["count"]["left"]
    return templates.TemplateResponse(request, "_feature_window.html", {
        "c": ch, "o": o, "s": s, "whom": whom, "first": first, "reachable": ddb_bridge.reachable(ch),
        "n": max(1, min(left, first["needs"] if first and first["needs"] else 1)) if s["pool"] else 1})  # (all it needs; 1 when nobody's hurt)


def _spend(db: Session, ch: Character, field: str, n: int, label: str) -> None:
    """The count, through Use one's change (`n` back when negative)."""
    made = ddb_bridge._change(ddb_bridge.numbers(ch), {"kind": "use", "field": field, "delta": n})
    if not made:
        raise HTTPException(409, "That isn't a change askdnd can make on D&D Beyond.")
    ddb_bridge.add(db, ch, *made, label)


@router.post("/characters/{character_id:int}/feature")
def use(request: Request, character_id: int, key: str, way: str = Form("use"), how_many: str = Form("1", alias="n"),
        target: int = Form(0), db: Session = Depends(get_db)):
    """Use it: what it spends on D&D Beyond, and what the way does (heal, end a condition) to whom it's for."""
    ch, user = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    sheet = _sheet(db, ch)
    o, s = _row(sheet, key)
    w = next((x for x in s["ways"] if x["key"] == way), None)
    if not w:
        raise HTTPException(404)
    pay, name = s["pay"][0], o["name"].split(":")[0].strip()
    left = pay["count"]["left"]
    n = int(w["spend"]) if w.get("spend") else (int(how_many) if how_many.strip().isdigit() else 1) if s["pool"] else int(pay["n"])
    if n < 1 or n > left:
        raise HTTPException(409, f"{name}: {left} left." if left else f"{name}: none left.")
    who = None
    if s["for"]:
        who = next((x for x in _whom(db, user, ch) if x["id"] == target), None)
        if not who:
            raise HTTPException(409, f"Who is {name} for?")
        if w.get("heal") and who["hp"] and not who["needs"]:
            raise HTTPException(409, f"{who['name']} is at full Hit Points.")
        if w.get("heal") and who["needs"]:  # (never more than it heals: the rest stays in the pool)
            n = min(n, who["needs"])
    tgt = db.get(Character, who["id"]) if who else None
    if tgt and w.get("ends") and who["own"] and not any(x.get("name") == w["ends"] for x in cond.shown(tgt.conditions, (_sheet(db, tgt)).get("conditions"), True)):
        raise HTTPException(409, f"{tgt.name} isn't {w['ends']}.")
    _spend(db, ch, pay["field"], n, f"{ch.name}: {name}, {n} {'used' if not s['pool'] else 'from the pool'}")
    undo = {"key": key, "field": pay["field"], "n": str(n)}
    text = f"{ch.name}: {name}, {pay['label']}" if w["key"] == "use" else f"{ch.name}: {w['name']}" + (f", {n}" if s["pool"] and not w.get("spend") else "")
    if tgt and w.get("heal"):
        if who["own"]:
            ddb_bridge.reach(tgt)
            work = hit_points.working(db, tgt, "heal", [{"amount": n, "type": ""}])
            text = f"{name}: {hit_points.make(db, tgt, user, None, 'heal', work)}"
            if not work["up"]:  # (back up from 0 is the DM's to take back: Undo leaves it)
                undo |= {"healed": str(work["hp_after"] - work["hp_before"]), "target": str(tgt.id)}
        else:
            from app import picks, table_rolls

            me = picks.user_row(db, user)
            row = table_rolls.add_roll(db, ch, me.id, f"{name} for {tgt.name}", str(n))
            text = f"{name}: {n} healing for {tgt.name}, in Table rolls for {tgt.name}'s player to apply"
            undo |= {"roll": str(row.id)} if row else {}
    if tgt and w.get("ends"):
        if who["own"]:
            _end(db, tgt, w["ends"])
            text = f"{name}: {w['ends']} ends for {tgt.name}"
            undo |= {"ended": w["ends"], "target": str(tgt.id)}
        else:
            text = f"{name}: {w['ends']} ends for {tgt.name}; {tgt.name}'s player (or the DM) marks it"
    db.commit()
    undo["sig"] = web.seal(undo, f"feature-undo:{ch.id}")  # (Undo gets back exactly this, for this character)
    return JSONResponse({"text": text, "undo": undo, "undoUrl": f"/characters/{ch.id}/feature/undo", "deliver": web.deliver_now(ch)})


@router.post("/characters/{character_id:int}/feature/undo")
def undo_use(request: Request, character_id: int, key: str = Form(...), field: str = Form(...), n: str = Form("1"),
             healed: str = Form(""), target: str = Form(""), roll: str = Form(""), ended: str = Form(""), sig: str = Form(""),
             db: Session = Depends(get_db)):
    """The corner card's Undo: the points back, and the healing or the condition as it was. Only what the use answered
    (`sig`)."""
    ch, user = _guard(db, request, character_id)
    sent = {"key": key, "field": field, "n": n, "healed": healed, "target": target, "roll": roll, "ended": ended}
    if not web.sealed(sent, f"feature-undo:{ch.id}", sig):
        raise HTTPException(409, "That Undo isn't one askdnd gave: change it on the sheet.")
    ddb_bridge.reach(ch)
    name = key.removeprefix("action:").split(":")[0].strip()
    from app.models import TableRoll

    given = db.get(TableRoll, int(roll)) if roll.isdigit() else None
    if given and hit_points.applied(db, given):  # (the healing is someone's now: the points stay spent)
        raise HTTPException(409, f"{name}: that healing was already applied; the DM can change it.")
    _spend(db, ch, field, -int(n), f"{ch.name}: {name} undone")
    tgt = db.get(Character, int(target)) if target.isdigit() else None
    if tgt and healed.isdigit() and int(healed) > 0 and hit_points.can_apply(db, user, tgt):
        ddb_bridge.reach(tgt)
        ddb_bridge.add(db, tgt, "hp", {"amount": -int(healed), "undo": True}, f"{tgt.name}: {name} undone")
    if tgt and ended in cond.KNOWN and hit_points.can_apply(db, user, tgt):
        tgt.conditions = cond.add(tgt.conditions, ended, name, "")
        if ended in cond.ON_DDB:
            ddb_bridge.add(db, tgt, "set", {"field": cond.ddb_field(ended), "value": True}, f"{tgt.name}: {ended} again ({name} undone)")
    if given:
        r = given
        if r.character_id == ch.id:
            r.label, r.total = f"Undone: {r.label}"[:120], 0
            from app import realtime

            realtime.announce(db, ch.campaign_id, "rolls")
    db.commit()
    return JSONResponse({"text": f"{name} undone", "deliver": web.deliver_now(ch)})

