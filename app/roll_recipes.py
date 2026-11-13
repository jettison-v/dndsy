"""How spells roll: stored, audited recipes (app/data/roll_recipes.json, built and checked by
scripts/roll_audit.py from the 2024 rules text; the audit itself is docs/rules/rolls-audit.md).

A recipe lists events: what gets rolled, and when.

    {"level": 1, "events": [
       {"name": "Shard", "on": "hit", "parts": ["1d10 piercing"]},
       {"name": "Explosion", "on": "save", "save": "Dex", "success": "none", "parts": ["2d6 cold"], "upcast": ["1d6"]}]}

- on: "hit" (a spell attack; the damage on a hit), "save" (targets save; success "half" or "none"), "rider"
  (added to each hit while the spell lasts: Hunter's Mark; never rolled on casting),
  "auto" (no attack or save, e.g. Magic Missile), "heal", "temp" (Temporary Hit Points), "plain"
  (a die that isn't damage, e.g. Blink's d6).
- parts: dice, an optional flat bonus and the damage type ("1d4+1 force"); "mod": true adds the
  caster's spellcasting modifier (only when the spell says so).
- count: separate instances, each rolled on its own (3 darts, 3 rays; each ray its own attack).
- upcast: dice added to each part per slot level above the spell's level ("every": 2 for every two
  levels); count_upcast: instances added per level.
- cantrip: "dice" (dice ×2/×3/×4 at character levels 5/11/17), "count" (more beams) or "extra"
  (none before level 5, then ×1/×2/×3: True Strike).
- repeat: when it's rolled again (e.g. "start of each of its turns"); note: anything else to know.

Why stored: D&D Beyond's and Open5e's structured numbers are wrong for some spells (2014 numbers,
upcasting the wrong part), so askdnd rolls from these and the audit checks them against the text.
"""

import json
import re
from functools import cache
from pathlib import Path

PATH = Path(__file__).parent / "data" / "roll_recipes.json"
PART = re.compile(r"^(?:(\d+)d(\d+)([+-]\d+)?|([+-]?\d+))(?:\s+(.+))?$")  # "2d6+3 fire", or a fixed "1 bludgeoning"
# Spells the SRD names without their wizard ("Melf's Acid Arrow" is "Acid Arrow")
RENAMED = {"Nystul's Magic Aura": "Arcanist's Magic Aura", "Bigby's Hand": "Arcane Hand", "Mordenkainen's Sword": "Arcane Sword"}


@cache
def recipes() -> dict:
    try:
        return json.loads(PATH.read_text())
    except FileNotFoundError:
        return {"spells": {}}


def srd_name(name: str) -> str:
    return RENAMED.get(name) or re.sub(r"^[A-Z][a-z]+(?:'s)\s+", "", name or "")


def spell_key(name: str) -> str | None:
    """The recipe's own name for a spell's D&D Beyond name ("Melf's Acid Arrow" -> "Acid Arrow"), or None."""
    all_ = recipes().get("spells") or {}
    return name if name in all_ else srd_name(name) if srd_name(name) in all_ else None


def spell(name: str) -> dict | None:
    """The audited recipe for a spell by its D&D Beyond name, or None. This is the tool's knowledge; a campaign's
    house rules are applied on top by app/house_rules.py."""
    key = spell_key(name)
    return (recipes().get("spells") or {})[key] if key else None


def feature(name: str) -> dict | None:
    """The recipe for a class feature's roll by its Battle name ("Second Wind"), parts with {tokens} the sheet fills in
    (app/rules_book.py `fill`: {level:Fighter}, {mod:dexterity}, N{martial_arts}, {sneak}, {lands_aid}, {bardic}…). D&D
    Beyond's own names match too: curly apostrophes, and the part after a prefix ("Channel Divinity: Divine Spark")."""
    all_ = recipes().get("features") or {}
    norm = lambda n: re.sub(r"\s+", " ", (n or "").replace("’", "'")).strip().lower()
    keys = {norm(k): k for k in all_}
    want = norm(name)
    hit = keys.get(want) or (keys.get(want.split(": ", 1)[1]) if ": " in want else None)
    return all_.get(hit) if hit else None


def modifier(name: str) -> dict | None:
    """What a feature or spell does to another roll by its name (Bless, Guidance, Sneak Attack, Deflect Attack…), as it
    stands in the rules book (app/rules_book.py), its numbers not yet filled from a sheet: when, what it's for, what it
    adds (`adds`) or reduces."""
    from app import rules_book

    want = rules_book._norm(name)
    a = next((a for e in rules_book.entries() for a in e.get("adds") or []
              if rules_book._norm(a["name"]) == want and a.get("op", "add") == "add" and (a.get("amount") or a.get("reduces"))), None)
    return {("adds" if k == "amount" else "types" if k == "damage_types" else k): v for k, v in a.items() if k != "name"} if a else None


# A rules-book entry's rolls as the engine's events (app/data/rules/<book>.json `rolls` -> roll_recipes.json `events`):
# the one map, used by scripts/roll_audit.py to compile the books and by a campaign's homebrew items (app/homebrew.py)
ON = {("attack", "damage", None): "hit", ("save", "damage", None): "save", ("none", "damage", None): "auto",
      ("none", "heal", None): "heal", ("none", "temp", None): "temp", ("none", "dice", None): "plain", ("none", "damage", "on_hit"): "rider"}


def event(e: dict) -> dict:
    out = {"name": e["name"], "on": ON[(e["resolve"], e["effect"], e.get("when"))], "parts": e["dice"]}
    return out | {k: v for k, v in e.items() if k not in ("name", "resolve", "effect", "when", "dice")}


def item_for(sheet: dict | None, name: str) -> dict | None:
    """An item's recipe for this character: the campaign's homebrew item of that name first (app/homebrew.py, carried
    on the sheet as `_homebrew` by character_views.apply_overrides), then the books' (`item`)."""
    hb = (sheet or {}).get("_homebrew") or {}
    want = " ".join((name or "").removeprefix("Use an item: ").replace("’", "'").lower().split())
    e = hb.get(want) or (hb.get(want.split(" (")[0]) if " (" in want else None)
    if e and e.get("rolls"):
        return {"checked": "homebrew", "level": 0, "events": [event(r) for r in e["rolls"]]}
    return item(name)


def item(name: str) -> dict | None:
    """The recipe for an item by name ("Potion of Healing (Superior)"), any capitalization."""
    want = (name or "").removeprefix("Use an item: ").strip().lower()
    items = recipes().get("items") or {}
    found = next((r for n, r in items.items() if n.lower() == want), None)
    if found is None and " (" in want:  # (a magic weapon named with its base: "Hammer of Thunderbolts (Maul)")
        base = want.split(" (")[0]
        found = next((r for n, r in items.items() if n.lower() == base), None)
    return found


def parse_part(part: str) -> tuple[int, int, int, str] | None:
    """'2d6+3 fire' -> (2, 6, 3, 'fire'); '1 bludgeoning' -> (0, 0, 1, 'bludgeoning')."""
    m = PART.match((part or "").strip())
    if not m:
        return None
    if m.group(4):
        return 0, 0, int(m.group(4)), (m.group(5) or "").strip()
    return int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), (m.group(5) or "").strip()


def _grow(part: str, extra: str, times: int) -> str:
    """Add `times` × extra dice ("1d6") or a flat amount ("+5") to a part with the same die."""
    p = parse_part(part)
    if not p or not extra or times <= 0:
        return part
    if re.fullmatch(r"[+-]\d+", extra):
        count, sides, flat, kind = p
        flat += int(extra) * times
        return f"{count}d{sides}{f'{flat:+d}' if flat else ''}{(' ' + kind) if kind else ''}"
    e = parse_part(extra)
    if not e:
        return part
    count, sides, flat, kind = p
    if e[1] == sides:
        count += e[0] * times
        return f"{count}d{sides}{f'{flat:+d}' if flat else ''}{(' ' + kind) if kind else ''}"
    return part  # different dice: listed separately by the recipe instead


def tier(char_level: int) -> int:
    return 1 + (char_level >= 5) + (char_level >= 11) + (char_level >= 17)


def resolve(recipe: dict, slot: int | None = None, char_level: int = 1) -> list[dict]:
    """The events with concrete parts and counts for a slot level (leveled spells) or a character
    level (cantrips)."""
    level = recipe.get("level") or 0
    out = []
    for ev in recipe.get("events") or []:
        e = {**ev, "parts": list(ev.get("parts") or []), "count": ev.get("count") or 1}
        if level and slot and slot > level:
            times = (slot - level) // (ev.get("every") or 1)
            e["parts"] = [_grow(p, (ev.get("upcast") or [""] * len(e["parts"]))[i] if i < len(ev.get("upcast") or []) else "", times)
                          for i, p in enumerate(e["parts"])]
            e["count"] += (ev.get("count_upcast") or 0) * times
        if not level and ev.get("cantrip"):
            t = tier(char_level)
            if ev["cantrip"] == "count":
                e["count"] = e["count"] * t
            elif ev["cantrip"] == "extra":  # nothing until level 5, then 1, 2, 3 times the dice (True Strike)
                if t == 1:
                    continue
                e["parts"] = [_grow(p, p.split()[0].split("+")[0].split("-")[0], t - 2) for p in e["parts"]]
            else:
                e["parts"] = [_grow(p, p.split()[0].split("+")[0].split("-")[0], t - 1) for p in e["parts"]]
        out.append(e)
    return out
