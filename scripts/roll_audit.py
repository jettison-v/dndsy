"""Audit how askdnd rolls things, and store the result (app/data/roll_recipes.json).

Sources (openly licensed, CC-BY-4.0): every spell and magic item in the System Reference Document 5.2
(fetched from Open5e into private/srd/, which isn't committed) and the Beasts in app/data/beasts_2024.json.

For each spell, the rules text is read sentence by sentence: every dice expression must end up in the
recipe (damage, healing, Temporary Hit Points, upcasting, cantrip growth) or be marked as not a roll you
make (durations, a target's bonus die such as Bless, numbers on a table). Recipes the reader can't get
right on its own are written by hand in scripts/roll_overrides.json, each with the reason; those are
checked against the same text. The report, docs/rules/rolls-audit.md, lists every spell, Beast attack
and item with its recipe and how it was checked.

    uv run python scripts/roll_audit.py           # rebuild from the cache
    uv run python scripts/roll_audit.py --fetch   # refresh the cache from Open5e first
    uv run python scripts/roll_audit.py --campaign   # also list the table's own spells (local database)

Exits 1 when a dice expression isn't accounted for, so a change to the rules data can't slip through.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import roll_recipes as rr  # noqa: E402

CACHE = ROOT / "private" / "srd"
OUT = ROOT / "app" / "data" / "roll_recipes.json"
OVERRIDES = ROOT / "scripts" / "roll_overrides.json"
REPORT = ROOT / "docs" / "rules" / "rolls-audit.md"
CREDIT = ("Roll recipes for spells in the System Reference Document 5.2 by Wizards of the Coast LLC, licensed under "
          "CC-BY-4.0 (https://creativecommons.org/licenses/by/4.0/), written by askdnd from the rules text.")

TYPES = "Acid|Bludgeoning|Cold|Fire|Force|Lightning|Necrotic|Piercing|Poison|Psychic|Radiant|Slashing|Thunder"
DICE = re.compile(r"(\d+)d(\d+)(?:\s*([+−-])\s*(\d+)(?!\s*d))?")
DAMAGE = re.compile(rf"(\d+d\d+)(?:\s*\+\s*(\d+)(?!d))?\s+((?:(?:{TYPES}),?\s+(?:or\s+)?)*(?:{TYPES}))\s+damage", re.I)
DAMAGE_ANY = re.compile(r"(\d+d\d+)(?:\s*\+\s*(\d+)(?!d))?\s+damage(?: of (?:the|a) type)?", re.I)
HEAL = re.compile(r"(?:regains?|restores?)\s+(?:(?:a number of\s+)?Hit Points equal to\s+)?(\d+d\d+)(?:\s*\+\s*(\d+))?(?:\s+Hit Points)?(\s+plus your spellcasting ability modifier)?", re.I)
TEMP = re.compile(r"(\d+d\d+)(?:\s*\+\s*(\d+))?\s+Temporary Hit Points|Temporary Hit Points equal to\s+(\d+d\d+)(?:\s*\+\s*(\d+))?", re.I)
UPCAST = re.compile(r"(?:The|Its|the)\s+([\w\s,()]*?)(damage|healing|Temporary Hit Points)[\w\s,()]*? increases? by (\d+d\d+) for (each|every two) (?:spell )?slot levels? above (\d)", re.I)
MORE = re.compile(r"(?:one (?:more|additional) (dart|ray|beam|bolt|creature|target)|an additional (dart|ray|beam))[^.]*?for each (?:spell )?slot level above (\d)", re.I)
CANTRIP = re.compile(r"increases? by (\d+d\d+) when you reach levels? 5", re.I)
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
SAVES = {"Strength": "Str", "Dexterity": "Dex", "Constitution": "Con", "Intelligence": "Int", "Wisdom": "Wis", "Charisma": "Cha"}
# Dice in the text that aren't a roll the caster makes for damage or healing (a target's bonus die, a duration…)
NOT_ROLLS = [
    (re.compile(r"(?:add|adds|subtract|subtracts|roll)\s+(?:a\s+)?(\d+d\d+)\s+(?:and add the number rolled\s+)?(?:to|from)", re.I), "a die the target adds to or takes from its own roll"),
    (re.compile(r"(\d+d\d+)\s+(?:hours|minutes|days|rounds|miles)|\d+d\d+\s*×\s*\d+", re.I), "a duration or distance"),
    (re.compile(r"\(\d+d\d+\)"), "the cantrip's damage at a higher level, as listed"),
]


def fetch() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for kind in ("spells", "items"):
        url, out = f"https://api.open5e.com/v2/{kind}/?document__key=srd-2024&limit=100", []
        while url:
            d = json.loads(subprocess.run(["curl", "-s", "-m", "60", url], capture_output=True, text=True, check=True).stdout)
            out += d["results"]
            url = d["next"]
        (CACHE / f"{kind}.json").write_text(json.dumps(out))
        print(f"fetched {len(out)} {kind}")


def sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+(?=[A-Z])|\n+", text or "") if s.strip()]


def _part(dice: str, flat: str | None, kind: str) -> str:
    kind = re.sub(r",?\s+or\s+", " or ", kind.strip().lower()).replace(", ", " or ")
    return f"{dice}{('+' + flat) if flat else ''}{(' ' + kind) if kind else ''}"


def read_spell(s: dict) -> tuple[dict, list[str], list[str]]:
    """(recipe, used dice, unaccounted dice) for one SRD spell, read from its text."""
    desc, higher = s.get("desc") or "", s.get("higher_level") or ""
    level = s.get("level") or 0
    events, used, notes = [], [], []
    sents = sentences(desc)
    for i, sent in enumerate(sents):
        found = [(m.group(1), m.group(2), m.group(3)) for m in DAMAGE.finditer(sent)]
        found += [(m.group(1), m.group(2), "") for m in DAMAGE_ANY.finditer(sent) if not any(m.group(1) == f[0] for f in found)]
        heal, temp = HEAL.search(sent), TEMP.search(sent)
        if heal:
            events.append({"name": "Healing", "on": "heal", "parts": [_part(heal.group(1), heal.group(2), "")], **({"mod": True} if heal.group(3) else {})})
            used.append(heal.group(1))
        if temp:
            d, f = temp.group(1) or temp.group(3), temp.group(2) or temp.group(4)
            events.append({"name": "Temporary Hit Points", "on": "temp", "parts": [_part(d, f, "")]})
            used.append(d)
        if not found:
            continue
        before = " ".join(sents[max(0, i - 2):i + 1])
        ev = {"name": s["name"] if not events else f"{s['name']} ({len(events) + 1})", "parts": [_part(*f) for f in found]}
        used += [f[0] for f in found]
        if re.search(r"spell attack", before, re.I) and not re.search(r"saving throw", sent, re.I):
            ev["on"] = "hit"
        elif re.search(r"saving throw", before, re.I):
            ev["on"] = "save"
            ab = re.findall(r"(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) saving throw", before)
            if ab:
                ev["save"] = SAVES[ab[-1]]
            after = " ".join(sents[i:i + 2])
            ev["success"] = "half" if re.search(r"half as much damage|Half damage", after, re.I) else "none"
        else:
            ev["on"] = "auto"
        rep = re.search(r"(start|end) of each of (?:its|their|your) turns|each of your (?:later |subsequent )?turns|enters? (?:the|that)", sent, re.I)
        if rep:
            ev["repeat"] = rep.group(0)
        num = re.search(r"\b(one|two|three|four|five|six)\s+(?:\w+\s+){0,2}?(darts|rays|beams)\b", desc, re.I)
        if num:
            ev["count"], ev["count_label"] = WORDS[num.group(1).lower()], num.group(2).lower().rstrip("s")
        events.append(ev)
    if len(events) > 1:  # name them by what happens: "On a hit", "Dex save", "Damage"
        seen = {}
        for e in events:
            if e["on"] in ("heal", "temp"):
                continue
            n = {"hit": "On a hit", "save": f"{e.get('save', '')} save".strip(), "auto": "Damage"}.get(e["on"], e["name"])
            seen[n] = seen.get(n, 0) + 1
            e["name"] = n if seen[n] == 1 else f"{n} (later)"
    # upcasting and cantrip growth
    for m in UPCAST.finditer(higher):
        which, what, dice, step = m.group(1).strip().lower(), m.group(2).lower(), m.group(3), m.group(4)
        used.append(dice)
        targets = [e for e in events if (what == "healing") == (e["on"] == "heal") and (what != "temporary hit points" or e["on"] == "temp")]
        named = [e for e in targets if which and any(which.split()[0] in p for p in e["parts"])]
        for e in named or targets:
            e["upcast"] = [dice if (not named or which.split()[0] in p) else "" for p in e["parts"]]
            if step.lower() == "every two":
                e["every"] = 2
        if not targets:
            notes.append(f"upcast with nothing to apply to: {m.group(0)}")
    for m in MORE.finditer(higher):
        for e in events:
            if e.get("count"):
                e["count_upcast"] = 1
    c = CANTRIP.search(higher) or CANTRIP.search(desc)
    if c and not level:
        used.append(c.group(1))
        for e in events:
            e["cantrip"] = "dice"
    if not level and re.search(r"creates? (?:two|three|four) beams", higher + desc, re.I):
        for e in events:
            e["cantrip"] = "count"
    # every dice expression in the text must be accounted for
    left = []
    text = desc + "\n" + higher
    for m in DICE.finditer(text):
        dice = f"{m.group(1)}d{m.group(2)}"
        span = text[max(0, m.start() - 40):m.end() + 30]
        if dice in used or any(rx.search(span) for rx, _ in NOT_ROLLS):
            continue
        left.append(dice)
    return {"level": level, "events": events, **({"notes": notes} if notes else {})}, used, left


def dice_in(text: str | None) -> set[str]:
    return {f"{m.group(1)}d{m.group(2)}" for m in DICE.finditer(text or "")}


def recipe_dice(recipe: dict) -> list[str]:
    out = []
    for e in recipe.get("events") or []:
        for p in list(e.get("parts") or []) + list(e.get("upcast") or []):
            m = DICE.search(p or "")
            if m:
                out.append(f"{m.group(1)}d{m.group(2)}")
    return out


PHB = ROOT / "private" / "books" / "phb-2024" / "spell-descriptions.md"


def phb_text(name: str) -> str | None:
    """The spell's text in Brett's offline 2024 Player's Handbook (only on his Mac; never committed)."""
    if not PHB.exists():
        return None
    book = PHB.read_text()
    for m in re.finditer(r"^### (.+)$", book, re.M):
        title = m.group(1).replace("’", "'")
        if title == name or rr.srd_name(title) == name:
            end = book.find("\n### ", m.end())
            return book[m.end():end if end > 0 else None]
    return None


def build() -> int:
    spells = json.loads((CACHE / "spells.json").read_text())
    hand = json.loads(OVERRIDES.read_text()) if OVERRIDES.exists() else {}
    overrides = hand.get("spells") or {}
    out, report, problems = {}, [], 0
    for s in sorted(spells, key=lambda s: s["name"]):
        text = (s.get("desc") or "") + " " + (s.get("higher_level") or "")
        if not DICE.search(text):
            continue
        recipe, used, left = read_spell(s)
        o = overrides.get(s["name"])
        phb = phb_text(s["name"])
        if o:
            recipe = {"level": s.get("level") or 0, **{k: v for k, v in o.items() if k != "why"}}
            how, left = f"by hand: {o['why']}", [d for d in recipe_dice(recipe) if d not in dice_in(text) | dice_in(phb)]
        else:
            how = "read from the text"
        if phb is not None:
            ours, theirs = dice_in(text), dice_in(phb)
            how += "; same dice as the 2024 PHB" if ours == theirs else f"; the PHB also has {', '.join(sorted(theirs - ours)) or '-'} (Open5e: {', '.join(sorted(ours - theirs)) or '-'})"
        if left:
            problems += 1
            how = f"**check: dice not accounted for: {', '.join(sorted(set(left)))}**"
        if recipe["events"] or o:
            out[s["name"]] = {**recipe, "checked": "by hand" if o else "text"}
        report.append((s["name"], s.get("level") or 0, recipe, how))
    # spells in the 2024 Player's Handbook but not the SRD that the table uses: by hand, checked against the book
    phb_rows = []
    for name, o in sorted((hand.get("phb_spells") or {}).items()):
        recipe = {k: v for k, v in o.items() if k != "why"}
        phb = phb_text(name)
        missing = [d for d in recipe_dice(recipe) if phb is not None and d not in dice_in(phb)]
        problems += bool(missing)
        out[name] = {**recipe, "checked": "by hand (PHB)"}
        phb_rows.append((name, recipe.get("level") or 0, recipe, f"by hand: {o['why']}" + (f"; **not in the PHB text: {missing}**" if missing else "")))
    items = {}
    for name, o in sorted((hand.get("items") or {}).items()):
        items[name] = {"level": 0, **{k: v for k, v in o.items() if k != "why"}, "checked": "by hand"}
    beasts = beast_rows()
    problems += sum(1 for r in beasts if r[3].startswith("**"))
    OUT.write_text(json.dumps({"credit": CREDIT, "spells": out, "items": items}, indent=1, sort_keys=True) + "\n")
    write_report(report, phb_rows, [(n, 0, {k: v for k, v in o.items() if k != "why"}, o["why"]) for n, o in sorted((hand.get("items") or {}).items())],
                 beasts, campaign_rows(out) if "--campaign" in sys.argv else None)
    print(f"{len(out)} spell recipes, {len(items)} items, {len(beasts)} Beast actions; {problems} to check")
    return 1 if problems else 0


def beast_rows() -> list[tuple]:
    """Every Beast action with dice: its recipe, and whether every dice expression is in it."""
    from app import wild_shape as ws

    rows = []
    for b in json.loads((ROOT / "app" / "data" / "beasts_2024.json").read_text())["beasts"]:
        for k in ("actions", "bonus_actions", "reactions"):
            for e in b.get(k) or []:
                dice = dice_in(e["text"])
                if not dice:
                    continue
                recipe = ws.beast_recipe(e) or {"events": []}
                left = dice - set(recipe_dice(recipe))
                how = f"**check: dice not accounted for: {', '.join(sorted(left))}**" if left else "read from the stat block"
                rows.append((f"{b['name']}: {e['name']}", 0, recipe, how))
    return rows


def campaign_rows(audited: dict) -> list[tuple]:
    """The table's own spells (from the local database): which recipe askdnd uses, and where D&D
    Beyond's numbers differ from the audited ones."""
    from app import characters as chars
    from app.db import SessionLocal
    from app.models import Character

    seen, rows = {}, []
    with SessionLocal() as db:
        for ch in db.query(Character).all():
            s = chars.character_summary(ch)
            for sp in (s or {}).get("spells") or []:
                seen.setdefault(sp["name"], sp)
    for name, sp in sorted(seen.items()):
        mine = rr.spell(name)
        ddb = sp.get("roll")
        if mine:
            same = ddb and [e["parts"] for e in ddb["events"]] == [e["parts"] for e in mine["events"]]
            how = f"audited ({mine['checked']})" + ("" if not ddb or same else f"; D&D Beyond differs: {describe(ddb)}")
        elif ddb:
            how = "D&D Beyond's numbers, not checked against a book"
        else:
            how = "no damage or healing roll"
        rows.append((name, sp.get("level") or 0, mine or ddb or {}, how))
    return rows


def describe(recipe: dict) -> str:
    bits = []
    for e in recipe.get("events") or []:
        on = {"hit": "on a hit", "save": f"{e.get('save', '')} save, {'half' if e.get('success') == 'half' else 'nothing'} on a success",
              "auto": "no roll to hit", "heal": "healing", "temp": "Temporary Hit Points"}.get(e["on"], e["on"])
        count = f"{e['count']} {e.get('count_label', '')}s × " if e.get("count", 1) > 1 else ""
        parts = " + ".join(e["parts"]) + (" + spellcasting modifier" if e.get("mod") else "")
        up = []
        if e.get("upcast") and any(e["upcast"]):
            up.append(f"+{' / '.join(x for x in e['upcast'] if x)} per slot level{' (every two)' if e.get('every') == 2 else ''}")
        if e.get("count_upcast"):
            up.append(f"+{e['count_upcast']} {e.get('count_label', '')} per slot level")
        if e.get("cantrip"):
            up.append("more beams at levels 5, 11, 17" if e["cantrip"] == "count" else "dice ×2/×3/×4 at levels 5, 11, 17")
        rep = f"; again at the {e['repeat']}" if e.get("repeat") else ""
        bits.append(f"{e.get('name', '')}: {count}{parts} ({on}{rep}){'; ' + '; '.join(up) if up else ''}")
    return " · ".join(bits) or "no damage or healing roll"


def write_report(rows, phb_rows=(), item_rows=(), beast_rows_=(), campaign=None) -> None:
    lines = ["# Roll audit", "",
             "How askdnd rolls each SRD 5.2 spell that has dice, generated by `scripts/roll_audit.py` from the 2024 rules",
             "text (Open5e's copy of the SRD, CC-BY-4.0). \"read from the text\": every dice expression in the description",
             "is used by the recipe or is not a roll you make (a target's bonus die, a duration). \"by hand\": written in",
             "`scripts/roll_overrides.json` because the text needs judgment; the reason is given. Don't edit this file: run",
             "the script.", "", "| Spell | Level | How it rolls | Checked |", "|---|---|---|---|"]
    for name, level, recipe, how in rows:
        lines.append(f"| {name} | {level or 'cantrip'} | {describe(recipe)} | {how} |")
    lines += ["", "## Player's Handbook spells (not in the SRD)", "",
              "Spells the table uses that the SRD doesn't have, written by hand from the 2024 Player's Handbook (our own short",
              "recipes; no book text). Their dice are checked against the offline copy when it's on this computer.", "",
              "| Spell | Level | How it rolls | Checked |", "|---|---|---|---|"]
    lines += [f"| {n} | {lv or 'cantrip'} | {describe(r)} | {h} |" for n, lv, r, h in phb_rows]
    lines += ["", "## Items", "", "| Item | How it rolls | From |", "|---|---|---|"]
    lines += [f"| {n} | {describe(r)} | {h} |" for n, _, r, h in item_rows]
    lines += ["", "## Beast actions (Wild Shape)", "",
              "Every Beast action with dice in `app/data/beasts_2024.json`, as askdnd rolls it in a form (`wild_shape.beast_recipe`).",
              "Alternatives (\"or … if the swarm is Bloodied\") and conditional extras (\"if it moved 20+ feet straight toward it\")",
              "are separate choices, never added to every hit.", "", "| Action | How it rolls | Checked |", "|---|---|---|"]
    lines += [f"| {n} | {describe(r)} | {h} |" for n, _, r, h in beast_rows_]
    if campaign is not None:
        lines += ["", "## The table's spells", "",
                  "Every spell on the table's characters (from D&D Beyond), with the recipe askdnd uses. \"D&D Beyond differs\" shows",
                  "D&D Beyond's own numbers where they don't match the audit (askdnd uses the audited recipe).", "",
                  "| Spell | Level | How it rolls | Recipe |", "|---|---|---|---|"]
        lines += [f"| {n} | {lv or 'cantrip'} | {describe(r)} | {h} |" for n, lv, r, h in campaign]
    REPORT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    if "--fetch" in sys.argv:
        fetch()
    sys.exit(build())
