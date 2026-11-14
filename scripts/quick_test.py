"""A quick local pass: only the tests that run the code this branch changed (Brett, Nov 13: development faster).

    uv run python scripts/quick_test.py            # what changed since origin/main, committed or not
    uv run python scripts/quick_test.py --list     # which tests it would run, and why
    uv run python scripts/quick_test.py --map      # record which tests run which file (the server suite, a few minutes)

The record (private/test-map.json, on this computer only) is made by running the server suite once with coverage noting
which test ran each line; a changed file in app/ then runs exactly the tests that ran it. Import chains can't narrow it
here (everything uses the models, which use measuring), so the record is the only precise way. A changed test runs
itself; a changed template, stylesheet or app.js runs the layout checks, the links and the tests that name it (not the
browser flows: GitHub runs those); shared test setup or the
project's settings run everything. Seconds instead of the whole suite's minutes while you work. It is not the check:
GitHub runs everything on every push, and nothing merges until that is green.
"""

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
MAP = ROOT / "private" / "test-map.json"
OLD = 3 * 86400  # (a record older than three days is made again first: new tests, moved code)
LOOKS = ["tests/browser/test_layout.py", "tests/test_links.py"]  # (a template's or a stylesheet's change: every page's look and links)
EVERYTHING = ("conftest.py", "tests/table_setup.py", "pyproject.toml", "uv.lock")


def changed() -> list[str]:
    git = lambda *a: subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    files = git("diff", "--name-only", "origin/main...HEAD") + git("diff", "--name-only", "HEAD")
    files += git("ls-files", "--others", "--exclude-standard")
    return sorted(set(files))  # (a deleted file too: the tests that ran it should still run)


def make_map() -> None:
    """Run the server suite once with each test's name on the lines it ran, and keep, per app file, the tests."""
    from coverage import CoverageData

    data_file = ROOT / "private" / ".coverage-map"
    data_file.parent.mkdir(exist_ok=True)
    env = {**os.environ, "COVERAGE_FILE": str(data_file)}
    data_file.unlink(missing_ok=True)
    run = subprocess.run(["uv", "run", "pytest", "-q", "-n", "auto", "--ignore=tests/browser", "-p", "no:randomly",
                          "--cov=app", "--cov-context=test", "--cov-report="], cwd=ROOT, env=env, check=False)
    if run.returncode != 0 or not data_file.exists():  # (a run that failed partway would leave a record trusted for days)
        sys.exit("The server suite didn't pass, so no record was made: fix it, or run the whole suite.")
    data = CoverageData(str(data_file))
    data.read()
    out: dict[str, list[str]] = {}
    for f in data.measured_files():
        rel = str(Path(f).resolve().relative_to(ROOT)) if Path(f).is_absolute() else f
        tests = {c.split("::")[0] for ctxs in data.contexts_by_lineno(f).values() for c in ctxs if "::" in c}
        out[rel] = sorted(tests)
    MAP.write_text(json.dumps(out, indent=0))
    print(f"Recorded which tests run each of {len(out)} files: {MAP}")


def tests_for(files: list[str], record: dict[str, list[str]]) -> dict[str, list[str]]:
    """Each test file to run, with the changed files that brought it in."""
    sources = {str(p.relative_to(ROOT)): p.read_text(errors="ignore") for p in TESTS.rglob("test_*.py")}
    picked: dict[str, list[str]] = {}
    add = lambda test, why: picked.setdefault(test, []).append(why)
    for f in files:
        path = Path(f)
        if f.startswith("tests/") and path.name.startswith("test_") and path.suffix == ".py":
            if (ROOT / f).exists():
                add(f, f)
        elif f.startswith("app/") and path.suffix == ".py":
            for test in record.get(f, []):
                add(test, f)
            if f not in record:  # (a new file: nothing has run it yet, so the tests that import it by name)
                for test, text in sources.items():
                    if re.search(rf"\b{re.escape(path.stem)}\b", text):
                        add(test, f)
        elif f.startswith(("app/templates/", "app/static/", "scripts/")):
            for look in LOOKS if not f.startswith("scripts/") else []:
                add(look, f)
            stem = path.name if not f.startswith("scripts/") else path.stem
            for test, text in sources.items():
                if re.search(rf"\b{re.escape(stem)}\b", text):
                    add(test, f)
    return picked


def main() -> int:
    if "--map" in sys.argv:
        make_map()
        return 0
    files = changed()
    if any(f.endswith(EVERYTHING) for f in files):
        print("Shared test setup or the project's settings changed: run the whole suite (uv run pytest -q).")
        return 0
    if not MAP.exists() or time.time() - MAP.stat().st_mtime > OLD:
        print("Recording which tests run which file first (a few minutes, then it's quick for three days)…")
        make_map()
    picked = tests_for(files, json.loads(MAP.read_text()))
    if "--list" in sys.argv:
        for test, why in sorted(picked.items()):
            print(f"{test}  <- {', '.join(sorted(set(why)))}")
        return 0
    if not picked:
        print(f"No tests run what changed ({len(files)} files: docs or the like). GitHub still runs everything.")
        return 0
    print(f"{len(picked)} test files run the {len(files)} changed files (the whole suite runs on GitHub):")
    return subprocess.run(["uv", "run", "pytest", "-q", "-n", "auto", *sorted(picked)], cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
