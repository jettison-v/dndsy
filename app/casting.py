"""Casting a spell in play (roadmap 1.2; Brett, 2026-10-30: build it, the interface is reviewed afterwards).

A spell's Cast opens a small window like an item's (app.js "using an item"): the ways it can be cast now, and Cast. Only
where the bridge works and only for the character's own player, as with items:

- **A slot** spends that level's spell slot or Pact Magic slot on D&D Beyond (a spell can always use a higher slot).
- **As a Ritual** and **No slot** spend nothing: a Ritual for a spell that has the tag, No slot for anything else that
  pays for it (a feature, an item). askdnd doesn't decide which applies.
- **A free use** a feat or species gives is listed first where the sheet counts it, in place of No slot. askdnd can't change
  that count on D&D Beyond yet, so the corner card asks the player to mark it there.
- **Concentration** starts by itself and ends the one before, as at the table; the window says so first.
- **Undo** on the corner card gives the slot back and puts the earlier Concentration back.

Casting isn't always a roll, and a roll isn't always a cast: a spell with something to roll offers Cast and roll, at the
level picked (Brett, 2026-10-31), and Roll without spending a slot.
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app import characters as chars
from app import companions, ddb_bridge, ddb_sheet, web
from app import spellbook as sb
from app.character_views import ordinal
from app.db import get_db
from app.item_use import _guard as _player, _sheet
from app.models import Character
from app.templating import templates

router = APIRouter()


def _guard(db: Session, request: Request, character_id: int):
    ch, user = _player(db, request, character_id)
    if not ddb_bridge.plays(db, ch):
        raise HTTPException(404)
    return ch, user


RITUAL, NO_SLOT, FREE = "ritual", "none", "free"
HIGHER = "A higher slot: nothing more for this spell"


def ways(sheet: dict, e: dict) -> list[dict]:
    """How this spell can be cast now, the lowest slot first: {"way", "label", "level"}, with what a higher slot rolls."""
    uses = e.get("uses")
    out = [{"way": FREE, "level": e["level"], "name": "", "label": f"Free: {e['from']} ({uses['left']} left)"}] if uses and uses.get("left") and e.get("from") else []
    lowest = {}  # the lowest slot of each kind left: a higher one does nothing more for a spell that doesn't grow
    for s in sb.slot_levels(sheet):
        if e["level"] and s["level"] >= e["level"] and s["left"] > 0:
            a = e["avgs"].get(s["level"])
            kind = "pact" if s.get("pact") else "slot"
            low = lowest.setdefault(kind, s["level"]) == s["level"]
            out.append({"way": f"{kind}:{s['level']}", "level": s["level"], "name": f"{ordinal(s['level'])}-level",
                        "label": f"{ordinal(s['level'])}-level{' Pact' if s.get('pact') else ''} ({s['left']} left)" + (f" · {a['dice']}" if a else ""),
                        "group": "" if low or e.get("higher", True) else HIGHER})
    if e["ritual"]:
        out.append({"way": RITUAL, "level": e["level"], "name": "a Ritual", "label": "As a Ritual (no slot, 10 minutes longer)"})
    if e["level"] and not (out and out[0]["way"] == FREE):
        out.append({"way": NO_SLOT, "level": e["level"], "name": "", "label": "No slot"})
    # Grouped in the window (feedback 24): Wild Companion's first, then the usual ways, then the higher slots that do
    # nothing more for this spell (still yours to spend: saving a lower slot for something else is a choice)
    return wild_ways(sheet, e, out) + [w for w in out if not w.get("group")] + [w for w in out if w.get("group")]


WILD_GROUP = "Wild Companion: a Magic action, no components; always Fey, it leaves at your next Long Rest"
WILD = "wild"  # Wild Companion (a Druid's, 2024): Find Familiar from a Wild Shape use, or a slot, always Fey, gone at a Long Rest


def wild_use(sheet: dict) -> dict | None:
    """The Wild Shape uses Wild Companion spends: {"field", "left"}, or None (no Wild Companion, or none left)."""
    if not any(f.get("name") == "Wild Companion" for f in sheet.get("features") or []):
        return None
    a = next((a for a in sheet.get("actions") or [] if a.get("name") == "Wild Shape" and a.get("uses") and a.get("id")), None)
    return {"field": f"uses:{a['id']}", "left": a["uses"].get("left", 0)} if a else None


def wild_ways(sheet: dict, e: dict, slots: list[dict]) -> list[dict]:
    """Find Familiar as Wild Companion (Brett, Nov 4, docs/mockups/steeds-summons/ board 2): a Wild Shape use, or the
    lowest slot left, first in the list; the familiar is always Fey and leaves at the next Long Rest."""
    w = wild_use(sheet) if e.get("name") == companions.FIND_FAMILIAR else None
    if not w:
        return []
    out = [{"way": WILD, "level": e["level"], "name": "a Wild Shape use", "label": f"A Wild Shape use · Wild Companion ({w['left']} left)",
            "wild": True}] if w["left"] > 0 else []
    low = next((s for s in slots if s["way"].startswith(("slot:", "pact:"))), None)
    if low:
        out.append({**low, "way": f"{WILD}-{low['way']}", "label": f"{low['label']} · Wild Companion", "wild": True})
    for w in out:
        w["group"] = WILD_GROUP
    return out


def _spell(db: Session, ch: Character, key: str) -> tuple[dict, dict]:
    sheet = _sheet(db, ch)
    e = next((x for x in sb.entries(sheet) if x["key"] == key), None)
    if e is None:
        raise HTTPException(404)
    return sheet, e


@router.get("/characters/{character_id:int}/cast")
def window(request: Request, character_id: int, key: str, db: Session = Depends(get_db)):
    """What a spell's Cast opens, in the roll window."""
    ch, _ = _guard(db, request, character_id)
    sheet, e = _spell(db, ch, key)
    # Find Familiar brings the familiar (Brett, 2026-11-04, Creatures as Characters board 2): its form and what it is
    forms = companions.familiars(ch, sheet) if e["name"] == companions.FIND_FAMILIAR and companions.on(db, ch) else None
    # A summon spell or Find Steed brings askdnd's own creature (app/summons.py; Brett chose A, Nov 4)
    summon = companions.summon_entry(db, ch, e["name"]) if companions.on(db, ch) else None
    first, kind, named = companions.picked(forms or [])
    reachable = ddb_bridge.reachable(ch)
    # The familiar is askdnd's, like a Wild Shape form: with the sheet out of reach, still as a Ritual or without a slot
    offline = forms is not None and not reachable
    can = [w for w in ways(sheet, e) if not offline or w["way"] in (RITUAL, NO_SLOT, FREE)]
    return templates.TemplateResponse(request, "_cast_window.html", {"c": ch, "e": e, "ways": can, "way_groups": way_groups(can, e),
                                                                     "reachable": reachable, "offline": offline,
                                                                     "ends": ch.concentration if e["conc"] and ch.concentration and ch.concentration.get("key") != key else None,
                                                                     "form_no": form_no(sheet, ch, e["name"]), "familiars": forms, "ff_first": first,
                                                                     "ff_kind": kind, "ff_name": named, "kinds": companions.KINDS,
                                                                     "ff_new": companions.new_forms(sheet) if forms is not None and reachable else [],
                                                                     "summon": summon, "steed_before": companions.steed_before(ch, summon) if summon else None})


def way_groups(can: list[dict], e: dict) -> list[tuple[str, list[dict]]]:
    """The Cast at list in its groups, in order (feedback 24): with only the usual ways, one group with no heading."""
    groups: list[tuple[str, list[dict]]] = []
    for w in can:
        g = w.get("group") or ""
        if not groups or groups[-1][0] != g:
            groups.append((g, []))
        groups[-1][1].append(w)
    return [(g or (e["name"] if len(groups) > 1 else ""), ws) for g, ws in groups]


def form_no(sheet: dict, ch: Character, name: str) -> str:
    """In a Wild Shape form, a spell the form can't cast: said in Cast's window, never stopped (Brett, 2026-11-03: the
    DM rules). "" when it can be cast, or the character isn't in a form."""
    from app import wild_shape as ws

    d = ws.druid(sheet) if ch.wild_shape else None
    if not d or d.get("beast_spells") or name in (d.get("moon_spells") or []):
        return ""
    if d.get("moon_spells"):
        return f"In Wild Shape you can cast only Circle of the Moon spells: {name} isn't one. The DM rules."
    return "In Wild Shape you can't cast spells. The DM rules."


@router.post("/characters/{character_id:int}/cast")
def cast(request: Request, character_id: int, key: str, way: str = Form(""), familiar: str = Form(""), kind: str = Form(""),
         familiar_name: str = Form(""), choice: str = Form(""), again: str = Form(""), creature_name: str = Form(""),
         look: str = Form(""), db: Session = Depends(get_db)):
    """Cast it: the slot on its way to D&D Beyond, Concentration begun."""
    ch, _ = _guard(db, request, character_id)
    sheet, e = _spell(db, ch, key)
    can = ways(sheet, e)
    chosen = next((w for w in can if w["way"] == way), None)
    if can and not chosen:
        raise HTTPException(409, f"{e['name']}: that slot isn't left.")
    undo = {"key": key}
    said = f"Cast {e['name']}" + (f" as {chosen['name']}" if chosen and chosen["way"] == RITUAL else f" at {chosen['name']}" if chosen and chosen["name"] else "")
    if chosen and chosen["way"] == FREE:
        said += f": mark the use on D&D Beyond ({e['from']})"
    wild = bool(chosen and chosen.get("wild"))
    if wild:  # Wild Companion: always Fey, and gone at the next Long Rest
        kind = "Fey"
        said = f"Cast {e['name']} as Wild Companion" + (f", {chosen['name']} slot" if chosen["way"] != WILD else ", a Wild Shape use")
    if chosen and chosen["way"] == WILD:
        ddb_bridge.reach(ch)
        ddb_bridge.add(db, ch, "use", {"field": wild_use(sheet)["field"], "delta": 1}, f"{ch.name}: Wild Shape used (Wild Companion)")
        undo["spent"] = WILD
    elif chosen and chosen["way"] not in (RITUAL, NO_SLOT, FREE):
        way = chosen["way"].removeprefix(f"{WILD}-")
        ddb_bridge.reach(ch)
        _spend(ch, db, way, 1, f"{ch.name}: {e['name']}, {chosen['name']} slot")
        undo["spent"] = way
    if e["name"] == companions.FIND_FAMILIAR and companions.on(db, ch) and (familiar or companions.familiars(ch, sheet)):
        back, brought = companions.cast(db, ch, sheet, familiar, kind, familiar_name, wild=wild)
        undo |= back
        said += f": {brought}"
    if companions.on(db, ch) and (entry := companions.summon_entry(db, ch, e["name"])):
        back, brought = companions.summon(ch, sheet, entry, chosen["level"] if chosen and chosen.get("level") else e["level"] or entry["spell_level"],
                                          choice, creature_name, look, again=again == "1")
        undo |= back
        said += f": {brought}"
    if e["conc"]:
        was = ch.concentration
        ch.concentration = sb.concentrating(e, chosen["level"] if chosen else e["level"]) | ({"was": {k: v for k, v in was.items() if k != "was"}} if was else {})
        said += f": Concentrating on {e['name']}" + (f", {was['spell']} ended" if was and was.get("key") != key else "")
    db.commit()
    return JSONResponse({"text": said, "undo": undo, "undoUrl": f"/characters/{ch.id}/cast/undo", "deliver": web.deliver_now(ch)})


def _spend(ch: Character, db: Session, way: str, delta: int, label: str) -> None:
    kind, level = way.split(":", 1)
    ddb_bridge.add(db, ch, "use", {"field": way, "delta": delta, "max": ddb_sheet.most(ch.snapshot.raw, kind, level)}, label)


@router.post("/characters/{character_id:int}/cast/undo")
def undo_cast(request: Request, character_id: int, key: str = Form(...), spent: str = Form(""), companions_were: str = Form("", alias="companions"),
              healed: str = Form(""), added: str = Form(""), db: Session = Depends(get_db)):
    """The corner card's Undo: the slot back, Concentration as it was, and a familiar where it was."""
    ch, _ = _guard(db, request, character_id)
    _, e = _spell(db, ch, key)
    if companions_were or healed or added:  # (a familiar where it was; a summon or steed as it was; a new form not added)
        companions.uncast(db, ch, companions_were, healed, added)
    if spent == WILD:
        sheet = chars.character_summary(ch) or {}
        if (w := wild_use(sheet)):
            ddb_bridge.reach(ch)
            ddb_bridge.add(db, ch, "use", {"field": w["field"], "delta": -1}, f"{ch.name}: Wild Shape use back ({e['name']} undone)")
    elif spent:
        if spent.split(":", 1)[0] not in ("slot", "pact"):
            raise HTTPException(404)
        ddb_bridge.reach(ch)
        _spend(ch, db, spent, -1, f"{ch.name}: {e['name']} undone")
    if ch.concentration and ch.concentration.get("key") == key:
        ch.concentration = ch.concentration.get("was")
    db.commit()
    return JSONResponse({"text": f"{e['name']} undone", "deliver": web.deliver_now(ch)})
