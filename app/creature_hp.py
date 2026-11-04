"""Your creatures' Hit Points on D&D Beyond (slice 2, docs/plans/2026-11-03-your-creatures.md; Brett, Nov 3: "keep D&D
Beyond up to date"): − and + for one of the character's creatures through the bridge, and its maximum kept there to the one
the rule works out (app/creatures.py) by askdnd itself (Brett, Nov 4: askdnd keeps D&D Beyond's Extras in step)."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import characters as chars
from app import companions, ddb_bridge, hit_points, vtt, web
from app.auth import current_user
from sqlalchemy import select

from app.creatures import card, find, yours
from app.db import get_db
from app.models import BridgeIntent, Campaign, Character

router = APIRouter()
# Kept on the creature in the sheet's Extras, as D&D Beyond keeps them (Brett, Nov 3: "keep D&D Beyond up to date"): − and
# + through the bridge (`creature_hp`, PUT creature/hp; extension 0.10.0). D&D Beyond counts them against the maximum it
# shows, its stat block's unless one is set there (a Homunculus Servant: 1), so askdnd sets the one the rule works out
# there itself (its character value 43, `keep_max`), and − and + wait until that's on its way.


def keep_max(db: Session, ch: Character, summary: dict) -> None:
    """After a read of the sheet (characters.store): each of its creatures whose maximum grows with its master gets the
    rule's number on D&D Beyond, the first time and after its master levels up (Brett, Nov 4, Creatures as Characters:
    no button). Never over a number someone else typed there, and once per number: one given up or undone isn't made again."""
    camp = db.get(Campaign, ch.campaign_id) if ch.campaign_id else None
    if not ch.id or not vtt.on(camp, "creatures"):
        return
    asked = [i for i in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == ch.id, BridgeIntent.kind == "set"))
             if str((i.data or {}).get("field", "")).startswith("creature_max:")]
    for c in yours(summary):
        k = card(summary, c)
        if not k["hp"]["fix"]:
            continue
        field, ours = f"creature_max:{k['id']}", [i for i in asked if i.data.get("field") == f"creature_max:{k['id']}"]
        if any(i.data.get("value") == k["hp"]["fix"] or i.state in ddb_bridge.OPEN for i in ours):
            continue
        if c.get("max_set") and c["max_set"] not in [i.data.get("value") for i in ours if i.state == "live"]:
            continue  # (typed on D&D Beyond by its player or DM: theirs)
        ddb_bridge.add(db, ch, "set", {"field": field, "value": k["hp"]["fix"]}, f"{ch.name}'s {k['name']}: maximum {k['hp']['fix']} on D&D Beyond")


def _guard(db: Session, request: Request, character_id: int, creature_id: int):
    user = current_user(request)
    ch = db.get(Character, character_id)
    if not user or not ch or not ddb_bridge.on_for(db, ch) or not hit_points.can_apply(db, user, ch) \
            or not vtt.on(db.get(Campaign, ch.campaign_id) if ch.campaign_id else None, "creatures"):
        raise HTTPException(404)
    sheet = ddb_bridge.as_shown(db, ch, chars.character_summary(ch))  # (with what's on its way: a maximum being set counts)
    found = find(sheet, creature_id)
    if not found:
        raise HTTPException(404)
    ddb_bridge.reach(ch)
    return ch, card(sheet, found)


@router.post("/characters/{character_id:int}/creatures/{creature_id:int}/hp")
def change_hp(request: Request, character_id: int, creature_id: int, form=web.FormBody, db: Session = Depends(get_db)):
    """Damage (−) or healing (+) for one of the character's creatures, or its Temporary Hit Points, through the bridge."""
    ch, k = _guard(db, request, character_id, creature_id)
    if k["hp"]["waits"]:
        raise HTTPException(409, f"D&D Beyond still shows {k['hp']['ddb_max']} for its maximum: askdnd sets {k['hp']['rule']} there the next time the sheet is read.")
    amount, temp = str(form.get("amount") or "").strip().lstrip("+"), str(form.get("temp") or "").strip()
    who = f"{ch.name}'s {k['name']}"
    if temp:
        if not temp.isdigit():
            raise HTTPException(409, "Temporary Hit Points are a number.")
        ddb_bridge.add(db, ch, "creature_hp", {"creature": k["id"], "name": who, "amount": 0, "temp": int(temp)}, f"{who}: {temp} Temporary Hit Points")
        said = f"{who}: {temp} Temporary Hit Points"
    else:
        sign = -1 if form.get("to") == "damage" else 1
        if not amount.isdigit() or not 0 < int(amount) <= 999:
            raise HTTPException(409, "How many Hit Points?")
        n = int(amount)
        ddb_bridge.add(db, ch, "creature_hp", {"creature": k["id"], "name": who, "amount": sign * n, "max": k["hp"]["max"]},
                       f"{who} {'took' if sign < 0 else 'regained'} {n}")
        said = f"{who} {'took' if sign < 0 else 'regained'} {n}"
        if sign < 0 and companions.at_zero(ch, find(chars.character_summary(ch), creature_id), k, n):
            said += ": at 0 Hit Points it disappears, until Find Familiar is cast again"
            companions.in_step(db, ch)
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": web.changed(ch, said + ": on its way to D&D Beyond", deliver=True)})
