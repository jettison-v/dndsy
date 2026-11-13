"""Audit how askdnd rolls things, and store the result (app/data/roll_recipes.json).

Sources (openly licensed, CC-BY-4.0): every spell and Beast in the System Reference Document 5.2.1, as
app/rules_data.py reads it (app/data/srd/).

For each spell, the rules text is read sentence by sentence: every dice expression must end up in the
recipe (damage, healing, Temporary Hit Points, upcasting, cantrip growth) or be marked as not a roll you
make (durations, a target's bonus die such as Bless, numbers on a table). Everything written by hand is in
app/data/rules/<book>.json, one file per book (the Roll Data Review, Nov 10: docs/artifacts/roll-data-review.html):
each entry a spell, feature, item or the like, with what it rolls when used (`rolls`), what it adds to another roll
(`adds`) and what using an item rolls (`use`), in askdnd's own words, never book text. Those are checked against the
same text and compiled here into app/data/roll_recipes.json, the one file the app reads. The report, docs/rules/rolls-audit.md, lists every spell, Beast attack
and item with its recipe and how it was checked.

    uv run python scripts/roll_audit.py              # rebuild
    uv run python scripts/roll_audit.py --campaign   # also list the table's own spells (local database)

Exits 1 when a dice expression isn't accounted for, so a change to the rules data can't slip through.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import roll_recipes as rr  # noqa: E402
from app import rules_data  # noqa: E402

OUT = ROOT / "app" / "data" / "roll_recipes.json"
# Extra damage added to each hit while the spell lasts, not damage dealt when it's cast (feedback 48, Nov 7: Hunter's Mark
# rolled its 1d6 on casting). The 2024 smites ("As you hit the target") are cast on the hit, so they stay "auto".
RIDER = re.compile(r"\bextra\b[^.]*\b(?:whenever you hit|on a hit|when (?:it|you) hits?)\b|\b(?:whenever you hit|on a hit)\b[^.]*\bextra\b", re.I)
BOOKS = ROOT / "app" / "data" / "rules"
# An entry's `rolls` say how each resolves and what it does; the compiled recipe keeps one word for both (`on`)
from app.roll_recipes import ON, event as _event  # noqa: E402,F401 (the one map, shared with homebrew items)


def _recipe(e: dict) -> dict:
    """An entry as the compiled recipe it was before the book files: events, its `on_hit` and the rest as they are."""
    out = {k: v for k, v in e.items() if k not in ("kind", "name", "rolls", "after_hit", "adds", "book")}
    if "rolls" in e:
        out["events"] = [_event(x) for x in e["rolls"]]
    if "after_hit" in e:  # (cast right after a hit: its words; app/rules_book.py reads what it goes with)
        out["on_hit"] = e["after_hit"]["says"] if isinstance(e["after_hit"], dict) else e["after_hit"]
    return out


def from_books() -> dict:
    """The book files (app/data/rules/*.json) as the hand-written recipes the build reads, by kind and book."""
    hand = {"spells": {}, "phb_spells": {}, "other_spells": {}, "items": {}, "features": {}, "modifiers": {}}
    for f in sorted(BOOKS.glob("*.json")):
        data = json.loads(f.read_text())
        for e in data["entries"]:
            if e["kind"] == "spell" and ("rolls" in e or "after_hit" in e or e.get("why")):
                where = {"srd-5.2.1": "spells", "phb-2024": "phb_spells"}.get(data["book"], "other_spells")
                hand[where][e["name"]] = {"events": [], **_recipe(e)} | ({"book": e["book"]} if where == "other_spells" else {})
            elif e["kind"] == "item" and ({"rolls", "use", "self"} & set(e)):
                hand["items"][e["name"]] = _recipe(e)
            elif e["kind"] in ("feature", "feat", "species") and "rolls" in e:  # (a feat's or species trait's roll is played as a feature's)
                hand["features"][e["name"]] = _recipe(e)
    return hand
REPORT = ROOT / "docs" / "rules" / "rolls-audit.md"
CREDIT = "Roll recipes for spells in the SRD 5.2.1 (attribution in app/data/srd/README.md), written by askdnd from the rules text."

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
        elif RIDER.search(sent):
            ev["on"] = "rider"  # extra damage on each hit while it lasts (Hunter's Mark, Hex): never rolled on casting
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
            n = {"hit": "On a hit", "save": f"{e.get('save', '')} save".strip(), "auto": "Damage", "rider": "Each hit"}.get(e["on"], e["name"])
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


def sheet_text(name: str) -> str | None:
    """A spell's own words as D&D Beyond gives them on the party's saved sheets (for spells outside the SRD and PHB)."""
    import fixtures  # (the saved sheets are locked: unlocked on first use)

    fixtures.ready()
    from app import ddb

    for f in sorted((ROOT / "tests" / "fixtures" / "ddb").glob("*.json")):
        try:
            sheet = ddb.parse_character(ddb.sanitize(json.loads(f.read_text())["data"]))
        except (KeyError, ValueError, TypeError, AttributeError, ddb.DdbError):  # (items.json is a list of items, not a sheet)
            continue
        for sp in sheet.get("spells") or []:
            if sp["name"] == name:
                return sp.get("text") or ""
    return None


def cantrip_dice(recipe: dict) -> set[str]:
    """The larger dice a cantrip's parts grow to at levels 5, 11 and 17."""
    out = set()
    for e in recipe.get("events") or []:
        times = {"dice": (2, 3, 4), "extra": (1, 2, 3)}.get(e.get("cantrip"), ())
        for p in e.get("parts") or []:
            m = DICE.search(p or "")
            if m:
                out |= {f"{int(m.group(1)) * k}d{m.group(2)}" for k in times}
    return out


def recipe_dice(recipe: dict) -> list[str]:
    out = []
    for e in recipe.get("events") or []:
        for p in list(e.get("parts") or []) + list(e.get("upcast") or []) + list(e.get("alt") or []):
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
    data, report, phb_rows, hand, beasts, problems = compile_all()
    OUT.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    write_report(report, phb_rows, [(n, 0, {k: v for k, v in o.items() if k != "why"}, o["why"]) for n, o in sorted((hand.get("items") or {}).items())],
                 beasts, campaign_rows(data["spells"]) if "--campaign" in sys.argv else None)
    print(f"{len(data['spells'])} spell recipes, {len(data['items'])} items, {len(beasts)} Beast actions; {problems} to check")
    return 1 if problems else 0


def compiled() -> dict:
    """app/data/roll_recipes.json as the book files make it now (tests/test_rules_books.py: the stored file is this)."""
    return compile_all()[0]


def compile_all() -> tuple:
    # the text the reader reads: the description and what a higher slot or level adds
    spells = [{"name": s["name"], "level": s["level"], "desc": s["text"], "higher_level": s["higher_levels"] or s["cantrip_upgrade"]}
              for s in rules_data.srd("spell")]
    hand = from_books()
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
            how += "; same dice as the 2024 PHB" if ours == theirs else f"; the PHB also has {', '.join(sorted(theirs - ours)) or '-'} (the SRD: {', '.join(sorted(ours - theirs)) or '-'})"
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
        read = o.get("checked") == "read from the 2024 PHB"  # (scripts/rules_from_books.py: read like the SRD's, not by hand)
        out[name] = {**recipe, "checked": "read from the 2024 PHB" if read else "by hand (PHB)"}
        phb_rows.append((name, recipe.get("level") or 0, recipe, ("read from the 2024 PHB" if read else f"by hand: {o.get('why', '')}")
                         + (f"; **not in the PHB text: {missing}**" if missing else "")))
    # spells from other books that the table's sheets have (Xanathar's, Tasha's, the 2014 PHB…): by hand, checked
    # against the spell's own words on the party's saved sheets (tests/fixtures/ddb)
    for name, o in sorted((hand.get("other_spells") or {}).items()):
        recipe = {k: v for k, v in o.items() if k not in ("why", "book")}
        own = sheet_text(name)
        missing = [d for d in recipe_dice(recipe) if own is not None and d not in dice_in(own)]
        unrolled = sorted(dice_in(own) - set(recipe_dice(recipe)) - cantrip_dice(recipe)) if own else []
        problems += bool(missing or unrolled or own is None)
        out[name] = {**recipe, "checked": f"by hand ({o.get('book') or 'its own text'})"}
        phb_rows.append((name, recipe.get("level") or 0, recipe, f"by hand ({o.get('book')}): {o['why']}"
                         + (f"; **not in its text: {missing}**" if missing else "") + (f"; **its text also has {unrolled}**" if unrolled else "")
                         + ("; **not on a saved sheet to check against**" if own is None else "")))
    items = {}
    for name, o in sorted((hand.get("items") or {}).items()):
        items[name] = {"level": 0, **{k: v for k, v in o.items() if k != "why"}, "checked": "by hand"}
    beasts = beast_rows()
    problems += sum(1 for r in beasts if r[3].startswith("**"))
    features = {n: {**{k: v for k, v in f.items() if k != "why"}, "checked": "by hand"} for n, f in (hand.get("features") or {}).items()}
    # (what a spell or feature does to another roll, its `adds`, is read from the book files themselves: app/rules_book.py)
    return {"credit": CREDIT, "spells": out, "items": items, "features": features}, report, phb_rows, hand, beasts, problems


def beast_rows() -> list[tuple]:
    """Every Beast action with dice: its recipe, and whether every dice expression is in it."""
    from app import wild_shape as ws

    rows = []
    for b in ws._catalog():
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
              "auto": "no roll to hit", "rider": "added to each hit while it lasts", "heal": "healing",
              "temp": "Temporary Hit Points"}.get(e["on"], e["on"])
        count = f"{e['count']} {e.get('count_label', '')}s × " if e.get("count", 1) > 1 else ""
        parts = " + ".join(e["parts"]) + (" + spellcasting modifier" if e.get("mod") else "")
        up = []
        if e.get("upcast") and any(e["upcast"]):
            up.append(f"+{' / '.join(x for x in e['upcast'] if x)} per slot level{' (every two)' if e.get('every') == 2 else ''}")
        if e.get("count_upcast"):
            up.append(f"+{e['count_upcast']} {e.get('count_label', '')} per slot level")
        if e.get("cantrip"):
            up.append({"count": "more beams at levels 5, 11, 17", "extra": "none before level 5, then ×1/×2/×3 at levels 5, 11, 17"}.get(e["cantrip"], "dice ×2/×3/×4 at levels 5, 11, 17"))
        rep = f"; again at the {e['repeat']}" if e.get("repeat") else ""
        bits.append(f"{e.get('name', '')}: {count}{parts} ({on}{rep}){'; ' + '; '.join(up) if up else ''}")
    return " · ".join(bits) or "no damage or healing roll"


def write_report(rows, phb_rows=(), item_rows=(), beast_rows_=(), campaign=None) -> None:
    lines = ["# Roll audit", "",
             "How askdnd rolls each SRD 5.2.1 spell that has dice, generated by `scripts/roll_audit.py` from the 2024 rules",
             "text (the SRD, CC-BY-4.0, in `app/data/srd/`). \"read from the text\": every dice expression in the description",
             "is used by the recipe or is not a roll you make (a target's bonus die, a duration). \"by hand\": written in",
             "`app/data/rules/<book>.json` because the text needs judgment; the reason is given. Don't edit this file: run",
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
              "Every SRD Beast action with dice (`app/data/srd/monsters.json`), as askdnd rolls it in a form (`wild_shape.beast_recipe`).",
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
    sys.exit(build())
