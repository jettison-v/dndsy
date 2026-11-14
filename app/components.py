"""Spell components (Brett, Nov 8; he chose A, B, C and D on Nov 13, docs/mockups/spell-components/): whether a character
carries what a spell's Material component needs, said where a spell is chosen and cast, never stopping a cast (the DM
rules).

By the 2024 rules a Component Pouch or a Spellcasting Focus covers a Material component without a cost, so what matters
is a component with a cost (Revivify's diamond worth 300+ GP), or any Material component when you have neither. What
the character carries is matched by name (a significant word of the component, "diamond", in an item's name) and worth
(D&D Beyond's cost for it, times how many). A table can play it more simply (D, Manage › House rules › Spells):
"costly only" never marks a component without a cost, pouch or not.

`need(spell, sheet, rules)` answers one spell: None (nothing to say), or {"kind": "missing" | "unsure" | "consumes",
"says": words, "item": the item's key when one is carried}. Players' and the DM's pages show it alike, as everything
else about a spell.
"""

import re

COSTLY_ONLY = "costly_only"  # the house rule's field (HouseRule target "table" / "components")
USE_UP = "use_up"  # (C, used up when cast: its own switch, off until the table turns it on)
RULES = ("table", "components")

WORTH = re.compile(r"worth\s+(?:at\s+least\s+)?([\d,]+)\s*\+?\s*(gp|sp|cp)\b", re.I)
CONSUMED = re.compile(r"\bconsume", re.I)
FOCUS_WORDS = ("component pouch", "focus", "holy symbol", "totem", "sprig of mistletoe", "yew wand", "wooden staff",
               "amulet", "emblem", "reliquary", "crystal", "orb", "rod", "staff", "wand")
SKIP = {"a", "an", "the", "of", "and", "or", "other", "worth", "least", "which", "spell", "consumes", "some", "piece",
        "bit", "specially", "marked", "burning", "small", "tiny", "each", "with", "that"}
COIN = {"gp": 1.0, "sp": 0.1, "cp": 0.01}


def material(text: str) -> dict:
    """What a Material component's words say: its cost in GP (None without one), whether the spell consumes it, and its
    significant words, singular, to match an item's name."""
    m = WORTH.search(text or "")
    cost = float(m.group(1).replace(",", "")) * COIN[m.group(2).lower()] if m else None
    head = (text or "")[: m.start()] if m else (text or "")
    words = {w.rstrip("s") for w in re.findall(r"[a-z]+", head.lower()) if len(w) > 3 and w not in SKIP}
    return {"cost": cost, "consumed": bool(CONSUMED.search(text or "")), "words": words, "text": (text or "").strip()}


def _words(name: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z]+", (name or "").lower())}


def covered(sheet: dict) -> str:
    """The item that covers a component without a cost (a Component Pouch or a Spellcasting Focus), else ""."""
    for i in sheet.get("inventory") or []:
        text = f"{i.get('name') or ''} {i.get('type') or ''}".lower()
        if "component pouch" in text or "focus" in text or (i.get("type") or "").lower() in ("rod", "staff", "wand"):
            return i.get("name") or ""
        if any(w in text for w in FOCUS_WORDS[2:7]):
            return i.get("name") or ""
    return ""


def carried(sheet: dict, words: set[str]) -> list[dict]:
    """The items whose names share a significant word with the component."""
    return [i for i in sheet.get("inventory") or [] if words & _words(i.get("name") or "")]


def need(spell: dict, sheet: dict, rules: dict | None = None) -> dict | None:
    """What this character lacks or uses up for the spell's Material component (see the module's words)."""
    if "M" not in (spell.get("components") or []) and not spell.get("material"):
        return None
    rules = rules or {}
    m = material(spell.get("material") or "")
    if m["cost"] is None:
        if rules.get(COSTLY_ONLY) or covered(sheet):
            return None
        return {"kind": "missing", "says": f"needs {m['text'] or 'its Material component'} (no Component Pouch or focus)"}
    have = carried(sheet, m["words"])
    worth = sum((i.get("cost") or 0) * (i.get("count") or i.get("quantity") or 1) for i in have)
    needs = f"{m['text'].split(',')[0]}" if m["text"] else "its Material component"
    if have and worth >= m["cost"]:
        if m["consumed"]:
            return {"kind": "consumes", "says": f"uses {have[0]['name']} (consumed)", "item": have[0].get("key")}
        return None
    if have and not worth:
        return {"kind": "unsure", "says": f"needs {needs}; you carry {have[0]['name']}, its worth isn't on D&D Beyond",
                "item": have[0].get("key")}
    carry = f"; you carry {have[0]['name']} worth {worth:g} GP" if have else ""
    return {"kind": "missing", "says": f"needs {needs}{carry}"}


def rules_for(campaign_id: int | None = None) -> dict:
    """The table's components house rule (D): {"costly_only": bool, "use_up": bool}."""
    from app import house_rules

    kept = house_rules.rules(campaign_id).get(RULES) or {}
    return {k: (kept.get(k) or {}).get("value") == "1" for k in (COSTLY_ONLY, USE_UP)}
