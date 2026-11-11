"""Read the offline 2024 books (private/books/, Brett's Mac only) into the roll engine's book files, mechanics only
(the Roll Data Review, Nov 10, docs/artifacts/roll-data-review.html).

    uv run python scripts/rules_from_books.py spells     # the PHB's spells beyond the SRD

For each spell in the 2024 Player's Handbook that the SRD doesn't have, the same reader scripts/roll_audit.py uses on
the SRD reads its words; a spell whose every die it accounts for is saved into app/data/rules/phb-2024.json as an entry
"read from the 2024 PHB" (its recipe only: dice, saves, upcasting, never the words). One it can't is listed for a hand
entry. A hand entry already there is never replaced. Then run scripts/roll_audit.py to compile and check.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import roll_recipes as rr  # noqa: E402
from app import rules_data  # noqa: E402

PHB = ROOT / "private" / "books" / "phb-2024" / "spell-descriptions.md"
OUT = ROOT / "app" / "data" / "rules" / "phb-2024.json"
READ = "read from the 2024 PHB"
ON = {"hit": ("attack", "damage", None), "save": ("save", "damage", None), "auto": ("none", "damage", None), "heal": ("none", "heal", None),
      "temp": ("none", "temp", None), "plain": ("none", "dice", None), "rider": ("none", "damage", "on_hit")}


def phb_spells() -> list[dict]:
    """Each spell in the offline PHB: its name, level, words and what a higher slot or level adds."""
    text = PHB.read_text()
    out = []
    heads = list(re.finditer(r"^### (.+)$", text, re.M))
    for i, m in enumerate(heads):
        body = text[m.end():heads[i + 1].start() if i + 1 < len(heads) else None]
        lines = [x.strip() for x in body.strip().split("\n") if x.strip()]
        head = lines[0] if lines else ""
        lv = re.match(r"Level (\d)", head)
        level = int(lv.group(1)) if lv else 0
        rest = [x for x in lines[1:] if not re.match(r"^(Casting Time|Range|Components|Duration):", x)]
        higher = [x for x in rest if x.startswith(("Using a Higher-Level Spell Slot.", "Cantrip Upgrade."))]
        desc = [x for x in rest if x not in higher]
        out.append({"name": m.group(1).replace("’", "'"), "level": level, "desc": "\n".join(desc), "higher_level": "\n".join(higher)})
    return out


def _entry(name: str, recipe: dict) -> dict:
    rolls = []
    for e in recipe["events"]:
        resolve, effect, when = ON[e["on"]]
        r = {"name": e["name"], "resolve": resolve, "effect": effect, **({"when": when} if when else {}), "dice": e["parts"]}
        rolls.append(r | {k: v for k, v in e.items() if k not in ("name", "on", "parts")})
    return {"kind": "spell", "name": name, "level": recipe.get("level") or 0, "checked": READ, "rolls": rolls}


def spells() -> int:
    import roll_audit

    if not PHB.exists():
        print("The offline PHB isn't here (private/books/phb-2024/): nothing to read.")
        return 1
    srd = {s["name"] for s in rules_data.srd("spell")}
    data = json.loads(OUT.read_text())
    hand = {e["name"] for e in data["entries"] if e["kind"] == "spell" and e.get("checked") != READ}
    data["entries"] = [e for e in data["entries"] if not (e["kind"] == "spell" and e.get("checked") == READ)]
    added, none, left = [], [], []
    for s in phb_spells():
        if s["name"] in srd or rr.srd_name(s["name"]) in srd or s["name"] in hand:
            continue
        if not roll_audit.DICE.search(s["desc"] + " " + s["higher_level"]):
            none.append(s["name"])
            continue
        recipe, _, unaccounted = roll_audit.read_spell(s)
        if unaccounted or not recipe["events"]:
            left.append(f"{s['name']}: {', '.join(sorted(set(unaccounted))) or 'no events'}")
            continue
        data["entries"].append(_entry(s["name"], recipe))
        added.append(s["name"])
    data["entries"].sort(key=lambda e: (e["kind"], e["name"], e.get("sub") or ""))
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(added)} read from the PHB; {len(none)} roll nothing; {len(left)} for a hand entry:")
    for x in left:
        print("  ", x)
    return 0


if __name__ == "__main__":
    sys.exit({"spells": spells}[sys.argv[1] if len(sys.argv) > 1 else "spells"]())
