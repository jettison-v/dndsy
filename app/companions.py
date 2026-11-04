"""A familiar in play (Your creatures, round 2; Brett, 2026-11-04, docs/mockups/creatures-as-characters/ boards 2 and 3:
"Find Familiar spell creates the creature that can be chosen, new or one you have already created, dismisses the old
one"). A familiar exists only once it's cast: askdnd keeps where each is (Character.companions, by its D&D Beyond id;
app/creatures.py `where`), by the 2024 rules of Find Familiar:

- **Casting Find Familiar** (the Cast window, app/casting.py) picks its form from the familiars on the sheet's Extras and
  what it is (Celestial, Fey or Fiend). One familiar at a time: one that's here or away takes the new form. One that
  disappeared comes back whole (its Hit Points on D&D Beyond, through the bridge).
- **The pocket dimension**: sent there and brought back (each a Magic action of its master's), on its Battle.
- **Gone**: at 0 Hit Points (back only when cast again), or dismissed forever.

**D&D Beyond kept in step** (Brett, 2026-11-04, option A; extension 0.11.0, `in_step`): the familiar that's here is
switched on (Active) on the sheet's Extras with what it is (its creature type) and the name it was given, and every other
familiar form is switched off, after each change here, through the bridge where the sheet can be reached (askdnd's own
state changes either way). Never deletes anything there.

Only for the character's player or the DM, as with its Hit Points. Adding a form that isn't on Extras and the familiar's
picture come next."""

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import characters as chars
from app import ddb_bridge, ddb_fields, hit_points, vtt, web
from app import spellbook as sb
from app.auth import current_user
from app.creatures import FAMILIAR, KINDS, card, placed, where, yours
from app.db import get_db
from app.models import Campaign, Character

router = APIRouter()
FIND_FAMILIAR = "Find Familiar"
MOVES = {"away": ("here",), "here": ("away",), "gone": ("here", "away")}  # (to: from)


def on(db: Session, ch: Character) -> bool:
    return vtt.on(db.get(Campaign, ch.campaign_id) if ch.campaign_id else None, "creatures")


def spell_key(sheet: dict | None) -> str:
    """The character's Find Familiar, for its Cast window ("" without it)."""
    return next((e["key"] for e in sb.entries(sheet) if e["name"] == FIND_FAMILIAR), "") if sheet else ""


def familiars(ch: Character, sheet: dict) -> list[dict]:
    """The familiars on the sheet's Extras (the forms it can take), with where each is."""
    return [placed(ch, card(sheet, c), c) for c in yours(sheet) if c.get("group_id") == FAMILIAR]


def picked(forms: list[dict]) -> tuple[str, str, str]:
    """The Cast window's first choice: the one in play (here or away), else one that disappeared, else the first; what
    it was made last time; and the name it was given (its name on D&D Beyond, when that isn't its stat block's)."""
    f = next((x for x in forms if x["where"] in ("here", "away")), None) or next((x for x in forms if x["where"] == "gone"), None) \
        or (forms[0] if forms else None)
    return (str(f["id"]), f["made"] or KINDS[0], f["name"] if f["name"] != f["kind"] else "") if f else ("", KINDS[0], "")


def in_step(db: Session, ch: Character, named: dict | None = None) -> None:
    """D&D Beyond's Extras as askdnd has them (option A): the familiar that's here Active, with its creature type, and
    every other familiar form switched off; `named` ({id: name}) gives a form its name there. Where the sheet can be
    reached; each only when D&D Beyond holds something else."""
    if not ddb_bridge.on_for(db, ch) or not ddb_bridge.reachable(ch) or not ch.snapshot or not ch.snapshot.raw:
        return
    raw, sheet = ch.snapshot.raw, chars.character_summary(ch)
    for c in yours(sheet):
        if c.get("group_id") != FAMILIAR:
            continue
        cid, here = c["id"], where(ch, c) == "here"
        want = {f"creature_active:{cid}": here}
        if here:
            want[f"creature_type:{cid}"] = ddb_fields.MONSTER_TYPES.get(((ch.companions or {}).get(str(cid)) or {}).get("kind"))
        if (named or {}).get(str(cid)):
            want[f"creature_name:{cid}"] = named[str(cid)]
        for field, v in want.items():
            if v is not None and ddb_fields.value(raw, field) != v:
                ddb_bridge.add(db, ch, "set", {"field": field, "value": v}, f"{ch.name}'s {c['name']}: {ddb_fields.show(raw, field, v)}")


def cast(db: Session, ch: Character, sheet: dict, chosen: str, kind: str, name: str = "") -> tuple[dict, str]:
    """Find Familiar cast with this form and kind: it's here, and any other form of it isn't (one familiar at a time).
    Returns what Undo needs and what the corner card says."""
    forms = {str(c["id"]): c for c in yours(sheet) if c.get("group_id") == FAMILIAR}
    c = forms.get(str(chosen))
    if c is None:
        raise HTTPException(409, "Which familiar? Add its form on D&D Beyond first (Extras › Manage Extras › Familiar).")
    if kind not in KINDS:
        raise HTTPException(409, "Celestial, Fey or Fiend?")
    was = dict(ch.companions or {})
    before = next((forms[i] for i, v in was.items() if i in forms and (v or {}).get("state") in ("here", "away")), None)
    ch.companions = {**{i: v for i, v in was.items() if i not in forms}, str(c["id"]): {"state": "here", "kind": kind}}
    k = card(sheet, c)
    name = name.strip()[:60]
    shown = name or k["name"]
    form = shown if shown == k["kind"] else f"{shown}, a {k['kind']}"
    said = f"{shown} ({kind}) is here" if before is None or str(before["id"]) == str(c["id"]) else f"Your familiar takes a new form: {form} ({kind})"
    undo = {"companions": json.dumps(was)}
    if k["hp"]["removed"] and not k["hp"]["waits"] and ddb_bridge.on_for(db, ch) and ddb_bridge.reachable(ch):  # (back whole)
        ddb_bridge.add(db, ch, "creature_hp", {"creature": k["id"], "name": f"{ch.name}'s {k['name']}", "amount": k["hp"]["removed"], "max": k["hp"]["max"]},
                       f"{ch.name}'s {k['name']} back, whole")
        undo["healed"] = f"{k['id']}:{k['hp']['removed']}"
    in_step(db, ch, {str(c["id"]): name} if name and name != k["name"] else None)
    return undo, said


def uncast(db: Session, ch: Character, companions: str, healed: str) -> None:
    """Undo's half for the familiar: where each was, and the Hit Points taken again."""
    try:
        was = json.loads(companions) if companions else None
    except ValueError:
        was = None
    if isinstance(was, dict):
        ch.companions = was
    if healed and ":" in healed:
        cid, n = healed.split(":", 1)
        if cid.isdigit() and n.isdigit():
            ddb_bridge.add(db, ch, "creature_hp", {"creature": int(cid), "name": f"{ch.name}'s familiar", "amount": -int(n)}, f"{ch.name}'s familiar: back undone")
    in_step(db, ch)


def at_zero(ch: Character, c: dict, k: dict, damage: int) -> bool:
    """Damage that takes a familiar to 0 Hit Points: it disappears (back only when Find Familiar is cast again)."""
    if c.get("group_id") != FAMILIAR or where(ch, c) != "here":
        return False
    if k["hp"]["current"] - max(0, damage - k["hp"]["temp"]) > 0:
        return False
    ch.companions = {**(ch.companions or {}), str(c["id"]): {**((ch.companions or {}).get(str(c["id"])) or {}), "state": "gone", "why": "0 Hit Points"}}
    return True  # (its master's route keeps D&D Beyond in step once the damage is on its way: in_step)


@router.post("/characters/{character_id:int}/creatures/{creature_id:int}/where")
def move(request: Request, character_id: int, creature_id: int, form=web.FormBody, db: Session = Depends(get_db)):
    """Its master sends it to the pocket dimension or brings it back (each a Magic action), or dismisses it forever."""
    user = current_user(request)
    ch = db.get(Character, character_id)
    if not user or not ch or not on(db, ch) or not hit_points.can_apply(db, user, ch):
        raise HTTPException(404)
    sheet = chars.character_summary(ch)
    c = next((x for x in yours(sheet) if str(x["id"]) == str(creature_id) and x.get("group_id") == FAMILIAR), None)
    to = str(form.get("to") or "")
    if c is None or to not in MOVES:
        raise HTTPException(404)
    if where(ch, c) not in MOVES[to]:
        raise HTTPException(409, f"It's {placed(ch, card(sheet, c), c)['where_word'].lower()}.")
    kept = (ch.companions or {}).get(str(c["id"])) or {}
    ch.companions = {**(ch.companions or {}), str(c["id"]): {**kept, "state": to, "why": "dismissed" if to == "gone" else ""}}
    in_step(db, ch)
    db.commit()
    said = {"away": f"{c['name']} is in the pocket dimension", "here": f"{c['name']} is back", "gone": f"{c['name']} is dismissed for good"}[to]
    return Response(status_code=204, headers={"HX-Trigger": web.changed(ch, said, deliver=True)})
