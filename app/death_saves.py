"""Death saving throws (roadmap step 6, docs/mockups/death-saves.html; Brett, 2026-10-29: the three recommendations).

At 0 Hit Points a character is dying: askdnd keeps the marks where its hit points were (the Dying tile, `_char.html`),
reminds its player as its turn starts in a heard fight (app/fight.py follow), and makes every change on the D&D Beyond
sheet through the bridge, like hit points. The rules (2024 Player's Handbook), in askdnd's words:

- **The roll:** at the start of each of your turns at 0 Hit Points, a d20 with no bonus: 10 or more is a success, under
  10 a failure; a 1 is two failures; a 20 brings you back with 1 Hit Point. A death save rolled while dying **marks
  itself** (`roll`): the player pressed Roll for it, and the rule says what it counts as. A reroll or an added die on
  it moves the mark (`replaces`).
- **Three successes:** Stable, no more death saves (1 Hit Point after 1d4 hours unless healed). **Three failures:** the
  DM rules; askdnd shows it and marks nothing more. askdnd never decides that someone dies.
- **Damage at 0** is a failure, a critical hit two (hit_points.work; crossable for a ruling); damage while Stable starts
  the saves over. **Massive damage** (left over at least the Hit Point maximum) is pointed out to the DM.
- **Dropping to 0** starts Unconscious on the sheet; **healing from 0** ends it and clears the marks (both crossable in
  the hit points window).
"""

import copy

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from app import characters as chars
from app import conditions as cond
from app import ddb_bridge, picks, web
from app.auth import current_user
from app.db import get_db
from app.models import Campaign, Character

router = APIRouter()

UNCONSCIOUS = cond.ddb_field("Unconscious")
MARKS = {"success": (1, 0), "failure": (0, 1), "nat1": (0, 2), "nat20": (0, 0)}  # (successes, failures)
SAID = {"success": "a success", "failure": "a failure", "nat1": "a natural 1: two failures", "nat20": "a natural 20: back with 1 Hit Point"}


def outcome(total: int, nat: int | None) -> str:
    """What a death save's d20 counts as."""
    if nat == 20:
        return "nat20"
    if nat == 1:
        return "nat1"
    return "success" if total >= 10 else "failure"


def state(summary: dict | None) -> dict | None:
    """None while the character has Hit Points; at 0: {"success", "fail", "stable", "out": three failures (the DM's
    ruling)}."""
    hp = (summary or {}).get("hit_points") or {}
    if not hp or hp.get("current", 1) > 0:
        return None
    ds = (summary or {}).get("death_saves") or {}
    s, f = ds.get("success", 0), ds.get("fail", 0)
    return {"success": s, "fail": f, "stable": bool(ds.get("stable")), "out": f >= 3}


def rolling(st: dict | None) -> bool:
    """Dying and still rolling: at 0, neither Stable nor at three failures."""
    return bool(st) and not st["stable"] and not st["out"]


def _counts(st: dict) -> dict:
    return {"successCount": st["success"], "failCount": st["fail"]}


def roll(db: Session, ch: Character, result: str, replaces: str = "") -> str:
    """Make a death save's result on the sheet when the character is dying and the bridge reaches it; what's said, or ""
    (nothing to mark). `replaces`: the result this roll counted as before a reroll or an added die."""
    if result not in MARKS or not ddb_bridge.on_for(db, ch) or not ddb_bridge.reachable(ch) or replaces == "nat20":
        return ""
    st = state(ddb_bridge.as_shown(db, ch, chars.character_summary(ch)))
    if not st:
        return ""
    if replaces in MARKS:  # take the earlier result's marks back off
        s, f = MARKS[replaces]
        st = {**st, "success": max(0, st["success"] - s), "fail": max(0, st["fail"] - f)}
        st["stable"], st["out"] = st["success"] >= 3, st["fail"] >= 3
        if result == replaces:
            return ""
    elif not rolling(st):
        return ""
    if result == "nat20":
        up(db, ch, 1, f"{ch.name}: a natural 20 on a death save, back with 1 Hit Point")
        return f"{ch.name} is back up with 1 Hit Point"
    s, f = MARKS[result]
    after = {"successCount": min(3, st["success"] + s), "failCount": min(3, st["fail"] + f)}
    ddb_bridge.add(db, ch, "set", {"field": "death", "value": after}, f"{ch.name}: death save, {SAID[result]}")
    if after["successCount"] >= 3:
        tell(db, ch, "stable", "Stable: three death save successes, no more death saves")
        return f"{ch.name} is Stable: no more death saves"
    if after["failCount"] >= 3:
        tell(db, ch, "out", "three death save failures: your ruling")
        return f"{ch.name}: three death save failures. The DM rules"
    return f"Death save: {SAID[result]} ({after['successCount']} ✓ · {after['failCount']} ✗)"


def hit(db: Session, ch: Character, failures: int, label: str) -> None:
    """Damage at 0 Hit Points: one failure, two for a critical hit; damage while Stable starts the saves over."""
    st = state(ddb_bridge.as_shown(db, ch, chars.character_summary(ch))) or {"success": 0, "fail": 0, "stable": False}
    base = {"successCount": 0, "failCount": 0} if st["stable"] else _counts(st)
    after = {**base, "failCount": min(3, base["failCount"] + failures)}
    ddb_bridge.add(db, ch, "set", {"field": "death", "value": after}, label)


def down(db: Session, ch: Character) -> None:
    """Dropping to 0 Hit Points: Unconscious starts on the sheet, and the marks start from none."""
    ddb_bridge.add(db, ch, "set", {"field": "death", "value": {"successCount": 0, "failCount": 0}}, f"{ch.name}: death saves from none")
    ddb_bridge.add(db, ch, "set", {"field": UNCONSCIOUS, "value": True}, f"{ch.name}: Unconscious (0 Hit Points)")


def up(db: Session, ch: Character, heal: int, label: str) -> None:
    """Hit Points again from 0: the healing (when it isn't already made), then Unconscious ends and the marks clear.
    askdnd's own Unconscious goes too."""
    if heal:
        ddb_bridge.add(db, ch, "hp", {"amount": heal}, label)
    ddb_bridge.add(db, ch, "set", {"field": "death", "value": {"successCount": 0, "failCount": 0}}, f"{ch.name}: death saves cleared")
    ddb_bridge.add(db, ch, "set", {"field": UNCONSCIOUS, "value": False}, f"{ch.name}: no longer Unconscious")
    if any(c.get("name") == "Unconscious" for c in ch.conditions or []):
        ch.conditions = [c for c in ch.conditions if c.get("name") != "Unconscious"]


def tell(db: Session, ch: Character, kind: str, text: str) -> None:
    """A corner card for the character's player and the DM while a fight is heard (app/fight.py reminders): down to
    0, massive damage, Stable, three failures."""
    from app import fight

    campaign = db.get(Campaign, ch.campaign_id) if ch.campaign_id else None
    if not fight.shown(campaign, dm=True):
        return
    fight.lock(db, campaign)
    f = copy.deepcopy(campaign.fight)
    fight.remind(f, ch, kind, "Death saves", text)
    campaign.fight = f


@router.post("/characters/{character_id:int}/death")
def private_roll(request: Request, character_id: int, result: str = Form(""), replaces: str = Form(""),
                 db: Session = Depends(get_db)):
    """A death save rolled privately, in the player's own browser (app.js deathPrivate): its result marks the sheet as a
    table roll's does (app/table_rolls.py death_mark). Only the character's own player."""
    user, ch = current_user(request), db.get(Character, character_id)
    if not user or not ch or not picks.can_edit(db, user, ch) or result not in MARKS or (replaces and replaces not in MARKS):
        raise HTTPException(404)
    said = roll(db, ch, result, replaces)
    if not said:
        return Response(status_code=204)
    db.commit()
    return JSONResponse({"text": said, "character": ch.id, "deliver": web.deliver_now(ch)})
