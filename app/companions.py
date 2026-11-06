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
from app import companion_story as story
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


# Find Familiar's forms (2024 Player's Handbook; the DM can allow another Beast of Challenge Rating 0): a new one is added to
# Extras through the bridge by its D&D Beyond monster id (the 2024 Monster Manual's, rules_data.pictures)
FORMS = ("Bat", "Cat", "Frog", "Hawk", "Lizard", "Octopus", "Owl", "Rat", "Raven", "Spider", "Weasel")
NEW = "new:"  # a form askdnd is adding, kept by its monster id until D&D Beyond has it (`adopt`)


def new_forms(sheet: dict) -> list[dict]:
    """The rules' familiar forms not on the sheet's Extras yet: {"id": "new:<monster id>", "name"}."""
    from app import rules_data

    pics, have = rules_data.pictures(), {str(c.get("monster_id")) for c in yours(sheet) if c.get("group_id") == FAMILIAR}
    out = []
    for name in FORMS:
        mid = str((pics.get(name.lower()) or {}).get("ddb_id") or "")
        if mid and mid not in have:
            out.append({"id": NEW + mid, "name": name})
    return out


def adopt(db: Session, ch: Character, summary: dict, raw: dict) -> None:
    """A read that finds the form askdnd added: the familiar askdnd kept by its monster id is that creature now, and
    D&D Beyond is put in step with it (Active, what it is, its name)."""
    kept = dict(ch.companions or {})
    new = [k for k in kept if k.startswith(NEW)]
    if not new:
        return
    named = {}
    for k in new:
        found = next((c for c in yours(summary) if c.get("group_id") == FAMILIAR and str(c.get("monster_id")) == k[len(NEW):]
                      and str(c["id"]) not in kept), None)
        if found:
            entry = kept.pop(k)
            kept[str(found["id"])] = {x: v for x, v in entry.items() if x != "name"}
            if entry.get("name"):
                named[str(found["id"])] = entry["name"]
    if kept != (ch.companions or {}):
        ch.companions = kept
        in_step(db, ch, named or None, raw, summary)


def _was(was: dict, keys) -> str:
    """What Undo puts back: only these entries as they were (None: there was none), so a creature changed since (another
    summon, a steed's damage) is left as it is (review, Nov 4)."""
    return json.dumps({k: was.get(k) for k in keys})


def picked(forms: list[dict]) -> tuple[str, str, str]:
    """The Cast window's first choice: the one in play (here or away), else one that disappeared, else the first; what
    it was made last time; and the name it was given (its name on D&D Beyond, when that isn't its stat block's)."""
    f = next((x for x in forms if x["where"] in ("here", "away")), None) or next((x for x in forms if x["where"] == "gone"), None) \
        or (forms[0] if forms else None)
    return (str(f["id"]), f["made"] or KINDS[0], f["name"] if f["name"] != f["kind"] else "") if f else ("", KINDS[0], "")


def in_step(db: Session, ch: Character, named: dict | None = None, raw: dict | None = None, sheet: dict | None = None) -> None:
    """D&D Beyond's Extras as askdnd has them (option A): the familiar that's here Active, with its creature type, and
    every other familiar form switched off; `named` ({id: name}) gives a form its name there. Where the sheet can be
    reached; each only when D&D Beyond holds something else. `raw`, `sheet`: a read not stored yet (characters.store)."""
    if not ddb_bridge.on_for(db, ch) or not ddb_bridge.reachable(ch) or not (raw or (ch.snapshot and ch.snapshot.raw)):
        return
    raw, sheet = raw or ch.snapshot.raw, sheet or chars.character_summary(ch)
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


def master_options(ch: Character, sheet: dict) -> list[dict]:
    """On the master's own Battle (Creatures as Characters board 3; Find Familiar, 2024 PHB): a familiar that's been cast
    adds See through its eyes (a Bonus Action, until the start of the master's next turn, with its senses) and Deliver a
    touch spell (its Reaction, within 100 feet); greyed with the reason while it's in the pocket dimension or gone (as
    Sheet greys what a form can't do: `form_why`). Rows of their own: pinned and ordered like any other."""
    out = []
    for c in yours(sheet):
        w = where(ch, c)
        if c.get("group_id") != FAMILIAR or not w:
            continue
        name = c["name"]
        why = "" if w == "here" else (f"{name} is in the pocket dimension: bring it back first" if w == "away"
                                      else f"{name} is gone: cast Find Familiar to bring it back")
        senses = card(sheet, c).get("senses") or ""
        out += [{"key": f"rule:familiar:{c['id']}:eyes", "kind": "feature", "cost": "Bonus action", "name": f"See through {name}'s eyes",
                 "tags": [FIND_FAMILIAR], "common": True, "form_why": why,
                 "meta": "Until the start of your next turn" + (f" · its senses: {senses}" if senses else ""),
                 "text": f"You see what {name} sees and hear what it hears until the start of your next turn, with any special "
                         f"senses it has (Find Familiar)."},
                {"key": f"rule:familiar:{c['id']}:touch", "kind": "feature", "cost": "Reaction", "name": "Deliver a touch spell",
                 "tags": [FIND_FAMILIAR], "common": True, "form_why": why,
                 "meta": f"When you cast a spell with a range of touch: {name} delivers it, within 100 ft, with its Reaction",
                 "text": f"When you cast a spell with a range of touch, {name} can deliver the touch instead of you, if it's within "
                         f"100 feet of you; delivering it takes its Reaction (Find Familiar)."}]
    return out


def cast(db: Session, ch: Character, sheet: dict, chosen: str, kind: str, name: str = "", wild: bool = False) -> tuple[dict, str]:
    """Find Familiar cast with this form and kind: it's here, and any other form of it isn't (one familiar at a time).
    Returns what Undo needs and what the corner card says."""
    forms = {str(c["id"]): c for c in yours(sheet) if c.get("group_id") == FAMILIAR}
    if kind not in KINDS:
        raise HTTPException(409, "Celestial, Fey or Fiend?")
    if str(chosen).startswith(NEW):
        return _cast_new(db, ch, sheet, forms, str(chosen), kind, name, wild)
    c = forms.get(str(chosen))
    if c is None:
        raise HTTPException(409, "Which familiar? Pick its form.")
    was = dict(ch.companions or {})
    before = next((forms[i] for i, v in was.items() if i in forms and (v or {}).get("state") in ("here", "away")), None)
    ch.companions = {**{i: v for i, v in was.items() if i not in forms}, str(c["id"]): {"state": "here", "kind": kind, **({"wild": True} if wild else {})}}
    k = card(sheet, c)
    name = name.strip()[:60]
    shown = name or k["name"]
    form = shown if shown == k["kind"] else f"{shown}, a {k['kind']}"
    said = f"{shown} ({kind}) is here" if before is None or str(before["id"]) == str(c["id"]) else f"Your familiar takes a new form: {form} ({kind})"
    undo = {"companions": _was(was, set(forms) | {str(c["id"])})}
    if k["hp"]["removed"] and not k["hp"]["waits"] and ddb_bridge.on_for(db, ch) and ddb_bridge.reachable(ch):  # (back whole)
        ddb_bridge.add(db, ch, "creature_hp", {"creature": k["id"], "name": f"{ch.name}'s {k['name']}", "amount": k["hp"]["removed"], "max": k["hp"]["max"]},
                       f"{ch.name}'s {k['name']} back, whole")
        undo["healed"] = f"{k['id']}:{k['hp']['removed']}"
    in_step(db, ch, {str(c["id"]): name} if name and name != k["name"] else None)
    story.note(db, ch, story.FAMILIAR, "cast", name=name or (k["name"] if k["name"] != k["kind"] else ""), form=k["kind"], kind=kind, creature="familiar")
    return undo, said


def _cast_new(db: Session, ch: Character, sheet: dict, forms: dict, chosen: str, kind: str, name: str, wild: bool = False) -> tuple[dict, str]:
    """Find Familiar cast as a form the sheet doesn't have yet (board 2, "or a new one"): added to Extras through the
    bridge; until D&D Beyond has it, askdnd keeps the familiar by its monster id (`adopt` ties it to the new creature)."""
    form = next((f for f in new_forms(sheet) if f["id"] == chosen), None)
    if form is None:
        raise HTTPException(409, "That isn't one of Find Familiar's forms, or it's on Extras already.")
    if not ddb_bridge.on_for(db, ch) or not ddb_bridge.reachable(ch):
        raise HTTPException(409, f"A new form is added on D&D Beyond: {ch.name}'s sheet needs to be open (or pick a form on Extras).")
    was = dict(ch.companions or {})
    name = name.strip()[:60]
    ch.companions = {**{i: v for i, v in was.items() if i not in forms and not i.startswith(NEW)},
                     chosen: {"state": "here", "kind": kind, **({"name": name} if name and name != form["name"] else {}), **({"wild": True} if wild else {})}}
    mid = chosen[len(NEW):]
    ddb_bridge.add(db, ch, "set", {"field": f"familiar_add:{mid}", "value": 1}, f"{ch.name}'s familiar: a {form['name']} added to Extras")
    in_step(db, ch)  # (any other form switched off)
    story.note(db, ch, story.FAMILIAR, "cast", name=name if name != form["name"] else "", form=form["name"], kind=kind, creature="familiar")
    shown = f"{name}, a {form['name']}" if name and name != form["name"] else f"a {form['name']}"
    touched = set(forms) | {k for k in was if k.startswith(NEW)} | {chosen}
    return {"companions": _was(was, touched), "added": mid}, f"Your familiar: {shown} ({kind}), added to D&D Beyond's Extras"


# ---- Wild Companion (a Druid's): a familiar from a Wild Shape use or a slot, always Fey, gone at the next Long Rest

def wild_leaving(ch: Character, sheet: dict) -> list[str]:
    """The familiars Wild Companion brought that are still around (here or in the pocket dimension), by name."""
    return [c["name"] for c in yours(sheet) if c.get("group_id") == FAMILIAR and where(ch, c) in ("here", "away")
            and ((ch.companions or {}).get(str(c["id"])) or {}).get("wild")]


def wild_leave(db: Session, ch: Character, sheet: dict) -> list[str]:
    """A Long Rest: Wild Companion's familiar leaves (switched off on D&D Beyond, never deleted). Its names."""
    gone, kept = [], dict(ch.companions or {})
    for c in yours(sheet):
        v = kept.get(str(c["id"])) or {}
        if c.get("group_id") == FAMILIAR and v.get("wild") and v.get("state") in ("here", "away"):
            kept[str(c["id"])] = {**v, "state": "gone", "why": "Long Rest (Wild Companion)"}
            gone.append(c["name"])
    if gone:
        ch.companions = kept
        in_step(db, ch)
        story.note(db, ch, story.FAMILIAR, "left")
    return gone


# ---- askdnd's own: a summon, Find Steed's steed (app/summons.py; Brett chose A, Nov 4)

def summon_entry(db: Session, ch: Character, spell: str) -> dict | None:
    """The stat block a spell brings (the campaign's books: the Player's Handbook), or None."""
    from app import rules_data

    return next((e for e in rules_data.catalog("summon", db, ch.campaign_id) if e.get("spell") == spell), None)


def _caster(sheet: dict, entry: dict) -> tuple[int, int]:
    """The spell attack and save DC it uses: the class whose spell it is, else the first."""
    rows = sheet.get("spellcasting") or []
    row = next((r for r in rows if r.get("class") in (entry.get("classes") or [])), rows[0] if rows else {})
    try:
        return int(str(row.get("attack") or "+0").replace("−", "-")), int(row.get("save_dc") or 0)
    except ValueError:
        return 0, int(row.get("save_dc") or 0)


def steed_before(ch: Character, entry: dict) -> dict | None:
    """Find Steed's "the one that disappeared": the steed it had, as it was (its kind, name and look), once it's gone."""
    from app import summons

    kept = (ch.companions or {}).get(str(summons.own_id(entry.get("key") or entry["name"]))) or {}
    if not kept.get("own") or kept.get("state") == "here":  # (one that's here is replaced by the new one: the spell's rule)
        return None
    return kept.get("c")


def summon(ch: Character, sheet: dict, entry: dict, level: int, choice: str, name: str = "", look: str = "",
           again: bool = False, db: Session | None = None) -> tuple[dict, str]:
    """A summon spell or Find Steed cast at `level`: its creature is here, its numbers worked out for that level and
    its master; a summon the same spell brought before goes (one at a time). Find Steed `again`: the steed that
    disappeared, with its kind, name and look. Returns what Undo needs and what the corner card says."""
    from app import summons

    if again and (before := steed_before(ch, entry)):
        choice, name, look = before.get("choice") or choice, before.get("name") if before.get("name") != entry["name"] else "", before.get("look") or look
    if entry.get("choose") and choice not in entry["choose"]:
        raise HTTPException(409, f"{entry['name']}: {', '.join(entry['choose'])}?")
    attack, dc = _caster(sheet, entry)
    c = summons.creature(entry, level, choice, attack, dc, name=name.strip()[:60], look=look.strip()[:60])
    was = dict(ch.companions or {})
    ch.companions = {**was, str(c["id"]): {"own": True, "state": "here", "c": {k: v for k, v in c.items() if k not in ("removed", "temp")},
                                           "removed": 0, "temp": 0}}
    what = f"{c['name']} ({choice})" if choice else c["name"]
    if db is not None and entry.get("spell") == summons.STEED:
        story.note(db, ch, story.STEED, "cast", name=name.strip()[:60] if name.strip() else "", form=entry["name"], kind=choice, creature=str(c["id"]))
    return {"companions": _was(was, {str(c["id"])})}, f"{what} is here, at level {level}"


def own_hp(ch: Character, c: dict, k: dict, change: int = 0, temp: int | None = None) -> str:
    """Damage (negative) or healing for one of askdnd's own creatures, or its Temporary Hit Points: kept in askdnd
    (nothing on D&D Beyond: it has no such creature). At 0 Hit Points it disappears, as its spell says."""
    kept = dict((ch.companions or {}).get(str(c["id"])) or {})
    who = f"{ch.name}'s {k['name']}"
    if temp is not None:
        kept["temp"] = temp
        said = f"{who}: {temp} Temporary Hit Points"
    else:
        removed, t = kept.get("removed") or 0, kept.get("temp") or 0
        if change < 0:
            soak = min(t, -change)
            t, removed = t - soak, min(k["hp"]["max"], removed + (-change - soak))
        else:
            removed = max(0, removed - change)
        kept["removed"], kept["temp"] = removed, t
        said = f"{who} {'took' if change < 0 else 'regained'} {abs(change)}"
        if removed >= k["hp"]["max"]:
            kept["state"], kept["why"] = "gone", "0 Hit Points"
            said += ": at 0 Hit Points it disappears"
    ch.companions = {**(ch.companions or {}), str(c["id"]): kept}
    return said


def uncast(db: Session, ch: Character, companions: str, healed: str, added: str = "") -> None:
    """Undo's half for the creature: the entries the cast changed as they were, the Hit Points taken again, and a new
    familiar form not added after all (while its change is still waiting)."""
    try:
        was = json.loads(companions) if companions else None
    except ValueError:
        was = None
    if isinstance(was, dict):
        now = dict(ch.companions or {})
        for k, v in was.items():
            if v is None:
                now.pop(k, None)
            else:
                now[k] = v
        ch.companions = now
    if added.isdigit():
        from sqlalchemy import select

        from app.models import BridgeIntent

        for it in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == ch.id, BridgeIntent.state.in_(("waiting", "not_yet")))):
            if (it.data or {}).get("field") == f"familiar_add:{added}":
                ddb_bridge.dismiss(db, it.id)
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
    story.note(db, ch, story.FAMILIAR, {"away": "away", "here": "back", "gone": "dismissed"}[to])
    db.commit()
    said = {"away": f"{c['name']} is in the pocket dimension", "here": f"{c['name']} is back", "gone": f"{c['name']} is dismissed: casting Find Familiar brings it back"}[to]
    return Response(status_code=204, headers={"HX-Trigger": web.changed(ch, said, deliver=True)})
