"""Load a private rules book's entries into the database (app/books.py), from the offline copy in private/books/.

The first book (data strategy, Brett's answer 8): the 2024 Monster Manual's Beasts, for Wild Shape. They come from
private/books/mm-2024/monsters-data.json (D&D Beyond's data for each stat block, saved by scripts/book_receiver.py),
turned into askdnd's monster shape (rules_data.Monster) and written to book_entries. Nothing from the book goes into
the repo, test fixtures or docs: the repo is treated as public.

    uv run --env-file .env python scripts/book_load.py --compare   # check the conversion against the SRD's copies
    uv run --env-file .env python scripts/book_load.py --dry-run   # convert and validate, write nothing
    uv run --env-file .env python scripts/book_load.py             # write to DATABASE_URL (asks before a remote one)

Running it again replaces the book's Beasts with what the file has now. Loading beta's copy is Brett's call.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import rules_data  # noqa: E402
from app.ddb import ALIGNMENTS, SIZES, html_to_text  # noqa: E402
from app.ddb_sheet import ABILITY_KEY, MOVES, SENSE_NAMES  # noqa: E402

BOOK = "mm-2024"
FILE = ROOT / "private" / "books" / "mm-2024" / "monsters-data.json"
DDB_SOURCE = 147  # D&D Beyond's id for the 2024 Monster Manual

# D&D Beyond's ids (checked against the SRD's copies of the same monsters with --compare)
TYPES = {1: "Aberration", 2: "Beast", 3: "Celestial", 4: "Construct", 6: "Dragon", 7: "Elemental", 8: "Fey", 9: "Fiend",
         10: "Giant", 11: "Humanoid", 13: "Monstrosity", 14: "Ooze", 15: "Plant", 16: "Undead"}
SUBTYPES = {9: "Demon", 10: "Devil", 19: "Titan", 23: "Goblinoid", 47: "Angel", 74: "Wizard", 77: "Cleric", 81: "Metallic",
            82: "Chromatic", 98: "Dinosaur", 179: "Genie", 180: "Lycanthrope"}
# Damage adjustments: resistances from 1, immunities from 17, vulnerabilities from 33, each in this order
DAMAGE_ORDER = ("Bludgeoning", "Piercing", "Slashing", "Lightning", "Thunder", "Poison", "Cold", "Radiant", "Fire",
                "Necrotic", "Acid", "Psychic", "Force")
ADJUSTMENTS = {start + i: (field, kind) for field, start in (("resistances", 1), ("immunities", 17), ("vulnerabilities", 33))
               for i, kind in enumerate(DAMAGE_ORDER)}
XP = {0: 10, 0.125: 25, 0.25: 50, 0.5: 100, 1: 200, 2: 450, 3: 700, 4: 1100, 5: 1800, 6: 2300, 7: 2900, 8: 3900, 9: 5000,
      10: 5900, 11: 7200, 12: 8400, 13: 10000, 14: 11500, 15: 13000, 16: 15000, 17: 18000, 18: 20000, 19: 22000,
      20: 25000, 21: 33000, 22: 41000, 23: 50000, 24: 62000, 25: 75000, 26: 90000, 27: 105000, 28: 120000, 29: 135000,
      30: 155000}


class Unconvertible(ValueError):
    """Something in D&D Beyond's data this converter doesn't know yet: fail loudly rather than guess."""


def _cr(ddb_id: int) -> float:
    return {1: 0.0, 2: 0.125, 3: 0.25, 4: 0.5}.get(ddb_id, float(ddb_id - 4))


def _pb(cr: float) -> int:
    return 2 + max(0, (int(cr) - 1) // 4) if cr >= 1 else 2


def _text(html: str | None) -> str:
    """D&D Beyond's HTML as the SRD's plain text: one space between words, none before punctuation, straight
    apostrophes, a minus sign in dice ("1d4 − 1"), and without D&D Beyond's tooltip and dice markup
    ("opportunity attack;Opportunity Attacks", "+5;{"diceNotation": …})")."""
    text = re.sub(r"[ \t]+", " ", html_to_text(html)).replace("’", "'")
    text = re.sub(r";\{[^}]*\}\)", "", text)
    text = re.sub(r"\b((?:\w+ ){0,3}\w+);((?:\w+ ){0,3}\w+)\b", _untooltip, text)
    text = re.sub(r"(\d) [–-] (\d)", r"\1 − \2", text)
    return re.sub(r" ([,.;:])", r"\1", text).strip()


def _untooltip(m: re.Match) -> str:
    """"grapple;grappling" -> "grappling": D&D Beyond's tooltip key before the semicolon, the words shown after it
    (as many words on each side, the first sharing its start)."""
    left, right = m.group(1).split(), m.group(2).split()
    for n in range(min(len(left), len(right)), 0, -1):
        key, shown = left[-n:], right[:n]
        if key[0][:4].lower() == shown[0][:4].lower():
            return " ".join(left[:-n] + shown + right[n:])
    return m.group(0)


def _entries(html: str | None) -> list[dict]:
    """"<p><strong>Bite.</strong> Melee Attack Roll: …</p>" paragraphs as [{"name": "Bite", "text": "Melee…"}]."""
    out = []
    for para in (p.strip() for p in _text(html).split("\n") if p.strip()):
        m = re.match(r"([^.]{1,60}?(?:\([^)]*\))?)\.\s+(.*)", para, re.S)
        if m:
            out.append({"name": m.group(1).strip(), "text": m.group(2).strip()})
        elif out:
            out[-1]["text"] += "\n\n" + para
    return out


def _bonuses(text: str) -> dict[str, int]:
    """"Stealth +4, Perception +5" -> {"Stealth": 4, "Perception": 5}."""
    out = {}
    for part in filter(None, (p.strip() for p in _text(text).split(","))):
        m = re.fullmatch(r"(.+?) ([+−-]\d+)", part)
        if not m:
            raise Unconvertible(f"skill {part!r}")
        out[m.group(1)] = int(m.group(2).replace("−", "-"))
    return out


def _hit_dice(s: str) -> str:
    """"4d8 + -4" -> "4d8 − 4", as the SRD prints it."""
    m = re.fullmatch(r"(\d+d\d+)(?: \+ (-?\d+))?", s.strip())
    if not m:
        raise Unconvertible(f"hit dice {s!r}")
    n = int(m.group(2) or 0)
    return m.group(1) + (f" + {n}" if n > 0 else f" − {-n}" if n < 0 else "")


def printed(folder: Path) -> dict[str, dict]:
    """What the book's own text (the Markdown copy beside the data) prints for each stat block that D&D Beyond's data
    leaves out or gets wrong: every saving throw (the SAVE column) and the XP. {"Mastiff": {"saves": …, "xp": 25}}."""
    out: dict[str, dict] = {}
    for md in sorted(folder.glob("*.md")):
        for block in re.split(r"\n(?=#{2,4} )", md.read_text(encoding="utf-8")):
            head = re.match(r"#{2,4} (.+)", block)
            saves = dict(re.findall(r"^\| (Str|Dex|Con|Int|Wis|Cha) \| \d+ \| [+−-]\d+ \| ([+−-]\d+) \|", block, re.M))
            xp = re.search(r"^CR [\d/]+ \(XP ([\d,]+)", block, re.M)
            if head and len(saves) == 6 and xp:
                out[head.group(1).strip()] = {"saves": {k.lower(): int(v.replace("−", "-")) for k, v in saves.items()},
                                              "xp": int(xp.group(1).replace(",", ""))}
    return out


def convert(m: dict, book_text: dict | None = None) -> tuple[dict, int | None, str]:
    """One D&D Beyond monster as (askdnd's monster entry, its page, its picture link), with the saves and XP the
    book prints where `book_text` has them (printed()). Raises Unconvertible."""
    name = m["name"].strip()
    if m.get("typeId") not in TYPES:
        raise Unconvertible(f"{name}: creature type {m.get('typeId')}")
    if any(s not in SUBTYPES for s in m.get("subTypes") or []):
        raise Unconvertible(f"{name}: tags {m.get('subTypes')}")
    if m.get("isLegendary") or m.get("isMythic") or m.get("hasLair") or m.get("legendaryActionsDescription"):
        raise Unconvertible(f"{name}: legendary actions aren't converted yet")
    cr = _cr(m["challengeRatingId"])
    pb = _pb(cr)
    abilities = {ABILITY_KEY[s["statId"]][:3]: s["value"] for s in m["stats"]}
    proficient = {ABILITY_KEY[s["statId"]][:3]: s.get("bonusModifier") or 0 for s in m.get("savingThrows") or []}
    saves = {k: (v - 10) // 2 + (pb + proficient[k] if k in proficient else 0) for k, v in abilities.items()}
    adjust = {"resistances": [], "immunities": [], "vulnerabilities": []}
    for a in m.get("damageAdjustments") or []:
        if a not in ADJUSTMENTS:
            raise Unconvertible(f"{name}: damage adjustment {a}")
        field, kind = ADJUSTMENTS[a]
        adjust[field].append(kind)
    senses, senses_note = {}, []
    for s in m.get("senses") or []:
        got = re.match(r"\s*(\d+)(?: ft\.)?\s*(.*)", s.get("notes") or "")
        if s.get("senseId") not in SENSE_NAMES or not got:
            raise Unconvertible(f"{name}: sense {s}")
        senses[SENSE_NAMES[s["senseId"]].lower()] = int(got.group(1))
        if got.group(2).strip():
            senses_note.append(got.group(2).strip(" ()"))
    speed, hover = {}, False
    for mv in m.get("movements") or []:
        if mv.get("movementId") not in MOVES:
            raise Unconvertible(f"{name}: movement {mv}")
        if mv.get("speed"):
            speed[MOVES[mv["movementId"]]] = mv["speed"]
        hover = hover or "hover" in (mv.get("notes") or "").lower()
    swarm = m.get("swarm") or {}
    languages = _text(m.get("languageDescription")) or ("None" if not m.get("languages") else "")
    if not languages:
        raise Unconvertible(f"{name}: languages by id aren't converted yet")
    entry = {
        "key": rules_data.slug(name), "name": name, "size": SIZES[m["sizeId"]], "type": TYPES[m["typeId"]],
        "tags": [SUBTYPES[s] for s in m.get("subTypes") or []], "swarm_of": SIZES[swarm["sizeId"]] if swarm else "",
        "alignment": ALIGNMENTS.get(m["alignmentId"], "Unaligned"), "ac": m["armorClass"], "initiative": m.get("initiativeBonus") or 0,
        "hp": m["averageHitPoints"], "hit_dice": _hit_dice(m["hitPointDice"]["diceString"]), "speed": speed, "hover": hover,
        "abilities": abilities, "saves": saves, "skills": _bonuses(m.get("skillsHtml") or ""), **adjust,
        "condition_immunities": [c.strip() for c in _text(m.get("conditionImmunitiesHtml")).split(",") if c.strip()],
        "senses": senses, "senses_note": "; ".join(senses_note), "passive_perception": m["passivePerception"],
        "languages": languages, "cr": cr, "cr_label": rules_data.cr_label(cr), "xp": XP[cr], "pb": pb,
        "traits": _entries(m.get("specialTraitsDescription")), "actions": _entries(m.get("actionsDescription")),
        "bonus_actions": _entries(m.get("bonusActionsDescription")), "reactions": _entries(m.get("reactionsDescription")),
        "section": "Animals" if m["typeId"] == 2 else "", "source": "",
    }
    entry |= (book_text or {}).get(name, {})
    rules_data.check("monster", {**entry, "source": "MM 2024"})
    return entry, m.get("sourcePageNumber"), m.get("avatarUrl") or ""


def beasts(path: Path) -> list[tuple[dict, int | None, str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    book_text = printed(path.parent)
    return [convert(m, book_text) for m in data if m.get("typeId") == 2 and m.get("sourceId") == DDB_SOURCE]


def compare(rows) -> int:
    """Each converted Beast against the SRD's copy of it (the same stat block, from the free rules): prints the fields
    that differ. Text is compared too, so the differences printed are the conversion's, or the two books'."""
    srd = {m["key"]: m for m in rules_data.srd("monster")}
    differ = 0
    for entry, _, _ in rows:
        theirs = srd.get(entry["key"])
        if theirs is None:
            print(f"{entry['name']}: only in the book")
            continue
        entry = rules_data.Monster.model_validate({**entry, "source": "MM 2024"}).model_dump()  # with the schema's defaults
        diffs = [k for k in entry if k not in ("source", "section", "group") and entry[k] != theirs.get(k)]
        if diffs:
            differ += 1
            print(f"{entry['name']}: " + "; ".join(f"{k} {entry[k]!r} vs SRD {theirs.get(k)!r}" for k in diffs))
    print(f"{len(rows)} Beasts, {differ} differ from the SRD's copy")
    return differ


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--file", type=Path, default=FILE, help="the book's monsters-data.json")
    ap.add_argument("--compare", action="store_true", help="compare with the SRD's copies; write nothing")
    ap.add_argument("--dry-run", action="store_true", help="convert and validate; write nothing")
    ap.add_argument("--yes", action="store_true", help="don't ask before writing to a database that isn't on this Mac")
    args = ap.parse_args()
    if not args.file.exists():
        sys.exit(f"No {args.file}: the offline copy lives in private/books/ of the main checkout (scripts/book_receiver.py).")
    rows = beasts(args.file)
    if args.compare:
        compare(rows)
        return
    print(f"{len(rows)} Beasts from the Monster Manual (2024) converted and valid.")
    if args.dry_run:
        return

    from sqlalchemy import delete, select

    from app import books, config
    from app.db import SessionLocal
    from app.models import BookEntry

    url = config.DATABASE_URL or ""
    where = url.split("@")[-1]
    if not re.search(r"(^|//|@)(localhost|127\.0\.0\.1)[:/]", url) and not args.yes:
        if input(f"Write them to {where}? Type yes: ").strip().lower() != "yes":
            sys.exit("Nothing written.")
    with SessionLocal() as db:
        keys = []
        for entry, page, image in rows:
            books.save(db, BOOK, "monster", entry, page=page, image=image)
            keys.append(entry["key"])
        gone = db.scalars(select(BookEntry.key).where(BookEntry.book == BOOK, BookEntry.kind == "monster", BookEntry.key.not_in(keys))).all()
        db.execute(delete(BookEntry).where(BookEntry.book == BOOK, BookEntry.kind == "monster", BookEntry.key.not_in(keys)))
        db.commit()
    print(f"Wrote {len(rows)} Beasts to {where}" + (f"; removed {len(gone)} no longer in the file" if gone else "") + ".")


if __name__ == "__main__":
    main()
