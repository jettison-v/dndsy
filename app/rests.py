"""Short and Long Rests (roadmap 1.4; 2024 rules, SRD 5.2.1 Rules Glossary).

Hit points' panel has Short Rest and Long Rest. Each opens a small window listing what comes back, and Rest makes it all on
D&D Beyond through the bridge. Nothing moves until the player confirms, and only while the sheet can be reached.

- **Short Rest:** resources that come back on one, and Hit Point Dice the player chooses to spend: each rolls the die and
  adds the Constitution modifier (at least 1), in Table rolls for all to see, and heals.
- **Long Rest:** all lost Hit Points and all spent Hit Point Dice, Temporary Hit Points end, every spell slot and resource
  that comes back on one, Exhaustion down 1.
- **At 0 Hit Points** neither can start: the window says so, and the DM rules.
- Something back **at dawn** isn't a rest: it's listed, and stays the table's to mark.
- **Concentration** ends when the rest outlasts the spell (a Short Rest is an hour) and on any Long Rest (its sleep is
  Unconscious): listed ticked, and unticking keeps it, for the DM's ruling (Brett, 2026-11-03).

Interruptions are the table's: askdnd can't see the hour pass.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import ddb_bridge, ddb_sheet, hit_points, picks, table_rolls, web
from app.character_views import ordinal
from app.db import get_db
from app.item_use import _guard as _player, _sheet
from app.templating import templates

router = APIRouter()
SHORT, LONG = "short", "long"
TITLE = {SHORT: "Short Rest", LONG: "Long Rest"}
RESETS = {SHORT: ("Short or Long Rest",), LONG: ("Short or Long Rest", "Long Rest")}


def _guard(db: Session, request: Request, character_id: int):
    ch, user = _player(db, request, character_id)
    if not ddb_bridge.plays(db, ch):
        raise HTTPException(404)
    return ch, user


def counts(sheet: dict, kind: str) -> list[dict]:
    """The counts that come back on this rest: {"field", "name", "back"}."""
    out = []
    ss = sheet.get("spell_slots") or {}
    if kind == LONG:
        out += [{"field": f"slot:{s['level']}", "name": f"{ordinal(s['level'])}-level", "back": s["used"]} for s in ss.get("slots") or [] if s.get("used")]
    if ss.get("pact", {}).get("used"):
        out.append({"field": f"pact:{ss['pact']['level']}", "name": "Pact Magic", "back": ss["pact"]["used"]})
    out += [{"field": f"uses:{a['id']}", "name": a["name"], "back": a["uses"]["used"]} for a in sheet.get("actions") or []
            if a.get("id") and a.get("uses") and a["uses"]["used"] and a["uses"]["reset"] in RESETS[kind]]
    out += [{"field": f"charges:{it['key'].split(':', 1)[1]}", "name": it["name"], "back": it["charges"]["used"]} for it in sheet.get("inventory") or []
            if it.get("charges") and it["charges"]["used"] and it["charges"]["reset"] in RESETS[kind]]
    return out


def at_dawn(sheet: dict) -> list[str]:
    """What's spent and comes back at dawn, not on a rest."""
    return [x["name"] for x in (*(a for a in sheet.get("actions") or [] if a.get("uses") and a["uses"]["used"] and a["uses"]["reset"] == "Dawn"),
                                *(it for it in sheet.get("inventory") or [] if it.get("charges") and it["charges"]["used"] and it["charges"]["reset"] == "Dawn"))]


def dice(sheet: dict) -> list[dict]:
    """Hit Point Dice by class: {"id", "class", "die", "left", "used"}."""
    return [{"id": d.get("id"), "class": d["class"], "die": d["die"], "left": d["total"] - d["used"], "used": d["used"]}
            for d in (sheet.get("hit_points") or {}).get("hit_dice") or [] if d.get("id")]


SHORT_REST_ROUNDS = 600  # an hour


def conc_ends(conc: dict | None, kind: str) -> str:
    """The spell whose Concentration this rest ends, or "": any on a Long Rest, one lasting an hour or less on a Short."""
    if not conc:
        return ""
    return conc.get("spell", "") if kind == LONG or 0 < (conc.get("rounds") or 0) <= SHORT_REST_ROUNDS else ""


def plan(sheet: dict, kind: str, conc: dict | None = None) -> dict:
    """What this rest brings back, for the window and for making it."""
    hp = sheet.get("hit_points") or {}
    exhaustion = next((c.get("level", 0) for c in sheet.get("conditions") or [] if c.get("name") == "Exhaustion"), 0)
    p = {"counts": counts(sheet, kind), "dawn": at_dawn(sheet), "dice": dice(sheet), "can": hp.get("current", 0) >= 1, "hp": 0, "temp": 0, "exhaustion": 0,
         "conc": conc_ends(conc, kind)}
    if kind == LONG:
        p |= {"hp": hp.get("damage", 0), "temp": hp.get("temp", 0), "exhaustion": exhaustion}
    return p


def lines(p: dict, kind: str) -> list[str]:
    """What comes back, in words."""
    out = [f"{c['name']}: {c['back']} back" for c in p["counts"]]
    if p["hp"]:
        out.insert(0, f"All Hit Points: {p['hp']} back")
    if kind == LONG:
        spent = sum(d["used"] for d in p["dice"])
        if spent:
            out.append(f"All Hit Point Dice: {spent} back")
    if p["temp"]:
        out.append(f"Temporary Hit Points end ({p['temp']})")
    if p["exhaustion"]:
        out.append(f"Exhaustion {p['exhaustion']} goes down 1")
    return out


def _kind(kind: str) -> str:
    if kind not in TITLE:
        raise HTTPException(404)
    return kind


def _formula(spend: list[tuple[dict, int]], con: int) -> str:
    """Hit Point Dice as a roll: "2d10+1d8+6"."""
    parts = "+".join(f"{n}{d['die']}" for d, n in spend)
    flat = con * sum(n for _, n in spend)
    return parts + (f"{flat:+d}" if flat else "")


@router.get("/characters/{character_id:int}/rest")
def window(request: Request, character_id: int, kind: str, db: Session = Depends(get_db)):
    """What Short Rest or Long Rest opens, in the roll window."""
    from app.preparing import books_to_prepare

    ch, _ = _guard(db, request, character_id)
    sheet = _sheet(db, ch)
    p = plan(sheet, _kind(kind), ch.concentration)
    prepare = [b["class"] for b in books_to_prepare(sheet)] if kind == "long" else []  # (a Long Rest is when most classes change them)
    return templates.TemplateResponse(request, "_rest_window.html", {"c": ch, "kind": kind, "title": TITLE[kind], "p": p, "lines": lines(p, kind),
                                                                     "reachable": ddb_bridge.reachable(ch), "prepare": prepare})


@router.post("/characters/{character_id:int}/rest")
def rest(request: Request, character_id: int, kind: str, form=web.FormBody, db: Session = Depends(get_db)):
    """Rest: all of it on its way to D&D Beyond, and Hit Point Dice rolled in Table rolls."""
    return _make(request, db, character_id, _kind(kind), form)


def _make(request: Request, db: Session, character_id: int, kind: str, form) -> JSONResponse:
    ch, user = _guard(db, request, character_id)
    ddb_bridge.reach(ch)
    sheet = _sheet(db, ch)
    p = plan(sheet, kind, ch.concentration)
    if not p["can"]:
        raise HTTPException(409, "To start a rest you must have at least 1 Hit Point.")
    said = lines(p, kind)
    if p["conc"] and form.get("conc_ends"):
        ch.concentration = None  # (askdnd's own, as End does on Battle)
        said.append(f"Concentration on {p['conc']} ended")
    for c in p["counts"]:
        fk, arg = c["field"].split(":", 1)
        ddb_bridge.add(db, ch, "use", {"field": c["field"], "delta": -c["back"], "max": ddb_sheet.most(ch.snapshot.raw, fk, arg)}, f"{ch.name}: {c['name']} back")
    row = None
    if kind == LONG:
        if p["hp"]:
            ddb_bridge.add(db, ch, "hp", {"amount": p["hp"]}, f"{ch.name}: all Hit Points back")
        if p["temp"]:
            ddb_bridge.add(db, ch, "temp", {"value": 0}, f"{ch.name}: Temporary Hit Points end")
        for d in p["dice"]:
            if d["used"]:
                ddb_bridge.add(db, ch, "use", {"field": f"hitdice:{d['id']}", "delta": -d["used"]}, f"{ch.name}: Hit Point Dice back")
        if p["exhaustion"]:
            ddb_bridge.add(db, ch, "set", {"field": "exhaustion", "value": p["exhaustion"] - 1}, f"{ch.name}: Exhaustion down 1")
    else:
        spend = [(d, n) for d in p["dice"] if (n := min(d["left"], _number(form.get(f"dice_{d['id']}"))))]
        if spend:
            ddb_bridge.add(db, ch, "short_rest", {"spend": {str(d["id"]): n for d, n in spend}}, f"{ch.name}: Hit Point Dice spent")
            me = picks.user_row(db, user)
            row = table_rolls.add_roll(db, ch, me.id, "Hit Point Dice", _formula(spend, _con(sheet)))
            if row:
                at_least = max(row.total, sum(n for _, n in spend))  # (each die heals at least 1)
                w = hit_points.working(db, ch, "heal", [{"amount": at_least, "type": ""}])
                said.append(hit_points.make(db, ch, user, row, "heal", w))
    db.commit()
    out = {"text": f"{TITLE[kind]}" + (": " + ", ".join(said) if said else ": nothing to bring back"), "deliver": web.deliver_now(ch)}
    if row:
        db.refresh(row)
        out |= table_rolls.reply_body(request, db, row, picks.user_row(db, user).id, False)
    return JSONResponse(out)


def _number(value) -> int:
    return int(value) if str(value or "").isdigit() else 0


def _con(sheet: dict) -> int:
    return next((a["modifier"] for a in sheet.get("abilities") or [] if a["key"] == "con"), 0)
