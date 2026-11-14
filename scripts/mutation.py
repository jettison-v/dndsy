"""Mutation testing on one module of core logic (foundations F8, docs/plans/2026-11-13-engineering-practices.md).

    uv run python scripts/mutation.py access        # app/access.py
    uv run python scripts/mutation.py roll_plan     # app/roll_plan.py

mutmut puts small deliberate bugs into the module, one at a time (a > made >=, a True made False, a key renamed), and
runs the tests that reach it; each bug the tests don't notice "survived": a missing test, or a change nobody could see
(wording, which the tests don't pin on purpose: CLAUDE.md, markers not text). It lists the survivors with what changed.
Slow (minutes to an hour a module): run it by hand on the module you're changing, never in CI. Its working copy is
mutants/ (ignored by git). Never reports to Sentry or uses the local copy of beta.
"""

import os
import subprocess
import sys

CORE = ("access", "roll_plan", "hit_points", "rules_book", "measure", "areas", "fog", "coins", "initiative", "conditions", "death_saves")


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in CORE:
        print(f"Which module? One of: {', '.join(CORE)}")
        return 2
    module = sys.argv[1]
    # (OBJC_DISABLE_INITIALIZE_FORK_SAFETY: macOS aborts a forked test process that touches its own system libraries,
    # which crashed 54 runs; mutmut forks one per bug)
    env = {**os.environ, "SENTRY_DSN": "", "OBJC_DISABLE_INITIALIZE_FORK_SAFETY": "YES", "TEST_DATABASE_URL": os.environ.get("TEST_DATABASE_URL", "postgresql+psycopg://localhost/askdnd_test_mutation")}
    subprocess.run(["uv", "run", "mutmut", "run", "--max-children", "4", f"app.{module}.*"], env=env, check=False)
    out = subprocess.run(["uv", "run", "mutmut", "results"], env=env, capture_output=True, text=True).stdout
    survived = [line.split(":")[0].strip() for line in out.splitlines() if line.strip().endswith("survived") and f"app.{module}." in line]
    print(f"\n{len(survived)} survived in app/{module}.py")
    for name in survived:
        diff = subprocess.run(["uv", "run", "mutmut", "show", name], env=env, capture_output=True, text=True).stdout
        changed = [d for d in diff.splitlines() if d.startswith(("+ ", "- "))]
        print(f"  {name}\n    " + "\n    ".join(changed[:4]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
