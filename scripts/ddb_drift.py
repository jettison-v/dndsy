"""Has D&D Beyond's sheet changed shape under our tests? (Brett, 2026-11-05: the testing round.)

    uv run python scripts/ddb_drift.py

Every test outside the live test reads D&D Beyond through the copies in tests/fixtures/ddb, taken weeks ago. D&D Beyond
changes its data without notice, and the tests would go on passing on the old copies while beta read the new ones
wrong. This reads today's test sheets (VTT test's, docs/testing-setup.md; public reads, as askdnd makes them) and says:

- **gone**: a field the copies have that no sheet has today (in a part of the sheet that's there): askdnd may read it;
- **changed**: a field whose kind changed (a number that's now text, a list that's now an object);
- **parsed**: askdnd's own parser on each sheet today gives what every character has (a name, a level, Hit Points,
  Armor Class, six abilities and saves, eighteen skills, a class, actions or attacks, items, and spells for these casters).

Runs every morning on GitHub (.github/workflows/ddb-drift.yml), where a miss fails the run and GitHub emails Brett.
Exits 1 on any of them. Only reads; never the table's characters, never Brett's own account.
"""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SHEETS = {"Cathartic": "172986165", "Vi (test)": "172992073", "Levi": "173148163"}  # VTT test's seats, as in real_table.py
OURS = (".askdnd", ".noteItemIds")  # what askdnd adds to a copy itself (app/ddb.py), never D&D Beyond's


def shape(o, path: str = "", depth: int = 0, out: dict | None = None, deepest: int = 3) -> dict[str, set[str]]:
    """{path: the kinds of value found there}, three levels down, a list's items under `[]`."""
    out = {} if out is None else out
    out.setdefault(path or ".", set()).add(type(o).__name__)
    if depth < deepest and isinstance(o, dict):
        for k, v in o.items():
            shape(v, f"{path}.{k}", depth + 1, out, deepest)
    elif depth < deepest and isinstance(o, list):
        for v in o:
            shape(v, f"{path}[]", depth + 1, out, deepest)
    return out


def compare(copies: dict, today: dict) -> tuple[list[str], list[str]]:
    """(gone, changed) between the copies' shape and today's. A field under a part that's missing or an empty list today
    isn't gone: that's what's on these sheets (no custom items), not D&D Beyond changing."""
    parent = lambda p: (p[:-2] if p.endswith("[]") else p.rsplit(".", 1)[0]) or "."
    gone = sorted(p for p in copies if p not in today and not p.startswith(OURS) and not p.endswith("[]") and parent(p) in today)
    kinds = lambda s: s - {"NoneType"}
    changed = sorted(f"{p}: {'/'.join(sorted(kinds(copies[p])))} → {'/'.join(sorted(kinds(today[p])))}"
                     for p in copies if p in today and kinds(copies[p]) and kinds(today[p]) and not kinds(copies[p]) & kinds(today[p]))
    return gone, changed


def essentials(s: dict) -> list[str]:
    """What's missing from a parsed sheet that every character here has."""
    hp = s.get("hit_points") or {}
    checks = {"a name": bool(s.get("name")), "a level": (s.get("level") or 0) > 0, "Hit Points": (hp.get("max") or 0) > 0,
              "Armor Class": (s.get("armor_class") or 0) > 0, "six abilities": len(s.get("abilities") or []) == 6,
              "six saves": len(s.get("saves") or []) == 6, "eighteen skills": len(s.get("skills") or []) == 18,
              "a class": bool(s.get("classes")), "actions or attacks": bool(s.get("actions") or s.get("attacks")),
              "items": bool(s.get("inventory")), "spells": bool(s.get("spells"))}
    return [k for k, ok in checks.items() if not ok]


def main() -> int:
    from app import characters, ddb

    import fixtures  # (the saved sheets are locked: unlocked on first use; FIXTURES_KEY is the workflow's secret)

    fixtures.ready()
    copies: dict = {}
    for f in sorted((ROOT / "tests/fixtures/ddb").glob("*.json")):
        d = json.loads(f.read_text())
        d = d.get("data", d) if isinstance(d, dict) else d
        if isinstance(d, dict) and "classes" in d:
            shape(d, out=copies)
    today: dict = {}
    problems = []
    for name, ddb_id in SHEETS.items():
        got = characters.read(ddb_id, fetch=ddb.fetch_character_json)
        if got.error:
            problems.append(f"{name}: couldn't be read ({got.error})")
            continue
        shape(got.raw, out=today)
        if missing := essentials(got.summary):
            problems.append(f"{name}: askdnd's parser found no {', '.join(missing)}")
    if today:
        gone, changed = compare(copies, today)
        problems += [f"gone from D&D Beyond's sheet: {p}" for p in gone] + [f"changed kind: {c}" for c in changed]
    print("\n".join(problems) or f"No drift: {len(SHEETS)} sheets read, parsed, and shaped like the test copies.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
