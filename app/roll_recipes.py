"""How spells roll: stored, audited recipes (app/data/roll_recipes.json, built and checked by
scripts/roll_audit.py from the 2024 rules text; the audit itself is docs/rules/rolls-audit.md).

A recipe lists events: what gets rolled, and when.

    {"level": 1, "events": [
       {"name": "Shard", "on": "hit", "parts": ["1d10 piercing"]},
       {"name": "Explosion", "on": "save", "save": "Dex", "success": "none", "parts": ["2d6 cold"], "upcast": ["1d6"]}]}

- on: "hit" (a spell attack; the damage on a hit), "save" (targets save; success "half" or "none"),
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


def item(name: str) -> dict | None:
    """The recipe for an item by name ("Potion of Healing (Superior)"), any capitalization."""
    want = (name or "").removeprefix("Use an item: ").strip().lower()
    return next((r for n, r in (recipes().get("items") or {}).items() if n.lower() == want), None)


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
