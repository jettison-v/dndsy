"""Conditions a character has right now (Invisible from a Ring of Invisibility…), and the magic-item
actions that start or end them (roadmap step 7, Brett 2026-10-21).

- Character.conditions: [{"name": "Invisible", "source": "Ring of Invisibility"}]. Everyone at the
  table sees them on Battle; only the character's player starts or ends them.
- Item actions: curated in app/data/item_actions.json (our own summaries); otherwise an equipped
  magic item whose text says "take a Magic action" or "as a Bonus Action" gets a plain option.
- Effects on rolls (adv_reasons): offered in the roll window with the reason, never forced: a
  creature that can see you cancels Invisible's Advantage, and the DM makes the ruling.
"""

import json
import re
from functools import cache
from pathlib import Path

from app import rules_terms

DATA = Path(__file__).parent / "data" / "item_actions.json"
KNOWN = ("Invisible",)  # conditions askdnd can track today

# What each condition does to your own rolls (our summaries of the 2024 Rules Glossary)
EFFECTS = {
    "Invisible": {"attack": "Advantage on your attack rolls, unless the target can see you",
                  "initiative": "Advantage on Initiative"},
}
MAGIC_ACTION = re.compile(r"\btake a Magic action\b", re.I)
BONUS_ACTION = re.compile(r"\bas a Bonus Action\b|\btake a Bonus Action\b", re.I)


@cache
def _curated() -> dict:
    return {k: v for k, v in json.loads(DATA.read_text()).items() if not k.startswith("_")}


def rules_text(name: str) -> str:
    """The condition's short rules summary (rules_terms), for the pill's pop-up."""
    return next((t.text for t in rules_terms.TERMS if t.name == name), "")


def usable(it: dict) -> bool:
    """An item whose powers work now: equipped (or attuned), and attuned if it needs attunement."""
    return bool(it.get("magic")) and (it.get("equipped") or it.get("attunement") == "attuned") and it.get("attunement") != "required"


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def item_actions(it: dict) -> list[dict]:
    """The Battle options one item gives: curated actions, else a plain one read from its text."""
    if not usable(it):
        return []
    curated = _curated().get(it.get("base_name") or it["name"]) or _curated().get(it["name"])
    if curated:
        return [{**a, "key": f"{it['key']}#{_slug(a['name'])}", "item": it["name"]} for a in curated]
    text = f"{it.get('summary') or ''} {it.get('text') or ''}"
    cost = "Action" if MAGIC_ACTION.search(text) else "Bonus action" if BONUS_ACTION.search(text) else None
    if not cost or it.get("battle"):  # "Use an item: …" already covers potions, scrolls and charged items
        return []
    return [{"cost": cost, "name": f"Use: {it['name']}", "meta": ("Magic action" if cost == "Action" else "Bonus Action") + f" · {it['name']}",
             "text": it.get("summary") or "", "key": f"{it['key']}#use", "item": it["name"]}]


def adv_reasons(conditions: list[dict] | None) -> dict:
    """{"attack": ["Invisible (Ring of Invisibility): Advantage…"], "initiative": [...]}, for the roll window."""
    out: dict[str, list[str]] = {}
    for c in conditions or []:
        for roll, effect in EFFECTS.get(c.get("name"), {}).items():
            out.setdefault(roll, []).append(f"{c['name']}" + (f" ({c['source']})" if c.get("source") else "") + f": {effect}")
    return out


def add(conditions: list[dict] | None, name: str, source: str = "") -> list[dict]:
    if name not in KNOWN:
        raise ValueError("unknown condition")
    rest = [c for c in conditions or [] if c.get("name") != name]
    return rest + [{"name": name, "source": source[:120]}]


def end(conditions: list[dict] | None, name: str) -> list[dict]:
    return [c for c in conditions or [] if c.get("name") != name]
