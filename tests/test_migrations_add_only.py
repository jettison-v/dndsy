"""A standing rule (Brett's picks, Nov 19, Work Flow, Sized to Grow › At every level: "Database changes only add;
removals come later"): a new migration's upgrade() only adds. Then the code before it still runs on the database after
it, so undoing a bad deploy is safe (docs/undo.md). Taking something away (a column, a table, a rename, a type) comes in
a later change, once no released code uses it, and says so on the line: `# removal: <the revision that stopped using it>`.
Migrations before this rule (dated before 2026_12_08) are as they were."""

import re
from pathlib import Path

VERSIONS = Path(__file__).resolve().parent.parent / "migrations" / "versions"
SINCE = "2026_12_08"
TAKES_AWAY = re.compile(r"op\.(drop_column|drop_table|rename_table)\(|op\.alter_column\([^)]*(new_column_name|type_)\s*=")


def _upgrade(text: str) -> str:
    start = text.find("def upgrade(")
    end = text.find("def downgrade(", start)
    return text[start:end] if start >= 0 else ""


def test_a_standing_rule_new_migrations_only_add():
    bad = []
    for f in sorted(VERSIONS.glob("*.py")):
        if f.name[: len(SINCE)] < SINCE:
            continue
        for line in _upgrade(f.read_text()).splitlines():
            if TAKES_AWAY.search(line) and "# removal:" not in line:
                bad.append(f"{f.name}: {line.strip()}")
    assert not bad, "A migration takes something away in the same change (removals come later, marked # removal:):\n" + "\n".join(bad)


def test_the_rule_catches_a_removal():
    assert TAKES_AWAY.search('op.drop_column("fft_areas", "lane")')
    assert TAKES_AWAY.search('op.alter_column("fft_areas", "lane", type_=sa.String(20))')
    assert TAKES_AWAY.search('op.alter_column("x", "a", new_column_name="b")')
    assert not TAKES_AWAY.search('op.add_column("fft_areas", sa.Column("lane", sa.String(10)))')
    assert not TAKES_AWAY.search('op.alter_column("x", "a", server_default="")')
