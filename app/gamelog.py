"""askdnd's rolls in D&D Beyond's Game Log (Brett, 2026-10-29, DECISIONS: option B).

A player's roll made in askdnd also goes into the D&D Beyond game their character is in, so the DM sees it where they
play: the extension sends it from the player's own D&D Beyond tab (extension/askdnd-bridge/ddb-page.js), in the Game
Log's own message shape, marked as askdnd's and never as D&D Beyond's: the message's source is "askdnd" and the roll's
name ends in ⓐ ("Pistol ⓐ: To Hit"). Tested on Vi on Oct 29: D&D Beyond shows them live and keeps them in the Game
Log's history, with advantage, a damage type in place of "Damage", private rolls and healing. No dice set is named, so
D&D Beyond shows its basic dice rather than one the roll never used. askdnd's Table rolls stay the record: the extension
doesn't pass these back (ddb_bridge.heard_in_game skips askdnd's own), and D&D Beyond may stop taking them.

`messages(db, row, character)` builds them here, so the extension only fills in what its tab knows (who is signed in,
the message's id and time). They go only where the bridge works on the character and its sheet is in a D&D Beyond game.
"""

from app import ddb_bridge
from app.models import Character, TableRoll
from app.table_rolls import D20_KINDS, parse_formula

SOURCE, MARK = "askdnd", "ⓐ"
ROLL_TYPE = {"attack": "to hit", "check": "check", "save": "save", "death": "save", "heal": "heal", "temp": "heal",
             "dice": "roll", "bonus": "roll"}
OP = {"adv": 2, "dis": 1}  # D&D Beyond's keep highest / keep lowest
KIND = {"adv": "advantage", "dis": "disadvantage"}


def _name(row: TableRoll, kind: str) -> str:
    """D&D Beyond's names: "Con" for a Con save (the type says Save), "Death" for a death save; then askdnd's mark."""
    label = row.label
    if kind in ("save", "check") and label.lower().endswith((" save", " check")):
        label = label.rsplit(" ", 1)[0]
    if kind == "death":
        label = "Death"
    return f"{label[:60]} {MARK}" + (" crit" if row.crit else "")


def _set(sides: int, dice: list[int], op: int = 0) -> dict:
    return {"count": len(dice), "dieType": f"d{sides}", "dice": [{"dieType": f"d{sides}", "dieValue": v} for v in dice], "operation": op}


def _sets_from(formula: str, dice: list[int]) -> list[dict]:
    """The dice of "2d6+1d8+3" in order, as a set per die size."""
    parsed = parse_formula(formula.split(" ")[0] if formula else "")
    sets, i = [], 0
    for count, sides in (parsed[0] if parsed else []):
        sets.append(_set(sides, dice[i:i + count]))
        i += count
    return sets


def _extras(row: TableRoll) -> tuple[list[dict], int]:
    """Bless's d4 and the like as sets of their own (a die that subtracts, Bane's, goes into the bonus instead)."""
    sets, counted = [], 0
    for x in row.extras or []:
        parsed = parse_formula(x.get("formula", "").lstrip("+"))
        if x.get("dice") and parsed and x.get("total", 0) >= 0:
            sets += _sets_from(x["formula"].lstrip("+"), x["dice"])
            counted += sum(x["dice"])
    return sets, counted


def _roll(row: TableRoll, kind: str, part: dict | None = None) -> dict:
    """One roll in the Game Log's shape: its dice by size, the bonus, the total; advantage kept as D&D Beyond keeps it."""
    src = part or {"dice": row.dice, "kept": row.kept, "total": row.total, "extras": row.extras}
    extra_sets, extra_sum = _extras(row) if not part else ([], 0)
    if kind in D20_KINDS:
        sets = [_set(20, list(src["dice"]), OP.get(row.mode, 0))]
        counted = src["kept"] or 0
        roll_kind, roll_type = KIND.get(row.mode, ""), ROLL_TYPE[kind]
    else:
        lines = row.parts or []
        if lines:
            sets = [s for x in lines for s in _sets_from(x.get("formula", ""), x.get("dice", []))]
        else:
            sets = _sets_from(row.formula, list(row.dice))
        counted = sum(d["dieValue"] for s in sets for d in s["dice"])
        types = {x.get("kind") for x in lines if x.get("kind")}
        roll_type = types.pop() if kind == "damage" and len(types) == 1 else ("damage" if kind == "damage" else ROLL_TYPE.get(kind, "roll"))
        roll_kind = "critical hit" if row.crit else ""
    sets += extra_sets
    constant = src["total"] - counted - extra_sum
    values = [d["dieValue"] for s in sets for d in s["dice"]]
    shown = f"({','.join(map(str, src['dice']))})" if kind in D20_KINDS and len(src["dice"]) > 1 else "+".join(map(str, values))
    return {"diceNotation": {"constant": constant, "set": sets}, "rollKind": roll_kind, "rollType": roll_type,
            "result": {"constant": constant, "text": f"{shown}{constant:+d}" if constant else shown, "total": src["total"], "values": values}}


def _audience(row: TableRoll, raw: dict) -> tuple[str, str] | None:
    """Who sees it, as the Game Log addresses it: everyone in the game, or one person (the DM, or the player alone)."""
    camp = raw.get("campaign") or {}
    if row.visibility == "table":
        return "gameId", str(camp.get("id"))
    if row.visibility == "self":
        return "userId", "self"  # (the sheet puts in whoever is signed in there)
    return ("userId", str(camp["dmUserId"])) if camp.get("dmUserId") else None


def messages(db, row: TableRoll, character: Character | None) -> list[dict]:
    """What the extension sends to the Game Log for this roll (a roll's follow-up, its damage or reroll, on its own),
    or [] where it doesn't go: no character, the bridge not on it, or its sheet not in a D&D Beyond game."""
    if not character or not character.ddb_id or not ddb_bridge.on_for(db, character) or not character.snapshot:
        return []
    raw = character.snapshot.raw or {}
    game, aim = (raw.get("campaign") or {}).get("id"), _audience(row, raw)
    if not game or not aim:
        return []
    kind = row.kind
    if kind == "reroll":  # a d20 rolled again: its own roll, of the kind it rerolled
        root = db.get(TableRoll, row.parent_id)
        kind = root.kind if root else "check"
    rays = [x for x in row.parts or [] if x.get("kept") is not None] if kind in D20_KINDS else []
    rolls = [(f"{_name(row, kind)} {x.get('label', '')}".strip(), _roll(row, kind, x)) for x in rays] or [(_name(row, kind), _roll(row, kind))]
    scope, target = aim
    context = {"entityId": str(character.ddb_id), "entityType": "character", "messageScope": scope, "messageTarget": target,
               "name": character.name}
    return [{"gameId": str(game), "source": SOURCE, "eventType": "dice/roll/fulfilled", "persist": True,
             "entityId": str(character.ddb_id), "entityType": "character", "messageScope": scope, "messageTarget": target,
             "data": {"action": name, "context": context, "rollId": f"askdnd-{row.id}-{i}", "rolls": [r]}}
            for i, (name, r) in enumerate(rolls)]
