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


def on_use(it: dict) -> dict | None:
    """What using a consumable starts ({"starts": "Enlarged", "note": "10 minutes…"}), for a Track button."""
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
