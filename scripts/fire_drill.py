"""The fire drill (Brett, Nov 13: check the foundations as a whole): one deliberate break for each kind of harm in
What robust means (docs/plans/2026-11-13-engineering-practices.md), each confirmed caught by the check that's meant to.

    uv run python scripts/fire_drill.py              # every break, one at a time (about 15 minutes)
    uv run python scripts/fire_drill.py access link  # only these

For each break: the check runs clean first (so a failure means the break, not something already broken), the break is
written into the file, the check runs again and must fail, and the file is put back whatever happens. A break that stays
green is a hole in the foundations: the report says which. Run it again after changing a check or the way tests run.
Never commits anything; run it on a clean checkout of main.
"""

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ["uv", "run", "pytest", "-q", "-p", "no:randomly", "-x"]
LINT = "tools/lint/node_modules/.bin/"


@dataclass
class Break:
    key: str
    harm: str           # the line of What robust means it stands for
    what: str           # the break, in plain words
    file: str
    old: str            # the text replaced ("" appends `new` to the file)
    new: str
    check: list[str]    # must pass clean and fail with the break
    caught_by: str


AT = "@"  # (written apart, so the drill's own source has no address-like text: tests/test_public_safe.py)
ROUTE = '\n\n' + AT + 'router.post("/drill-unguarded")\ndef drill_unguarded():\n    return {}\n'
ASYNC = '\n\n' + AT + 'router.get("/drill-async")\nasync def drill_async(db: Session = Depends(get_db)):\n    return {}\n'
VISUAL = ["bash", "-c", "uv run python scripts/visual_compare.py | tee /dev/stderr | grep -qE '^[1-9][0-9]* of [0-9]+ pictures changed' && exit 1 || exit 0"]

BREAKS = [
    Break("access", "A bug in what already worked (security)", "a player may change someone else's character",
          "app/picks.py", "    return bool(me and character.owner_id == me.id)", "    return bool(me)",
          PY + ["-n", "auto", "tests/test_refusals.py"], "every route asked by the wrong person (test_refusals)"),
    Break("same-site", "A bug in what already worked (security)", "a change from another website is accepted",
          "app/same_site.py", '    """Whether a change made with the sign-in cookie came from a page that isn\'t askdnd\'s."""',
          '    """Whether a change made with the sign-in cookie came from a page that isn\'t askdnd\'s."""\n    return False',
          PY + ["tests/test_same_site.py"], "the cross-site check's tests"),
    Break("hidden", "A bug in what already worked (privacy)", "a hidden World entry shows up in a player's Search",
          "app/search.py", "            continue  # (hidden is as if it didn't exist: CLAUDE.md › Privacy)", "            pass",
          PY + ["tests/test_search.py"], "Search's tests"),
    Break("unguarded", "A workflow left incomplete", "a new route that changes something, with no feature and no refusal check",
          "app/dice.py", "", ROUTE, PY + ["-n", "auto", "tests/test_usage.py", "tests/test_refusals.py"],
          "every action route has a feature and is asked by the wrong person"),
    Break("async-db", "A bug in what already worked", "a route that holds the event loop while it waits for the database",
          "app/dice.py", "", ASYNC, PY + ["tests/test_event_loop.py"], "test_event_loop"),
    Break("link", "A workflow left incomplete", "a link to a page that doesn't exist, in the menu bar",
          "app/templates/base.html", "{% block content %}{% endblock %}", "<a href=\"/drill-nowhere\" hidden>drill</a>{% block content %}{% endblock %}",
          PY + ["-n", "auto", "tests/test_links.py"], "every link on every page followed (test_links)"),
    Break("words", "A bug in the tests themselves", "app.js deciding by a button's words",
          "app/static/app.js", "", "\ndocument.querySelectorAll('button').forEach(b => { if (b.textContent === 'Roll') b.dataset.drill = '1'; });\n",
          PY + ["tests/test_no_text_refs.py"], "the markers-not-text ratchet (test_no_text_refs)"),
    Break("clock", "A bug in what already worked", "a date taken from the server's clock (UTC) instead of the table's",
          "app/config.py", "", "\n\ndef _drill_today():\n    from datetime import date\n    return date.today()\n",
          ["uv", "run", "ruff", "check", "app"], "ruff's date rule"),
    Break("button", "A bug in what already worked", "a button with no type inside a form (it would submit it)",
          "app/templates/base.html", "{% block content %}{% endblock %}", "<form><button>drill</button></form>{% block content %}{% endblock %}",
          ["uv", "run", "djlint", "app/templates", "--lint"], "djLint"),
    Break("shadow", "A bug in what already worked", "a name in app.js hiding another (toast)",
          "app/static/app.js", "  function toast(message, action, kind) {",
          "  function drillShadow() { const toast = 1; return toast; }\n  function toast(message, action, kind) {",
          [LINT + "eslint", "-c", "tools/lint/eslint.config.mjs", "app/static"], "ESLint"),
    Break("email", "A bug in what already worked (privacy)", "a real-looking email address committed to the public repo",
          "docs/DECISIONS.md", "", "\n- 2026-11-13: drill: write to someone.at.the.table" + AT + "gmail.com\n",
          PY + ["tests/test_public_safe.py"], "test_public_safe"),
    Break("phone", "The UI or UX quietly getting worse", "the menu bar too wide for a phone",
          "app/static/app.css", "", "\n.topbar { min-width: 640px; }\n",
          PY + ["-n", "4", "tests/browser/test_layout.py"], "the layout checks at every width (test_layout)"),
    Break("page-error", "A bug in what already worked", "a JavaScript error on every page",
          "app/static/app.js", "", "\ndocument.addEventListener('DOMContentLoaded', () => { const drill = null; drill.boom(); });\n",
          PY + ["-n", "4", "tests/browser/test_layout.py"], "every browser test failing on a page error it didn't expect"),
    Break("moved", "The UI or UX quietly getting worse", "Battle, Sheet and Plan's tabs nudged 24px to the right",
          "app/static/app.css", "", "\n.char-head { margin-left: 24px; }\n", VISUAL, "the before-and-after pictures (visual_compare)"),
]


def run(cmd: list[str]) -> bool:
    return subprocess.run(cmd, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def drill(b: Break) -> str:
    path = ROOT / b.file
    original = path.read_text()
    if b.old and original.count(b.old) != 1:
        return f"SKIPPED: its anchor isn't in {b.file} once (the drill needs updating)"
    if not run(b.check):
        return "SKIPPED: the check fails before the break (fix that first)"
    try:
        path.write_text(original.replace(b.old, b.new, 1) if b.old else original + b.new)
        caught = not run(b.check)
    finally:
        path.write_text(original)
    return f"caught by {b.caught_by}" if caught else "NOT CAUGHT: a hole in the foundations"


def main() -> int:
    if subprocess.run(["git", "status", "--porcelain", "app", "docs"], cwd=ROOT, capture_output=True, text=True).stdout.strip():
        print("app/ or docs/ has changes; run the drill on a clean checkout so it puts back exactly what it found.")
        return 2
    wanted = set(sys.argv[1:])
    holes = 0
    for b in BREAKS:
        if wanted and b.key not in wanted:
            continue
        result = drill(b)
        holes += result.startswith(("NOT", "SKIPPED"))
        print(f"{b.key:11} {b.what}: {result}", flush=True)
    print(f"\n{'Every break was caught.' if not holes else f'{holes} not caught or skipped: see above.'}")
    return 1 if holes else 0


if __name__ == "__main__":
    sys.exit(main())
