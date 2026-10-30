"""After leveling on D&D Beyond (roadmap 1.9): what's new and how it works.

A character is leveled on D&D Beyond. When a read of the sheet finds a higher level, askdnd compares it with the copy it
had and keeps what changed: Hit Points, Proficiency Bonus, new features, spells and slots. Battle shows it to the character's
player until they've read it, each new thing opening its usual side panel. It informs: nothing here says what to pick.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app import ddb_bridge, web
from app.db import get_db
from app.item_use import _guard as _player

router = APIRouter()


def changes(old: dict | None, new: dict) -> dict | None:
    """What's new between two copies of a sheet when the level went up, else None."""
    was, now = (old or {}).get("level") or 0, new.get("level") or 0
    if not was or now <= was:
        return None
    have = {f["key"] for f in old.get("features") or []}
    spells = {s["key"] for s in old.get("spells") or []}
    slots = {s["level"]: s["max"] for s in (old.get("spell_slots") or {}).get("slots") or []}
    return {"from": was, "to": now,
            "hp": ((new.get("hit_points") or {}).get("max") or 0) - ((old.get("hit_points") or {}).get("max") or 0),
            "pb": new.get("proficiency_bonus") if new.get("proficiency_bonus") != old.get("proficiency_bonus") else None,
            "features": [{"key": f["key"], "name": f["name"]} for f in new.get("features") or [] if f["key"] not in have],
            "spells": [{"key": s["key"], "name": s["name"]} for s in new.get("spells") or [] if s["key"] not in spells],
            "slots": [{"level": s["level"], "more": s["max"] - slots.get(s["level"], 0)} for s in (new.get("spell_slots") or {}).get("slots") or []
                      if s["max"] > slots.get(s["level"], 0)]}


def merged(kept: dict | None, new: dict) -> dict:
    """Two levels before the player has read the first: one list, from the level they last read."""
    if not kept:
        return new
    def more(k):
        return kept[k] + [x for x in new[k] if x not in kept[k]]

    return {**new, "from": kept["from"], "hp": kept["hp"] + new["hp"], "pb": new["pb"] or kept["pb"], "features": more("features"), "spells": more("spells"),
            "slots": more("slots")}


@router.post("/characters/{character_id:int}/level-up/read")
def read(request: Request, character_id: int, db: Session = Depends(get_db)):
    """Got it: the player has read what's new."""
    ch, _ = _player(db, request, character_id)
    if not ddb_bridge.plays(db, ch):
        raise HTTPException(404)
    ch.level_up = None
    db.commit()
    out = Response(status_code=204)
    out.headers["HX-Trigger"] = web.changed(ch)
    return out
