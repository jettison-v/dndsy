"""The party's saved D&D Beyond sheets, locked (Brett, Nov 9: the repository goes public; the sheets carry the books'
words, which aren't ours to publish). The readable copies (tests/fixtures/ddb/*.json) are never committed (.gitignore);
the repository holds one encrypted file, tests/fixtures/ddb.locked, that only FIXTURES_KEY opens: in .env here, a GitHub
Actions secret for the checks.

    uv run python scripts/fixtures.py unlock    # writes tests/fixtures/ddb/*.json from the locked file (the tests do it themselves)
    uv run python scripts/fixtures.py lock      # after a sheet is saved again (scripts/ddb_fixture.py): seals them into the locked file

The tests unlock on their own when the readable copies are missing (tests/conftest.py, before anything reads them).
"""

import gzip
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDER = ROOT / "tests" / "fixtures" / "ddb"
LOCKED = ROOT / "tests" / "fixtures" / "ddb.locked"


class NoKey(RuntimeError):
    pass


def key() -> bytes:
    """FIXTURES_KEY from the environment, else from .env (the tests don't load .env themselves)."""
    k = os.getenv("FIXTURES_KEY", "").strip()
    env = ROOT / ".env"
    if not k and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("FIXTURES_KEY="):
                k = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not k:
        raise NoKey("FIXTURES_KEY isn't set: the saved sheets stay locked (put it in .env, or the Actions secret).")
    return k.encode()


def lock() -> int:
    from cryptography.fernet import Fernet

    files = {f.name: f.read_text() for f in sorted(FOLDER.glob("*.json"))}
    if not files:
        raise SystemExit(f"Nothing to lock in {FOLDER}")
    LOCKED.write_bytes(Fernet(key()).encrypt(gzip.compress(json.dumps(files, sort_keys=True).encode(), mtime=0)))
    return len(files)


def unlock(quiet: bool = False) -> int:
    """Write the readable copies from the locked file (only those missing or different)."""
    from cryptography.fernet import Fernet

    files = json.loads(gzip.decompress(Fernet(key()).decrypt(LOCKED.read_bytes())))
    FOLDER.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        out = FOLDER / name
        if not out.exists() or out.read_text() != text:
            out.write_text(text)
    if not quiet:
        print(f"Unlocked {len(files)} saved sheets into {FOLDER.relative_to(ROOT)}")
    return len(files)


def ready() -> None:
    """For scripts and the tests: unlock if the readable copies aren't there yet."""
    if not any(FOLDER.glob("*.json")) and LOCKED.exists():
        unlock(quiet=True)


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else ""
    if what == "lock":
        print(f"Locked {lock()} saved sheets into {LOCKED.relative_to(ROOT)}")
    elif what == "unlock":
        unlock()
    else:
        raise SystemExit(__doc__)
