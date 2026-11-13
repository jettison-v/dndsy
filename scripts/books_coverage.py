"""Does askdnd's roll data cover the books? (the outside review's R2, Nov 10; Brett, Nov 12: "continue with the roll
card coverage"). Reads the offline Player's Handbook and DMG (private/books/, never committed), lists every class
feature, subclass feature, feat, species trait and magic item whose words hold dice, a saving throw or a bonus to a roll,
and says for each whether askdnd's data plays it, leaves it in words on purpose (and why), or is missing it.

    uv run python scripts/books_coverage.py          # writes tests/fixtures/book-index.json and docs/rules/books-coverage.md

The index keeps names, classes, levels and what kind of number each has (dice, a save, a bonus): never the book's
words, so it's committed, and tests/test_books_coverage.py builds made-up characters from it (every class and subclass
at levels 1, 5, 11 and 17) without the private books, and fails on a missing one not in `KNOWN_GAPS`.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

PHB = ROOT / "private" / "books" / "phb-2024"
DMG = ROOT / "private" / "books" / "dmg-2024"
INDEX = ROOT / "tests" / "fixtures" / "book-index.json"
REPORT = ROOT / "docs" / "rules" / "books-coverage.md"
LEVELS = (1, 5, 11, 17)

DICE = re.compile(r"\b\d*d(?:4|6|8|10|12|20|100)s?\b")
SAVE = re.compile(r"saving throw[^.]{0,80}\b(?:DC|against your)|\bDC (?:equals|\d)|succeed on a [A-Z][a-z]+ saving throw", re.I)
BONUS = re.compile(r"bonus to (?:the |your |its |an? )?(?:damage|attack|saving throw|ability check|AC|Armor Class|Initiative|roll)"
                   r"|\badds? [^.]{0,80}?\bto (?:[\w’']+ ){0,3}?(?:rolls?|damage|saving throws?|checks?|attack)"
                   r"|\bextra damage\b|\bminimum\b[^.]{0,40}\broll|\breduces? (?:the |that )?damage|damage[^.]{0,80}\bis reduced by"
                   r"|\bregains?\b[^.]{0,60}\bHit Points|\bTemporary Hit Points equal", re.I)

# What askdnd leaves in words on purpose, and why: it isn't a roll the character makes, or another part of askdnd has it.
ON_PURPOSE = {
    "Cutting Words": "acts on someone else's roll, after they see it",
    "Bend Luck": "acts on someone else's roll, after they see it",
    "Cosmic Omen": "acts on someone else's roll, after they see it",
    "Portent": "replaces a roll with a die rolled at dawn, decided by the player",
    "Greater Portent": "Portent's third die, decided by the player",
    "Lucky": "played by the roll card's Luck points",
    "Ability Score Improvement": "changes the sheet's numbers, which askdnd reads",
    "Epic Boon": "a choice of boon, each its own feat",
    "Spellcasting": "the spell save DC and attack come from the sheet",
    "Pact Magic": "the spell save DC and attack come from the sheet",
    "Weapon Mastery": "each mastery is a rider the roll card plays (roll_plan riders)",
    "Unarmored Defense": "AC, read from the sheet",
    "Fighting Style": "a choice of style, each its own feat",
    "Extra Attack": "how many attacks, class_rules",
    "Jack of All Trades": "in the sheet's check bonuses",
    "Expertise": "in the sheet's check bonuses",
    "Remarkable Athlete": "in the sheet's check and Initiative bonuses",
    "Reliable Talent": "a check's floor, said by the player",
    "Wild Shape": "askdnd's Wild Shape forms (app/wild_shape.py)",
    "Improved Circle Forms": "askdnd's Wild Shape forms add it (app/wild_shape.py)",
    "Improved Combat Superiority": "the Superiority Die's size, a named scale",
    "Ultimate Combat Superiority": "the Superiority Die's size, a named scale",
    "Twinkling Constellations": "Starry Form's dice, a named scale",
    "Hit Points": "the sheet's",
    "Druidic": "a check others make to spot a message",
    "Monk's Focus": "the Focus save DC is the sheet's",
    "Channel Divinity": "each Channel Divinity option is its own entry",
    "Greater Divine Intervention": "how many Long Rests until it's back (2d4): Any dice",
    "Star Map": "free Guiding Bolt casts, through the Cast window; the spell's own roll",
    "Fey Wanderer Spells": "a gift chosen or rolled once (1d6): Any dice",
    "Clockwork Spells": "a manifestation chosen or rolled once: Any dice",
    "Wild Magic Surge": "a d20 after a spell and a d100 table: Any dice, the DM reads the table",
    "Tides of Chaos": "Advantage on one D20 Test, the player's choice",
    "Tamed Surge": "a chosen Wild Magic Surge effect",
    "Restore Balance": "acts on someone else's roll",
    "Trance of Order": "a d20's floor, said by the player",
    "Use Magic Device": "a d6 to keep charges: Any dice",
    "Supreme Sneak": "a Cunning Strike option with no roll",
    "Relentless": "a d8 in place of a Superiority Die once a turn, said",
    "Bait and Switch": "a bonus to AC until your next turn, said",
    "Overchannel": "maximum damage and its cost, said by the player",
    "Empowered Spell": "rerolling damage dice: the roll card's Reroll",
    "Seeking Spell": "rerolling a missed spell attack: the roll card's Reroll",
    "Corona of Light": "Disadvantage on saves for enemies, the DM's roll",
    "Psychic Whispers": "hours of telepathy (a Psionic Energy Die): Any dice",
    "Investment of the Chain Master": "the familiar's own Battle has its numbers",
    "Arcane Ward": "a ward's Hit Points, kept by the player",
    "Bastion of Law": "a ward of d8s the warded creature spends, kept by the player",
    "Relentless Rage": "your own Con save (DC 10, up 5 each use): Table rolls' Con save",
    "Durable": "Speedy Recovery is a Hit Point Die (Table rolls' Roll); Defy Death's Advantage is said",
    "Boon of Spell Recall": "a d4 to keep a slot: Any dice",
    "Boon of Irresistible Offense": "extra damage on a 20, said",
    "Boon of Fortitude": "extra healing once a turn, said",
    "Poisoner": "a poison brewed with the kit: Any dice; Potent Poison ignores Resistance, said",
    "Beguiling Defenses": "half the damage back on a failed save, said",
    "Create Thrall": "the summoned Aberration's own numbers",
}

# Numbers D&D Beyond's sheet already applies, which askdnd reads.
SHEET = {
    "Archery": "+2 on ranged attacks, in the sheet's attack bonus",
    "Defense": "+1 AC, in the sheet's AC",
    "Dueling": "+2 damage, in the sheet's weapon damage",
    "Thrown Weapon Fighting": "+2 damage, in the sheet's weapon damage",
    "Two-Weapon Fighting": "the ability modifier on the extra attack, in the sheet's weapon damage",
    "Unarmed Fighting": "the Unarmed Strike's damage, in the sheet's (its 1d4 to a grappled creature: Any dice)",
    "Alert": "Initiative, in the sheet's Initiative",
    "Crossbow Expert": "in the sheet's attacks",
    "Initiative Bonus": "Initiative, in the sheet's Initiative",
    "Psychic Blades": "a weapon on the sheet, with its own attack and damage",
}


def norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (name or "").lower().replace("’", "'")).strip()


def kinds(text: str) -> list[str]:
    return [k for k, rx in (("dice", DICE), ("save", SAVE), ("bonus", BONUS)) if rx.search(text)]


PART = re.compile(r"^([A-Z][A-Za-z’' ()-]{2,50}?)\. (.+)", re.S)
NOT_PARTS = {"Creature Type", "Size", "Speed", "Prerequisite", "Repeatable", "Duration", "Hit Points", "Armor Class"}


def parts(words: str) -> list[dict]:
    """The named parts inside an entry's words ("Divine Spark. …", "Turn Undead. …"), each with what numbers it has."""
    out = []
    for para in re.split(r"\n\s*\n", words):
        para = para.strip().lstrip("-* ").strip()
        if (m := PART.match(para)) and m.group(1) not in NOT_PARTS and len(m.group(1).split()) <= 5:
            if has := kinds(m.group(2)):
                out.append({"name": re.sub(r"\s*\(.*?\)", "", m.group(1)).strip(), "has": has})
    return out


def entry(row: dict, words: str) -> dict:
    row["has"] = kinds(words)
    if ps := parts(words):
        row["parts"] = ps
    return row


def _sections(path: Path, depth: int) -> list[tuple[str, str]]:
    """(heading, its words up to the next heading of this depth or shallower) for every heading of exactly `depth` #s."""
    lines = path.read_text().splitlines()
    out, cur, buf = [], None, []
    for ln in lines:
        m = re.match(r"^(#+) (.+)", ln)
        if m and len(m.group(1)) <= depth:
            if cur:
                out.append((cur, "\n".join(buf)))
            cur, buf = (m.group(2).strip() if len(m.group(1)) == depth else None), []
        elif cur:
            buf.append(ln)
    if cur:
        out.append((cur, "\n".join(buf)))
    return out


def classes() -> list[dict]:
    """Every class feature and subclass feature with its level, and every option a feature picks from (a Battle Master's
    maneuvers, Metamagic, Eldritch Invocations, with the level it needs), from the two chapter files."""
    out = []
    for f in ("character-classes.md", "character-classes-continued.md"):
        cls = sub = opts = None
        for depth, title, words in _walk(PHB / f):
            if opts and (depth < opts[0] or (depth == opts[0] and opts[0] < 5) or re.match(r"Level \d+:", title)):
                opts = None
            if opts:
                lv = re.search(r"Prerequisite: Level (\d+)", words)
                out.append(entry({"kind": "option", "name": title, "class": cls, "level": int(lv.group(1)) if lv else opts[1],
                                  **({"sub": sub} if sub else {}), "of": opts[2]}, words))
                continue
            if depth == 2:
                cls, sub = title, None
            elif depth == 3 and title.endswith(" Subclasses"):
                sub = ""
            elif depth == 4 and sub is not None and not title.endswith(" Options"):
                sub = title
            if title.endswith(" Options"):
                base = {"Maneuver Options": 3, "Metamagic Options": 2}.get(title, 1)
                opts = (depth, base, title.removesuffix(" Options"))
            elif depth in (4, 5) and (m := re.match(r"Level (\d+): (.+)", title)):
                name = m.group(2).strip()
                if name.endswith(" Subclass") or name in ("Ability Score Improvement", "Epic Boon"):
                    continue
                out.append(entry({"kind": "feature", "name": name, "class": cls, "level": int(m.group(1)),
                                  **({"sub": sub} if sub else {})}, words))
    return out


def _walk(path: Path):
    """(heading depth, heading, its own words up to the next heading) through a file."""
    depth, title, buf = None, None, []
    for ln in path.read_text().splitlines():
        m = re.match(r"^(#+) (.+)", ln)
        if m:
            if title:
                yield depth, title, "\n".join(buf)
            depth, title, buf = len(m.group(1)), m.group(2).strip(), []
        else:
            buf.append(ln)
    if title:
        yield depth, title, "\n".join(buf)


def feats() -> list[dict]:
    out, cat = [], None
    for d, title, words in _walk(PHB / "feats.md"):
        if d == 2:
            cat = title
        elif d == 3 and cat and cat.endswith("Feats") and title != "Parts of a Feat":
            out.append(entry({"kind": "feat", "name": title, "group": cat}, words))
    return out


def species() -> list[dict]:
    out, sp = [], None
    for d, title, words in _walk(PHB / "character-origins.md"):
        if d == 3:
            sp = title
        if d == 4 and title.endswith(" Traits"):
            for para in re.split(r"\n\s*\n", words):
                if (m := PART.match(para.strip().lstrip("-* "))) and m.group(1) not in NOT_PARTS:
                    out.append(entry({"kind": "species", "name": re.sub(r"\s*\(.*?\)", "", m.group(1)).strip(), "species": sp}, m.group(2)))
    return out


def items() -> list[dict]:
    out = []
    for d, title, words in _walk(DMG / "magic-items-a-z.md"):
        if d == 3:
            out.append(entry({"kind": "item", "name": title}, words))
    return out


def build() -> list[dict]:
    rows = classes() + feats() + species() + items()
    return [r for r in rows if r["has"] or r.get("parts")]


# ------------------------------------------------------------------ what askdnd's data plays (no private books needed)

def played_names() -> dict[str, str]:
    """Every name askdnd's roll data knows, normalized, with where: a book entry (or one of its adds), a compiled recipe,
    a class rule, a named scale."""
    from app import class_rules, rules_book

    out: dict[str, str] = {}
    for b, data in rules_book.books().items():
        for e in data.get("entries") or []:
            out.setdefault(norm(e["name"]), f"rules/{b}")
            for a in e.get("adds") or []:
                out.setdefault(norm(a.get("name")), f"rules/{b}")
        for s in data.get("scales") or {}:
            out.setdefault(norm(s), f"rules/{b} scale")
    recipes = json.loads((ROOT / "app" / "data" / "roll_recipes.json").read_text())
    for part in ("features", "items", "spells"):
        for k in recipes.get(part) or {}:
            out.setdefault(norm(k), f"recipe {part}")
    for r in class_rules.RULES:
        out.setdefault(norm(r.name), "class_rules")
    return out


def _known(name: str, known: dict[str, str]) -> str | None:
    n = norm(name)
    if n in known:
        return known[n]
    for k, w in known.items():
        if k.startswith(n + " ") or k.endswith(" " + n) or (len(n) > 6 and n.rstrip("s") == k.rstrip("s")):
            return w
    return None


def where(row: dict, known: dict[str, str]) -> tuple[str, str]:
    """("played", where) / ("partly", the parts missing) / ("sheet", what) / ("on purpose", why) / ("save only", "") /
    ("missing", "")."""
    name = row["name"].replace("’", "'")
    if name in ON_PURPOSE:
        return "on purpose", ON_PURPOSE[name]
    if name in SHEET:
        return "sheet", SHEET[name]
    if w := _known(row["name"], known):
        return "played", w
    if row["has"] == ["save"] and all(p["has"] == ["save"] for p in row.get("parts") or []):
        return "save only", ""
    ps = [p for p in row.get("parts") or [] if p["name"].replace("’", "'") not in ON_PURPOSE | SHEET]
    if ps:
        got = {p["name"]: _known(p["name"], known) for p in ps}
        if all(got.values()):
            return "played", ", ".join(sorted(set(got.values())))
        if any(got.values()):
            return "partly", "missing " + ", ".join(n for n, w in got.items() if not w)
    return "missing", ""


def write() -> None:
    rows = build()
    subs: dict[str, list[str]] = {}
    for r in classes():
        if r.get("sub") and r["sub"] not in subs.setdefault(r["class"], []):
            subs[r["class"]].append(r["sub"])
    INDEX.write_text(json.dumps({"about": "Names, classes, levels and the kind of number each entry has (dice, save, bonus), "
                                 "from the offline 2024 PHB and DMG by scripts/books_coverage.py; never their words.",
                                 "subclasses": subs, "entries": rows}, indent=1, ensure_ascii=False) + "\n")
    known = played_names()
    by = {"played": [], "partly": [], "sheet": [], "save only": [], "on purpose": [], "missing": []}
    for r in rows:
        st, w = where(r, known)
        by[st].append((r, w))
    lines = ["# The books' coverage", "",
             "What askdnd's roll data plays from the 2024 Player's Handbook and DMG: every class feature, subclass feature, feat, "
             "species trait and magic item whose words hold dice, a saving throw or a bonus to a roll. Written by "
             "`scripts/books_coverage.py` from the offline books (names only); `tests/test_books_coverage.py` checks it.", "",
             f"**{len(rows)} entries**: {len(by['played'])} played, {len(by['partly'])} partly, {len(by['sheet'])} the sheet's numbers, "
             f"{len(by['save only'])} a save with nothing for the character to roll, {len(by['on purpose'])} in words on purpose, "
             f"{len(by['missing'])} missing.", "",
             "**Played** means askdnd's data has it: an `add` plays on every roll it changes; a `rolls` entry plays on the Battle "
             "row D&D Beyond lists for it (activated features are listed as actions). **Save only**: the target rolls the save; "
             "its DC is the sheet's. Magic items are listed for reference: an item's rolls are added as the table's characters "
             "carry it.", ""]
    for kind, title in (("feature", "Class and subclass features"), ("option", "Options a feature picks from"), ("feat", "Feats"), ("species", "Species traits"), ("item", "Magic items (DMG)")):
        lines += [f"## {title}", "", "| Name | Where | Has | askdnd |", "|---|---|---|---|"]
        for st in ("missing", "partly", "save only", "sheet", "on purpose", "played"):
            for r, w in by[st]:
                if r["kind"] != kind:
                    continue
                at = (f"{r['class']} {r['level']}" + (f", {r['sub']}" if r.get("sub") else "")) if kind in ("feature", "option") else r.get("species") or r.get("group") or ""
                say = {"missing": "**missing**", "partly": f"**partly**: {w}", "on purpose": f"in words: {w}", "played": w,
                       "sheet": f"the sheet: {w}", "save only": "save only: the target rolls"}[st]
                lines.append(f"| {r['name']} | {at} | {', '.join(r['has'])} | {say} |")
        lines.append("")
    REPORT.write_text("\n".join(lines))
    print(f"{len(rows)} entries: " + ", ".join(f"{len(v)} {k}" for k, v in by.items()))


if __name__ == "__main__":
    write()
