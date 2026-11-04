"""Load the 2024 Player's Handbook's summoned creatures into askdnd, as a private book (app/books.py, kind "summon";
Brett, 2026-11-04: summons and Find Steed are askdnd's own, DECISIONS): each Summon spell's spirit and Find Steed's
Otherworldly Steed, read from the offline copy in private/books/phb-2024/spell-descriptions.md, kept as printed
("11 + the spell's level") for app/summons.py to work out. Their words go only into the database, never the repo.

    uv run --env-file .env python scripts/summon_load.py             # into the local database
    uv run --env-file .env python scripts/summon_load.py --export    # the upload file for beta (private/books/)

Beta's database has no public address: Manage › askdnd › Backups and imports › Books takes the --export file.
"""

import argparse
import gzip
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

BOOK = "phb-2024"
FILE = ROOT / "private" / "books" / "phb-2024" / "spell-descriptions.md"
EXPORT = ROOT / "private" / "books" / "phb-2024-summons-upload.json.gz"
SPELLS = re.compile(r"^(Summon \w+|Find Steed)$")
ABILITIES = {"STR": "str", "DEX": "dex", "CON": "con", "INT": "int", "WIS": "wis", "CHA": "cha"}
SECTIONS = {"Traits": "traits", "Actions": "actions", "Bonus Actions": "bonus_actions", "Reactions": "reactions"}


def _clean(s: str) -> str:
    return " ".join(s.replace("’", "'").replace("–", "-").replace("−", "-").split())


def spells(text: str) -> dict[str, list[str]]:
    """Each summoning spell's lines, from its ### heading to the next."""
    out, name = {}, None
    for line in text.splitlines():
        if line.startswith("### "):
            title = line[4:].strip()
            name = title if SPELLS.match(title) else None
            if name:
                out[name] = []
        elif name is not None:
            out[name].append(line)
    return out


def _choices(lines: list[str], block: list[str]) -> list[str]:
    """What's chosen when it's cast: the spell's "choose a mood: Fuming, Mirthful, or Tricksy", else the stat block's
    "(Air only)" marks, or "Celestial, Fey, or Fiend (Your Choice)"."""
    for line in lines:
        if m := re.search(r"[Cc]hoose (?:an?|the) [\w ]+?: ([A-Z][\w ]*(?:, [A-Z][\w ]*)*,? or [A-Z][\w ]*)\.", _clean(line)):
            return [x.strip() for x in re.split(r",\s*(?:or\s+)?|\s+or\s+", m.group(1)) if x.strip()]
    found: list[str] = []
    for line in block:
        if m := re.search(r"([A-Z][\w ,]+?),? or (\w+) \(Your Choice\)", line):
            found += [re.sub(r"^(Tiny|Small|Medium|Large|Huge|Gargantuan) ", "", x.strip()) for x in m.group(1).split(",") if x.strip()] + [m.group(2)]
        for m in re.finditer(r"\((?:[^();]*;\s*)?([A-Z][\w ,]*?) [Oo]nly", line):
            found += [x.strip() for x in re.split(r",\s*|\s+and\s+|\s+or\s+", m.group(1))]
    out = []
    for x in found:
        if x and x not in out:
            out.append(x)
    return out


def entry(spell: str, lines: list[str]) -> dict | None:
    """The spell's stat block as a "summon" entry (app/rules_data.py Summon)."""
    text = "\n".join(lines)
    level = re.search(r"Level (\d) ", text)
    at = next((i for i, x in enumerate(lines) if x.startswith("#### ")), None)
    if not level or at is None:
        return None
    pre, block = lines[:at], [x for x in lines[at:] if x.strip()]
    name = block[0][5:].strip()
    e = {"name": _clean(name), "spell": spell, "spell_level": int(level.group(1)), "what": _clean(block[1]),
         "ac": "", "hp": "", "speed": "", "abilities": {}, "senses": "", "languages": "",
         "concentration": "Duration: Concentration" in text}
    for p in pre:  # how it acts and when it goes, from the spell's own paragraphs
        p = _clean(p)
        if "Initiative" in p and not e.get("turn"):
            e["turn"] = re.sub(r"^Combat\. ", "", p)
        if p.startswith("Disappearance") or "disappears if" in p:
            e["goes"] = re.sub(r"^Disappearance of the \w+\. ", "", p)
    section = None
    for line in block[2:]:
        line = _clean(line)
        for k in ("AC", "HP", "Speed", "Senses", "Languages"):
            if line.startswith(k + " "):
                e[k.lower()] = line[len(k) + 1:]
        if m := re.match(r"^\| (STR|DEX|CON|INT|WIS|CHA) \| (\d+) \|", line):
            e["abilities"][ABILITIES[m.group(1)]] = int(m.group(2))
        if line in SECTIONS:
            section = SECTIONS[line]
            e.setdefault(section, [])
            continue
        if section and (m := re.match(r"^(.+?)\. (.+)$", line)) and not line.startswith(("|", "CR ")):
            e[section].append({"name": m.group(1), "text": m.group(2)})
    e["choose"] = _choices(pre, block)
    return e


def load(path: Path = FILE) -> list[dict]:
    return [e for s, lines in spells(path.read_text(encoding="utf-8")).items() if (e := entry(s, lines))]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--export", nargs="?", const=EXPORT, type=Path, help="write the upload file for beta instead (default: %(const)s)")
    args = ap.parse_args()
    found = load()
    rows = [[e, None, ""] for e in found]
    from app import rules_data

    for e in found:
        rules_data.check("summon", {**e, "key": rules_data.slug(e["name"]), "source": "PHB 2024"})
    print(f"{len(found)} summoned creatures: " + ", ".join(f"{e['name']} ({e['spell']}, {'/'.join(e['choose']) or 'no choice'})" for e in found))
    if args.export:
        args.export.write_bytes(gzip.compress(json.dumps({"book": BOOK, "kind": "summon", "rows": rows}).encode()))
        print(f"Wrote {args.export}: upload it on Manage › askdnd › Backups and imports › Books")
        return
    from app import books
    from app.db import SessionLocal

    with SessionLocal() as db:
        written, gone = books.replace(db, BOOK, "summon", [tuple(r) for r in rows])
        db.commit()
    print(f"Local database: {written} written, {gone} removed")


if __name__ == "__main__":
    main()
