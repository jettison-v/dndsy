"""Your turn's bar on askdnd's table (slice 2; docs/plans/2026-11-06-table-build-plan.md, docs/mockups/table-slices/
Turn-bar). Under the middle of the table page, for the character you play: movement left this turn (− and + 5 ft until
the map counts it, Dash adds your Speed again), what you've used of your Action, Bonus Action and Reaction, and your
Battle pins by what they cost, each with its Roll, Cast or Use as on Battle. Off your turn it keeps only your Reactions
and a readied action.

askdnd counts and shows; it never stops you (going past your Speed only turns red, for the DM to rule). What you've
used is kept on the character (`Character.turn`) and cleared when its next turn begins, from whichever fight runs
(app/fight.py heard: D&D Beyond's VTT's or askdnd's own). Rolling from the bar marks its cost used (app.js "your
turn's bar"); pressing a mark unticks it.

**Your scratch pad** (Prepare your turn; Brett chose A and B, Nov 13, docs/mockups/prepare-your-turn/: "keep it simple
to start, like an executable scratch pad"): while others play, a short list jotted from your Battle with + Add (an
attack, a spell, a Bonus Action, a Reaction to keep), in any order, each with a note if you like; on your turn each line
has its own Roll, Cast or Use, in any order, nothing required. Kept in `Character.turn["pad"]` ({key, note, done}); your
turn's start keeps it, its end clears it (app/fight.py starts_over).
"""

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app import character_views as views
from app import characters as chars
from app import ddb_bridge, picks, readying, web
from app import conditions as cond
from app.auth import current_user
from app.db import get_db
from app.models import Campaign, Character

router = APIRouter()

COSTS = [("Action", "action", "Action"), ("Bonus action", "bonus", "Bonus"), ("Reaction", "reaction", "Reaction")]
USES = {k for _, k, _ in COSTS}
COST_KEY = {c: k for c, k, _ in COSTS} | {"No action": "none"}
STEP = 5  # feet, one square
PAD_MAX = 8  # lines on the scratch pad
NOTE_MAX = 60


def pad(ch: Character, everything: list[dict]) -> list[dict]:
    """The scratch pad's lines as Battle options (one no longer on the sheet drops out): {o, cost, note, done}."""
    by_key = {o["key"]: o for o in everything}
    out = []
    for p in (ch.turn or {}).get("pad") or []:
        if isinstance(p, dict) and (o := by_key.get(p.get("key"))):
            out.append({"o": o, "cost": COST_KEY.get(o.get("cost"), "none"), "note": str(p.get("note") or "")[:NOTE_MAX], "done": bool(p.get("done"))})
    return out


def speed(sheet: dict | None) -> int:
    """Walking Speed now (conditions applied), in feet."""
    s = (sheet or {}).get("speed")
    if isinstance(s, dict):
        return int(s.get("walk") or 0)
    return 0


def state(ch: Character, sheet: dict | None) -> dict:
    """{"moved", "dash", "used", "speed", "total", "left", "over", "pct_used", "pct_left"} for the bar."""
    t = ch.turn or {}
    moved, dash = max(0, int(t.get("moved") or 0)), max(0, int(t.get("dash") or 0))
    sp = speed(sheet)
    total = sp * (1 + dash)
    left = total - moved
    scale = max(total, moved, 1)
    return {"moved": moved, "dash": dash, "used": [u for u in t.get("used") or [] if u in USES], "speed": sp,
            "total": total, "left": max(left, 0), "over": max(-left, 0),
            "pct_used": round(100 * min(moved, total) / scale), "pct_left": round(100 * max(left, 0) / scale),
            "pct_over": round(100 * max(-left, 0) / scale)}


def whose(db: Session, user: dict | None, f: dict | None) -> Character | None:
    """Whose bar this person sees: the character of theirs whose turn it is (a test account plays several), else the
    one they play here."""
    if f and f.get("yours") and f.get("now") and f["now"].get("character"):
        ch = db.get(Character, f["now"]["character"])
        if ch is not None and picks.can_edit(db, user, ch):
            return ch
    return picks.my_character(db, user)


def context(db: Session, user: dict | None, campaign: Campaign | None, f: dict | None) -> dict | None:
    """What `_turn_bar.html` draws, or None (no character of theirs here)."""
    ch = whose(db, user, f)
    if ch is None or campaign is None or ch.campaign_id != campaign.id:
        return None
    sheet = ddb_bridge.as_shown(db, ch, chars.character_summary(ch)) or {}
    if sheet:
        from app.character_pages import listed  # (what it's under: Exhaustion and Speed 0 conditions change its Speed)

        sheet["speed"] = cond.speed_now(sheet.get("speed"), listed(db, ch, sheet))
    mine = picks.picks(db, ch, user)
    cols = views.battle_columns(sheet, mine["star"], mine["order"], pinned_only=True) if sheet else {}
    every = views.options(sheet, mine["star"]) if sheet else []
    on_turn = bool(f and not f.get("waiting") and f.get("now") and f["now"].get("character") == ch.id)
    groups = []
    for cost, key, label in COSTS:
        col = cols.get(cost) or {}
        rows = list(col.get("shown") or []) + list(col.get("items") or [])
        if not on_turn and f and key != "reaction":
            continue  # (off your turn: only Reactions)
        groups.append({"key": key, "label": label, "rows": rows})
    lines = pad(ch, every)
    on_pad = {x["o"]["key"] for x in lines}
    pick = [{"label": label, "rows": sorted((o for o in every if o.get("cost") == cost and o["key"] not in on_pad),
                                            key=lambda o: (not o.get("starred"), o.get("name") or ""))}
            for cost, label in (("Action", "Action"), ("Bonus action", "Bonus Action"), ("Reaction", "Reaction"), ("No action", "No action"))]
    return {"c": ch, "sheet": sheet, "turn": state(ch, sheet), "groups": groups, "in_fight": bool(f and not f.get("waiting")),
            "pad": lines, "pad_pick": [g for g in pick if g["rows"]], "pad_full": len(lines) >= PAD_MAX,
            "on_turn": on_turn, "readied": readying.shown(sheet, ch) if sheet else None,
            "can_play": picks.can_edit(db, user, ch) and ddb_bridge.plays(db, ch),
            "can_use": picks.can_edit(db, user, ch) and ddb_bridge.on_for(db, ch)}


def _player(db: Session, request: Request, character_id: int) -> Character:
    user, ch = current_user(request), db.get(Character, character_id)
    if not user or ch is None or not picks.can_edit(db, user, ch):
        raise HTTPException(404)
    return ch


@router.post("/characters/{character_id:int}/turn")
def change(request: Request, character_id: int, what: str = Form(...), n: int = Form(0), cost: str = Form(""),
           key: str = Form(""), note: str = Form(""), pad_key: str = Form("", alias="pad"), db: Session = Depends(get_db)):
    """The bar's buttons: `move` by n feet (− and + 5 ft), `dash` (n=1 adds one, −1 takes it back), `use` toggles a
    cost (`cost`: action, bonus, reaction; n=1 marks it used, 0 unticks, -1 toggles; `pad`: the scratch pad line it was
    rolled from, marked done), `start` starts the turn over (the scratch pad stays). The scratch pad: `pad_add` and
    `pad_remove` a line by its Battle option's `key`, `pad_note` its note, `pad_clear` all of it."""
    ch = _player(db, request, character_id)
    t = dict(ch.turn or {})
    used = [u for u in t.get("used") or [] if u in USES]
    lines = [dict(p) for p in t.get("pad") or [] if isinstance(p, dict)]
    if what.startswith("pad_"):
        if what == "pad_add":
            sheet = chars.character_summary(ch) or {}
            if not any(o["key"] == key for o in views.options(sheet, set())):
                raise HTTPException(422)
            if key not in {p.get("key") for p in lines} and len(lines) < PAD_MAX:
                lines.append({"key": key})
        elif what == "pad_remove":
            lines = [p for p in lines if p.get("key") != key]
        elif what == "pad_note":
            for p in lines:
                if p.get("key") == key:
                    p["note"] = " ".join(note.split())[:NOTE_MAX]
        elif what == "pad_clear":
            lines = []
        else:
            raise HTTPException(422)
        t["pad"] = lines
        if not lines:
            t.pop("pad", None)
        ch.turn = t or None
        db.commit()
        return Response(status_code=204, headers={"HX-Trigger": web.changed(ch)})
    if what == "move":
        t["moved"] = max(0, int(t.get("moved") or 0) + max(-60, min(60, n)))
    elif what == "dash":
        t["dash"] = max(0, min(4, int(t.get("dash") or 0) + (1 if n >= 0 else -1)))
    elif what == "use" and (cost in USES or (cost == "none" and pad_key)):
        if cost in USES:
            on = (cost not in used) if n < 0 else bool(n)
            used = [u for u in used if u != cost] + ([cost] if on else [])
            t["used"] = used
        if pad_key and lines:
            t["pad"] = [{**p, "done": True} if p.get("key") == pad_key else p for p in lines]
    elif what == "start":
        t = {"pad": [{k: v for k, v in p.items() if k != "done"} for p in lines]} if lines else {}
    else:
        raise HTTPException(422)
    ch.turn = t or None
    db.commit()
    return Response(status_code=204, headers={"HX-Trigger": web.changed(ch)})
