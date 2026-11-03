"""What a character is right now: the 2024 conditions (Invisible, Poisoned, Prone…, Exhaustion by level)
and effects from magic items (Enlarged from a Potion of Growth…), plus the magic-item actions that
start them (roadmap step 7; Brett 2026-10-22: one Status row for every condition).

- Character.conditions: [{"name": "Invisible", "source": "Ring of Invisibility", "note": "…", "level": 2}].
  Everyone at the table sees them on Battle; only the character's player starts or ends them.
- Item actions: curated in app/data/item_actions.json (our own summaries); otherwise an equipped
  magic item whose text says "take a Magic action" or "as a Bonus Action" gets a plain option.
- Effects on rolls (roll_effects): listed in the roll window with the reason, never chosen for you:
  "while the source is in sight", "unless the target can see you" and the like are the DM's call.

The conditions themselves (which there are, in the rules' order) are the SRD's Rules Glossary (app/rules_data.py);
what each does to your rolls is askdnd's reading of them, below. Summaries are ours (rules_terms holds the short text).
"""

import json
import re
from functools import cache
from pathlib import Path

from app import ddb_fields, rules_data, rules_terms

DATA = Path(__file__).parent / "data" / "item_actions.json"

ADV, DIS, NOTE = "adv", "dis", "note"
STR_DEX = {"save:str": (NOTE, "you automatically fail Strength saving throws"), "save:dex": (NOTE, "you automatically fail Dexterity saving throws")}
INCAPACITATED = {"initiative": (DIS, "Disadvantage on Initiative (Incapacitated)")}

# What a condition does to your own rolls (Charmed, Deafened: nothing; Exhaustion goes by level, see roll_effects).
# Keys: attack, check, check:str (one ability), save:dex…, initiative, d20 (every d20 Test).
ON_ROLLS: dict[str, dict] = {
    "Blinded": {"attack": (DIS, "Disadvantage on your attack rolls")},
    "Frightened": {"attack": (DIS, "Disadvantage on your attack rolls while the source of your fear is in sight"),
                   "check": (DIS, "Disadvantage on ability checks while the source of your fear is in sight")},
    "Grappled": {"attack": (DIS, "Disadvantage on attack rolls against anyone other than the grappler")},
    "Incapacitated": {**INCAPACITATED},
    "Invisible": {"attack": (ADV, "Advantage on your attack rolls, unless the target can see you"),
                  "initiative": (ADV, "Advantage on Initiative")},
    "Paralyzed": {**STR_DEX, **INCAPACITATED},
    "Petrified": {**STR_DEX, **INCAPACITATED},
    "Poisoned": {"attack": (DIS, "Disadvantage on your attack rolls"), "check": (DIS, "Disadvantage on ability checks")},
    "Prone": {"attack": (DIS, "Disadvantage on your attack rolls")},
    "Restrained": {"attack": (DIS, "Disadvantage on your attack rolls"), "save:dex": (DIS, "Disadvantage on Dexterity saving throws")},
    "Stunned": {**STR_DEX, **INCAPACITATED},
    "Unconscious": {**STR_DEX, **INCAPACITATED},
}
# Every official condition, in the order the rules list them, with what it does to your rolls
CONDITIONS: dict[str, dict] = {name: ON_ROLLS.get(name, {}) for name in rules_data.condition_names()}
if set(ON_ROLLS) - set(CONDITIONS):
    raise ValueError(f"not conditions in the SRD: {sorted(set(ON_ROLLS) - set(CONDITIONS))}")
# Effects that aren't conditions but change what you can do, from items the party has or may find
EFFECTS: dict[str, dict] = {
    "Enlarged": {"check:str": (ADV, "Advantage on Strength checks"), "save:str": (ADV, "Advantage on Strength saving throws"),
                 "attack": (NOTE, "your weapon and Unarmed Strike hits deal an extra 1d4 damage")},
    "Water Breathing": {},
    "Flying": {},
}
EFFECT_TEXT = {
    "Enlarged": "Your size is one larger (Large if you were Medium). You have Advantage on Strength checks and Strength saving throws, and your weapon and Unarmed Strike hits deal an extra 1d4 damage.",
    "Water Breathing": "You can breathe underwater.",
    "Flying": "You have a Fly Speed. If you're in the air when it ends, you fall (unless the item says you descend safely).",
}
KNOWN = tuple(CONDITIONS) + tuple(EFFECTS)
MAGIC_ACTION = re.compile(r"\btake a Magic action\b", re.I)
BONUS_ACTION = re.compile(r"\bas a Bonus Action\b|\btake a Bonus Action\b", re.I)


@cache
def _curated() -> dict:
    return {k: v for k, v in json.loads(DATA.read_text()).items() if not k.startswith("_")}


@cache
def _option_sets() -> dict:
    return json.loads(DATA.read_text()).get("_options") or {}


def curated(it: dict) -> dict:
    """{"actions": [...], "on_use": {...}} for an item askdnd knows by name, else {}."""
    return _curated().get(it.get("base_name") or it.get("name") or "") or _curated().get(it.get("name") or "") or {}


def rules_text(name: str) -> str:
    """The condition's or effect's short rules summary, for the pill's pop-up."""
    return EFFECT_TEXT.get(name) or next((t.text for t in rules_terms.TERMS if t.name == name), "")


# How a condition shows on Battle (Brett, 2026-10-28; docs/mockups/conditions-on-battle.html): each its own colour
# (app.css --cond-*, by its slug) and icon (_cond_icons.html). The page's edge takes the colours of the newest three,
# so each one shows; Blinded's is black and Blinded or Unconscious also darken the page towards its edges.
EDGE = 3
DARKEN = ("Blinded", "Unconscious")


def slug(name: str) -> str:
    return _slug(name)


def edge(conditions: list[dict] | None) -> list[str]:
    """The slugs of the conditions whose colours the page's edge takes: Concentration's always when it's there (Brett,
    2026-10-29), then the newest of the rest, three in all (["concentration", "poisoned", "prone"])."""
    conc = [c for c in conditions or [] if c.get("name") == "Concentration"]
    rest = [c for c in conditions or [] if c.get("name") != "Concentration"]
    return [slug(c["name"]) for c in conc] + [slug(c.get("name", "")) for c in rest[len(rest) - (EDGE - len(conc)):]][::-1]


def darkens(conditions: list[dict] | None) -> bool:
    return any(c.get("name") in DARKEN for c in conditions or [])


# D&D Beyond holds the 15 conditions and Exhaustion on the sheet (Brett, 2026-10-28: synced both ways). Where the
# bridge works on a character, those are D&D Beyond's: askdnd shows what the sheet has and makes a change there;
# askdnd keeps only what D&D Beyond doesn't have (item effects, and where a condition came from). Elsewhere askdnd
# shows what's ticked on D&D Beyond along with its own.
ON_DDB = (*ddb_fields.CONDITIONS.values(), "Exhaustion")
DDB_ID = {name: cid for cid, name in ddb_fields.CONDITIONS.items()}


def ddb_field(name: str) -> str:
    """The bridge's field for one D&D Beyond holds (app/ddb_fields.py): "exhaustion", or "condition:<its id>"."""
    return "exhaustion" if name == "Exhaustion" else f"condition:{DDB_ID[name]}"


def from_field(field: str) -> str:
    """The condition a bridge field is, or "" (not a condition)."""
    kind, _, arg = field.partition(":")
    if kind == "exhaustion":
        return "Exhaustion"
    return ddb_fields.CONDITIONS.get(int(arg), "") if kind == "condition" and arg.isdigit() else ""


def with_changes(sheet: list[dict] | None, changes) -> list[dict] | None:
    """D&D Beyond's conditions with the bridge's changes on their way already made (each {"field", "value"}, oldest
    first), for what reads the stored summary and not ddb_bridge.as_shown (the menu bar)."""
    if sheet is None:
        return None
    out = list(sheet)
    for ch in changes:
        name = from_field(str(ch.get("field")))
        if name and not ch.get("value"):
            out = [c for c in out if c["name"] != name]
        elif name and not any(c["name"] == name for c in out):
            out.append({"name": name})
    return out


def from_sheet(data: dict | None) -> list[dict]:
    """The conditions ticked on D&D Beyond's sheet (its character data), in its order, Exhaustion with its level."""
    out = []
    for c in (data or {}).get("conditions") or []:
        if not isinstance(c, dict):
            continue
        if c.get("id") == ddb_fields.EXHAUSTION:
            if c.get("level"):
                out.append({"name": "Exhaustion", "level": int(c["level"])})
        elif ddb_fields.CONDITIONS.get(c.get("id")):
            out.append({"name": ddb_fields.CONDITIONS[c["id"]]})
    return out


def shown(own: list[dict] | None, sheet: list[dict] | None, synced: bool) -> list[dict]:
    """What a character is under now, oldest first: D&D Beyond's (`sheet`, from the summary; None from a copy read
    before askdnd kept them) in D&D Beyond's order, with askdnd's source and note for each, then askdnd's own in its
    order. Each says "on_ddb". The order holds while one comes or goes (Brett, 2026-10-29: ending the first mustn't
    move it). Synced (the bridge works on it), one askdnd holds but D&D Beyond doesn't is left out: D&D Beyond decides."""
    own = own or []
    if sheet is None:
        return [dict(c) for c in own]
    there, notes = {c["name"] for c in sheet}, {c.get("name"): c for c in own}
    return ([{**notes.get(c["name"], {}), **c, "on_ddb": True} for c in sheet]
            + [{**c, "on_ddb": False} for c in own if c.get("name") not in there and not (synced and c.get("name") in ON_DDB)])


# What conditions do to Speed (SRD 5.2.1 Rules Glossary): these say "Your Speed is 0 and can't increase", and each level
# of Exhaustion reduces it by 5 feet
SPEED_ZERO = ("Grappled", "Paralyzed", "Petrified", "Restrained", "Unconscious")


def speed_now(speed: dict | None, conditions: list[dict] | None) -> dict | None:
    """The sheet's speeds as the conditions that count leave them (`counts`, character_pages.listed): Exhaustion takes
    5 feet a level off each, and Speed 0 makes each 0. Each change is a part of Speed's sum with its reason, so its
    panel shows the working; it says what the rules make the number, never stops a move."""
    if not speed:
        return speed
    on = [c for c in conditions or [] if c.get("counts", True)]
    level = max((int(c.get("level") or 0) for c in on if c.get("name") == "Exhaustion"), default=0)
    zero = next((c["name"] for c in on if c.get("name") in SPEED_ZERO), None)
    if not level and not zero:
        return speed
    out, parts = dict(speed), list(speed.get("parts") or [("Walking", speed.get("walk") or 0)])
    for kind in [k for k in speed if k not in ("parts", "notes")]:
        out[kind] = 0 if zero else max(0, (speed[kind] or 0) - 5 * level)
    if level:
        parts.append((f"Exhaustion {level} (5 ft a level)", -min(5 * level, speed.get("walk") or 0)))
    if zero:
        parts.append((f"{zero}: Speed 0, and it can't increase", -sum(v for _, v in parts)))
    out["parts"] = parts
    return out


def usable(it: dict) -> bool:
    """An item whose powers work now: equipped (or attuned), and attuned if it needs attunement."""
    return bool(it.get("magic")) and (it.get("equipped") or it.get("attunement") == "attuned") and it.get("attunement") != "required"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def item_actions(it: dict) -> list[dict]:
    """The Battle options one item gives: curated actions, else a plain one read from its text.
    (Potions and other "Use an item" options keep theirs; see on_use.)"""
    if not usable(it):
        return []
    acts = curated(it).get("actions")
    if acts:
        return [{**a, "key": f"{it['key']}#{_slug(a['name'])}", "item": it["name"]} for a in acts]
    text = f"{it.get('summary') or ''} {it.get('text') or ''}"
    cost = "Action" if MAGIC_ACTION.search(text) else "Bonus action" if BONUS_ACTION.search(text) else None
    if not cost or it.get("battle") or curated(it):  # "Use an item: …" already covers potions, scrolls and charged items
        return []
    return [{"cost": cost, "name": f"Use: {it['name']}", "meta": ("Magic action" if cost == "Action" else "Bonus Action") + f" · {it['name']}",
             "text": it.get("summary") or "", "key": f"{it['key']}#use", "item": it["name"]}]


# What using an item costs (Brett, 2026-10-30: the column it sits in on Battle)
ITEM_COST = re.compile(r"\b(?:as|take|takes|use|uses|using|with)\s+(?:an?|its)\s+(Magic action|Utilize action|Bonus Action|Reaction|action)\b", re.I)
COST_SAID = {"no action": ("No action", "No action needed"), "action": ("Action", "Action"), "magic action": ("Action", "Magic action"), "utilize action": ("Action", "Utilize action"),
             "bonus action": ("Bonus action", "Bonus Action"), "reaction": ("Reaction", "Reaction")}


def item_options(it: dict) -> dict | None:
    """The kinds an item comes in, where the rules list them ({"label", "choices": [{"name", "cost", "what"}]}): which
    one a copy is, its player marks (app/item_use.py), so no note has to say."""
    name = curated(it).get("options")
    return _option_sets().get(name) if name else None


def _chosen(it: dict, choice: str) -> dict | None:
    return next((c for c in (item_options(it) or {}).get("choices") or [] if c["name"] == choice), None) if choice else None


def item_cost(it: dict, choice: str = "") -> tuple[str, str]:
    """(its column on Battle, what to call the cost; "" when the item doesn't say, in the Action column so askdnd isn't
    guessing). Every potion is a Bonus Action to drink or give (2024 DMG, Using a Potion); a scroll takes what its spell
    takes, an action unless its text says otherwise. Anything else, by its own words, for every table: never a value
    kept for one party's copy of an item (Brett, 2026-10-30: he corrects his party's inventory himself)."""
    if it.get("type") == "Potion":
        return COST_SAID["bonus action"]
    if (kind := _chosen(it, choice)):
        return COST_SAID[kind["cost"].lower()]
    if item_options(it):
        return ("Action", "")  # which kind it is decides: until it's marked, not guessed
    m = ITEM_COST.search(f"{it.get('summary') or ''} {it.get('text') or ''}")
    if m:
        return COST_SAID[m.group(1).lower()]
    return ("Action", "Action") if it.get("type") == "Scroll" else ("Action", "")


def cost_source(it: dict, choice: str = "") -> str:
    """Where item_cost's answer came from: "rule", "choice", "text" or "" (neither)."""
    if it.get("type") in ("Potion", "Scroll") and (it.get("type") == "Potion" or not ITEM_COST.search(f"{it.get('summary') or ''} {it.get('text') or ''}")):
        return "rule"
    if _chosen(it, choice):
        return "choice"
    if item_options(it):
        return ""
    return "text" if ITEM_COST.search(f"{it.get('summary') or ''} {it.get('text') or ''}") else ""


def _counts_charges(it: dict) -> bool:
    ch = it.get("charges")
    return bool(ch) and (ch["max"] > 1 or ch["reset"] != "Used up")


def item_left(it: dict) -> int:
    """How many uses it has now. D&D Beyond keeps a potion two ways, a count (×2) and a one-use mark: a stack less any
    marked used. Anything with several charges, or charges that come back, counts its charges."""
    ch = it.get("charges")
    if _counts_charges(it):
        return ch["left"]
    return max(0, it.get("count", it.get("quantity", 1)) - (ch["used"] if ch else 0))


def item_spends(it: dict) -> str:
    """What one use changes on D&D Beyond: "charges" (its marks) or "item" (its count). The last of a stack with a
    one-use mark takes the mark, as using it on D&D Beyond does."""
    return "charges" if _counts_charges(it) or (it.get("charges") and it.get("count", 1) <= 1) else "item"


def on_use(it: dict) -> dict | None:
    """What using a consumable starts ({"starts": "Enlarged", "note": "10 minutes…"}), made when it's used
    (app/item_use.py)."""
    return curated(it).get("on_use")


def roll_effects(conditions: list[dict] | None) -> dict[str, list[dict]]:
    """{"attack": [{"mode": "dis", "text": "Poisoned: Disadvantage on your attack rolls"}], "save:dex": [...], "d20": [...]}:
    what the roll window lists for each kind of roll."""
    out: dict[str, list[dict]] = {}
    for c in conditions or []:
        name = c.get("name") or ""
        label = name + (f" {c['level']}" if c.get("level") else "") + (f" ({c['source']})" if c.get("source") else "")
        effects = dict(CONDITIONS.get(name) or EFFECTS.get(name) or {})
        if name == "Exhaustion" and c.get("level"):
            effects["d20"] = (NOTE, f"−{2 * int(c['level'])} to this roll (−2 per level)")
        for roll, (mode, text) in effects.items():
            out.setdefault(roll, []).append({"mode": mode, "text": f"{label}: {text}"})
    return out


def add(conditions: list[dict] | None, name: str, source: str = "", note: str = "", level: int = 0) -> list[dict]:
    if name not in KNOWN:
        raise ValueError("unknown condition")
    rest = [c for c in conditions or [] if c.get("name") != name]
    entry = {"name": name, "source": source[:120]}
    if note:
        entry["note"] = note[:300]
    if name == "Exhaustion":
        entry["level"] = max(1, min(6, int(level or 1)))
    return rest + [entry]


def end(conditions: list[dict] | None, name: str) -> list[dict]:
    return [c for c in conditions or [] if c.get("name") != name]


# ------------------------------------------------------------------ how long it lasts
# (Brett, 2026-10-29, docs/mockups/turn-conditions.html: timed by the turns heard from D&D Beyond's VTT, app/fight.py;
# when one runs out or asks for a save, its player and the DM are reminded; nothing ends by itself.) Kept on askdnd's
# own entry ("lasts"; "began": whose turn it began on, a fighter's key; "left": rounds still to run; "armed": its "next
# turn" has begun; "due": it ran out).

LASTS = ("removed", "endnext", "startnext", "rounds", "time", "save")
ABILITIES = ("Str", "Dex", "Con", "Int", "Wis", "Cha")
TIMES = ("10 minutes", "1 hour", "8 hours", "24 hours")


def lasts_from(kind: str, n: int = 0, time: str = "", ability: str = "", dc: int = 0, whose: str = "",
               whose_name: str = "") -> dict | None:
    """What + Condition's Lasts says, kept as askdnd times it, or None (until it's ended). `whose` is "self" or a
    fighter's key in the heard fight, `whose_name` how that one is named."""
    of = {"self": True} if whose in ("", "self") else {"key": str(whose)[:80], "name": str(whose_name)[:80]}
    if kind in ("endnext", "startnext"):
        return {"kind": kind, "of": of}
    if kind == "rounds" and 1 <= int(n or 0) <= 100:
        return {"kind": "rounds", "n": int(n)}
    if kind == "minute":
        return {"kind": "rounds", "n": 10}
    if kind == "time" and time in TIMES:
        return {"kind": "time", "text": time}
    if kind == "save" and ability in ABILITIES and 1 <= int(dc or 0) <= 30:
        return {"kind": "save", "ability": ability, "dc": int(dc), "of": of}
    return None


def _whose(of: dict | None, mine: bool) -> str:
    if not of or of.get("self"):
        return "your" if mine else "their"
    return f"{of.get('name') or 'their'}’s"


def lasts_short(entry: dict, mine: bool = True, now: bool = False) -> str:
    """The pill's few words ("to your next turn", "Wis 13 save", "9 rounds"); "" when it lasts until it's ended.
    `now`: it ends on the turn running now."""
    la = entry.get("lasts") or {}
    if entry.get("due"):
        return "due to end"
    if la.get("kind") in ("endnext", "startnext"):
        return "ends this turn" if now else f"to {_whose(la.get('of'), mine)} next turn"
    if la.get("kind") == "save":
        return f"{la['ability']} {la['dc']} save"
    if la.get("kind") == "rounds":
        left = rounds_left(entry)
        return f"{la['n']} rounds" if left is None else ("last round" if left <= 1 else f"{left} rounds")
    if la.get("kind") == "time":
        return la["text"]
    return ""


def lasts_long(entry: dict, mine: bool = True) -> str:
    """The whole of it, for the pill's pop-up."""
    la = entry.get("lasts") or {}
    k = la.get("kind")
    if entry.get("due"):
        return "Its time is up. End it, or keep it if the DM says it lasts."
    if k == "endnext":
        return f"Until the end of {_whose(la.get('of'), mine)} next turn."
    if k == "startnext":
        return f"Until the start of {_whose(la.get('of'), mine)} next turn."
    if k == "save":
        return f"Until a {la['ability']} save, DC {la['dc']}, at the end of each of {_whose(la.get('of'), mine)} turns."
    if k == "rounds":
        left = rounds_left(entry)
        return f"{la['n']} rounds" + (f": {left} left, counting this one." if left is not None else ", counted from the next turn askdnd hears.")
    if k == "time":
        return f"{la['text']}: not counted in rounds."
    return "Until it's ended."


def rounds_left(entry: dict) -> int | None:
    """Rounds still to run, counting this one (app/fight.py counts it down each time the turn it began on comes round
    again); None until a heard fight has begun counting it."""
    left = entry.get("left")
    return left if isinstance(left, int) else None
