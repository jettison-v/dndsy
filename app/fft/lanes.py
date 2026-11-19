"""Which lane a plan takes, from the files its change touches (the work flow's slice 3; Brett's picks, Nov 19).

Careful where a mistake hurts people or can't be undone, Look where a person sees it, Ship otherwise. The lists are
askdnd's own (app/data/lanes.json), so another product brings its own. A rule only ever picks; a person or Claude may
move a plan up (rules.set_lane), and only an admin down."""

import json
from fnmatch import fnmatch
from pathlib import Path

RULES = Path(__file__).resolve().parent.parent / "data" / "lanes.json"


def rules() -> dict:
    return json.loads(RULES.read_text())


def pick(files: list[str], read=None) -> tuple[str, str]:
    """(lane, why) for a change touching `files`. `read(path)` gives a migration's text, to tell one that only adds
    from one that alters or removes data."""
    r = rules()
    hit = lambda f, globs: any(fnmatch(f, g) for g in globs)
    careful = [f for f in files if hit(f, r["careful"])]
    if careful:
        return "careful", "It touches " + ", ".join(careful[:3]) + ("…" if len(careful) > 3 else "")
    for f in files:
        if f.startswith("migrations/versions/") and f.endswith(".py") and read is not None:
            text = _upgrade(read(f) or "")
            said = [m for m in r["careful_migration"] if m in text]
            if said:
                return "careful", f"Its database change ({f.rsplit('/', 1)[-1]}) alters or removes data: {said[0].strip()}"
    look = [f for f in files if hit(f, r["look"])]
    if look:
        return "look", "People see it: " + ", ".join(look[:3]) + ("…" if len(look) > 3 else "")
    return "ship", "Nothing a person sees: " + (", ".join(files[:3]) + ("…" if len(files) > 3 else "") if files else "no files")


ORDER = ("ship", "look", "careful")


def higher(a: str, b: str) -> bool:
    """Is lane a above lane b?"""
    return ORDER.index(a) > ORDER.index(b)


def _upgrade(text: str) -> str:
    """A migration's upgrade() alone (its downgrade() drops what it added, which is fine)."""
    start = text.find("def upgrade(")
    end = text.find("def downgrade(", start)
    return text[start:end] if start >= 0 else text
