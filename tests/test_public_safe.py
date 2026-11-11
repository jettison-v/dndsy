"""A standing rule (Brett, Nov 9: the repository is public while askdnd is built quickly; CLAUDE.md › Treat the repo as
public): nothing committed may hold the books' words, the players' writing, an email address or the table's real names.

- The party's saved D&D Beyond sheets are committed only locked (tests/fixtures/ddb.locked, scripts/fixtures.py).
- No committed file holds D&D Beyond's rules definitions (their book text comes with them).
- Email addresses only at example.com or askdnd.ai (and git's own no-reply ones).
- The table's real surnames never appear: they're listed here only as fingerprints (sha256), so this file doesn't
  publish them either.
"""

import hashlib
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT = (".py", ".html", ".md", ".json", ".js", ".css", ".txt", ".toml", ".yml", ".yaml", ".sh", ".plist", ".example", ".cfg", ".ini")
# sha256 of the lowercased surnames of the people at the table (Nov 9)
NAMES = {"295fc59afcff06529d3c19e0148d1b2bd701a9af719e94a7df4c634038ae1deb", "fc4fe1af2b46813efc38e648f02a24edc639c0ae14d0214fec1335445728c383"}
# Not addresses of anyone: a form's hint, a made-up Sentry key, a database URL in a test
PLACEHOLDERS = {"name@gmail.com", "key@o0.ingest.sentry.io", "x@postgres.railway.internal"}
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}")
OK_MAIL = re.compile(r"@(?:[a-z0-9.-]*\.)?(?:example\.(?:com|org|net)|askdnd\.ai|users\.noreply\.github\.com|anthropic\.com|[xy]\.com)$", re.I)


def tracked() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / f for f in out if f.endswith(TEXT) and (ROOT / f).is_file()]


def test_the_saved_sheets_are_committed_only_locked():
    files = subprocess.run(["git", "ls-files", "tests/fixtures"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    assert "tests/fixtures/ddb.locked" in files
    assert not [f for f in files if f.startswith("tests/fixtures/ddb/")], "A readable saved sheet is committed: lock it (scripts/fixtures.py lock)"


def test_no_committed_file_holds_d_and_d_beyond_rules_definitions():
    """A D&D Beyond definition carries the book's words ("description", "snippet"); none may be committed."""
    found = []
    for f in tracked():
        text = f.read_text(errors="ignore")
        if text.count('"definitionKey"') + text.count('"snippet":') > 2:
            found.append(str(f.relative_to(ROOT)))
    assert found == [], found


def test_no_email_addresses_but_example_ones():
    found = set()
    for f in tracked():
        if "app/static/vendor/" in f.as_posix():  # (a library's own author's address, as its package publishes it)
            continue
        for m in EMAIL.finditer(f.read_text(errors="ignore")):
            if not OK_MAIL.search(m.group(0)) and not re.search(r"\.(png|jpe?g|svg|webp|gif)$", m.group(0)) and "@3d-dice" not in m.group(0) \
                    and m.group(0) not in PLACEHOLDERS:
                found.add((str(f.relative_to(ROOT)), m.group(0)))
    assert found == set(), sorted(found)


def test_the_tables_real_names_are_nowhere():
    found = set()
    for f in tracked():
        for word in set(re.findall(r"[a-z]+", f.read_text(errors="ignore").lower())):
            if hashlib.sha256(word.encode()).hexdigest() in NAMES:
                found.add(str(f.relative_to(ROOT)))
    assert found == set(), f"A real name is in {sorted(found)}: use a role (the DM, Cole's player) or a made-up name"
