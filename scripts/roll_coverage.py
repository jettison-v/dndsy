"""Does every rolling action at the table have a roll plan the roll card can play? (Brett, Nov 9: "How are we going to
ensure all rolling actions have the correct metadata for the component?") app/roll_plan.py builds a plan for every
Battle option; this lists, per character, how many are ready, unchecked (a number from D&D Beyond's data or read from
the words), roll nothing, or have a gap (dice in its words the plan doesn't roll), and why each gap is there.

    uv run python scripts/roll_coverage.py                 # the party's saved sheets (tests/fixtures/ddb), writes docs/rules/roll-coverage.md
    uv run --env-file .env python scripts/roll_coverage.py --table   # every character at a table, from the local copy of beta

Prints names and short phrases only (never the book's text).
"""

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import ddb, roll_plan  # noqa: E402

PARTY = {"Big C": "big_c", "Cole": "cole", "No Name": "no_name", "Trah": "trah"}
SOURCES = {"correction": "a correction", "checked": "checked recipe", "sheet": "the sheet", "rule": "askdnd's rule",
           "ddb": "D&D Beyond's data", "text": "read from its words"}


def fixture(name: str) -> dict:
    return ddb.parse_character(ddb.sanitize(json.loads((ROOT / "tests" / "fixtures" / "ddb" / f"{name}.json").read_text())["data"]))


def sheets(table: bool) -> list[tuple[str, dict]]:
    if not table:
        return [(n, fixture(f)) for n, f in PARTY.items()]
    from sqlalchemy import select

    from app import characters as chars
    from app.db import SessionLocal
    from app.models import CampaignCharacter, Character

    with SessionLocal() as db:
        rows = db.scalars(select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                          .where(CampaignCharacter.left_on.is_(None), Character.copy_of_id.is_(None)).order_by(Character.name)).unique().all()
        return [(c.name, s) for c in rows if (s := chars.character_summary(c))]


def says(p: dict) -> str:
    bits = []
    if p["choice"]:
        bits.append(p["choice"]["ask"].rstrip("?"))
    if p["attack"]:
        bits.append(f"to hit {p['attack']['bonus']:+d}")
    if p["save"]:
        bits.append(f"{p['save']['ability']} save" + (f" DC {p['save']['dc']}" if p["save"].get("dc") else ""))
    for part in p["damage"] + p["heal"]:
        bits.append(f"{part['dice']}{'+' + str(part['flat']) if part['flat'] and part['dice'] else part['flat'] if part['flat'] else ''} {part['type']}".strip())
    return " · ".join(bits)


def main() -> None:
    table = "--table" in sys.argv
    lines = ["# Roll coverage", "",
             "Whether the roll card can play each thing on Battle, by `scripts/roll_coverage.py` from app/roll_plan.py "
             + ("for every character at a table (the local copy of beta)." if table else "for the party's saved sheets (tests/fixtures/ddb)."),
             "Ready: every number from a checked recipe, the sheet or askdnd's rules. Unchecked: a number from D&D Beyond's data "
             "or read from its words. Gap: its words have dice the plan doesn't roll; each has its reason (app/roll_plan.py "
             "`KNOWN_GAPS`). Don't edit this file: run the script.", ""]
    total = Counter()
    for name, sheet in sheets(table):
        ps = roll_plan.plans(sheet)
        count = Counter(p["status"] for p in ps)
        total.update(count)
        lines += [f"## {name}", "", " · ".join(f"{count[k]} {k}" for k in ("ready", "unchecked", "gap", "no roll")), "",
                  "| Action | Cost | How it rolls | From | Status |", "|---|---|---|---|---|"]
        for p in ps:
            if p["status"] == "no roll":
                continue
            src = ", ".join(sorted({SOURCES.get(v, v) for v in p["sources"].values()}))
            why = "; ".join(p["gaps"]) + (f" ({roll_plan.KNOWN_GAPS[p['name']]})" if p["name"] in roll_plan.KNOWN_GAPS and p["gaps"] else "")
            lines.append(f"| {p['name']} | {p['cost']} | {says(p)} | {src} | {p['status']}{': ' + why if why else ''} |")
        lines.append("")
    lines.insert(5, "**All together:** " + " · ".join(f"{total[k]} {k}" for k in ("ready", "unchecked", "gap", "no roll")) + "\n")
    out = "\n".join(lines)
    if table:
        print(out)
    else:
        (ROOT / "docs" / "rules" / "roll-coverage.md").write_text(out)
        print("Wrote docs/rules/roll-coverage.md:", dict(total))


if __name__ == "__main__":
    main()
