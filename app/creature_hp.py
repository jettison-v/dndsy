"""Your creatures' Hit Points on D&D Beyond (slice 2, docs/plans/2026-11-03-your-creatures.md; Brett, Nov 3: "keep D&D
Beyond up to date"): − and + for one of the character's creatures through the bridge, and its maximum set there to the
one the rule works out (app/creatures.py), each said and pressed, never by itself."""

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import characters as chars
from app import ddb_bridge, hit_points, vtt, web
from app.auth import current_user
from app.creatures import card, find
from app.db import get_db
from app.models import Campaign, Character

router = APIRouter()
# Kept on the creature in the sheet's Extras, as D&D Beyond keeps them (Brett, Nov 3: "keep D&D Beyond up to date"): − and
# + through the bridge (`creature_hp`, PUT creature/hp; extension 0.10.0). D&D Beyond counts them against the maximum it
# shows, its stat block's unless one is set there (a Homunculus Servant: 1), so − and + wait until it shows the one the
# rule works out: Set on D&D Beyond (its character value 43) first, said and pressed, never by itself.


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
    if k["hp"]["fix"]:
        raise HTTPException(409, f"D&D Beyond shows {k['hp']['ddb_max']} for its maximum: set it to {k['hp']['fix']} first, so both count the same.")
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
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": web.changed(ch, said + ": on its way to D&D Beyond", deliver=True)})


@router.post("/characters/{character_id:int}/creatures/{creature_id:int}/max")
def set_max(request: Request, character_id: int, creature_id: int, db: Session = Depends(get_db)):
    """D&D Beyond's maximum for it set to the one the rule works out (its character value 43, as its own sheet sets it)."""
    ch, k = _guard(db, request, character_id, creature_id)
    if not k["hp"]["fix"]:
        raise HTTPException(409, "D&D Beyond already shows that maximum.")
    who = f"{ch.name}'s {k['name']}"
    ddb_bridge.add(db, ch, "set", {"field": f"creature_max:{k['id']}", "value": k["hp"]["fix"]}, f"{who}: maximum {k['hp']['fix']} on D&D Beyond")
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": web.changed(ch, f"{who}: maximum {k['hp']['fix']}, on its way to D&D Beyond", deliver=True)})
