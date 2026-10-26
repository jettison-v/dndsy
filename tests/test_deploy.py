"""Deploying (docs/SETUP_LOG.md, 2026-10-24): the nightly backup service rebuilds only when a file it runs changes
(deploy_check.BACKUP_WATCH, its Railway watch paths), and scripts/deploy_check.py retries Railway's own build-machine
errors."""

import importlib.util
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _deploy_check():
    spec = importlib.util.spec_from_file_location("deploy_check", ROOT / "scripts" / "deploy_check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_backup_service_rebuilds_when_anything_it_runs_changes():
    """Every app module the backup script loads is on the watch list, so a change to one rebuilds the backup service
    (a new column in app/models.py must reach the nightly backup)."""
    watched = set(_deploy_check().BACKUP_WATCH)
    code = ("import importlib.util, sys; sys.argv = ['x', '--help']; s = importlib.util.spec_from_file_location('b', 'scripts/backup_db.py');"
            "m = importlib.util.module_from_spec(s)\ntry: s.loader.exec_module(m)\nexcept SystemExit: pass\n"
            "print('\\n'.join(sorted(v.__file__ for k, v in sys.modules.items() if (k == 'app' or k.startswith('app.')) and getattr(v, '__file__', None))))")
    loaded = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    missing = [str(Path(f).relative_to(ROOT)) for f in loaded if str(Path(f).relative_to(ROOT)) not in watched]
    assert not missing, f"Add to BACKUP_WATCH in scripts/deploy_check.py, then run it with --set-backup-watch: {missing}"


def test_only_railways_own_build_errors_are_retried():
    check = _deploy_check()
    assert check.railway_glitch('Build Failed: build daemon returned an error < listing workers for Build: failed to list workers >')
    assert check.railway_glitch("Build Failed: build daemon returned an error < failed to solve: frontend grpc server closed unexpectedly >")
    assert check.railway_glitch("🚂 All aboard, next stop: builder v4")  # a build that never started
    assert not check.railway_glitch("error: Failed to install: pillow==99 not found")  # our own mistake: no retry
    assert not check.railway_glitch("sqlalchemy.exc.ProgrammingError: column users.dice does not exist")


def test_a_railway_glitch_is_built_again_and_our_own_failure_is_not(monkeypatch):
    check = _deploy_check()
    monkeypatch.setattr(check.time, "sleep", lambda s: None)
    monkeypatch.setattr(check, "say", lambda text: None)
    meta = {"commitHash": "abc1234def"}
    history = [[{"id": "d1", "status": "FAILED", "createdAt": "2026-10-24T01:00:00Z", "meta": meta}]]
    calls = []

    def run(*cmd, check=True):
        calls.append(cmd[:3])
        if cmd[:3] == ("railway", "redeploy", "--service"):  # the retry builds again and succeeds
            history.append(history[-1] + [{"id": "d2", "status": "SUCCESS", "createdAt": "2026-10-24T01:05:00Z", "meta": meta}])
        if cmd[:3] == ("railway", "logs", "--build"):
            return "Build Failed: build daemon returned an error < failed to list workers >" if cmd[3] == "d1" else ""
        return ""

    monkeypatch.setattr(check, "run", run)
    monkeypatch.setattr(check, "deployments", lambda service: history[-1])
    assert check.follow("askdnd-v2", "abc1234", appear=60)
    assert ("railway", "redeploy", "--service") in calls
    # Our own failure (a missing package): no retry, and it reports failure
    calls.clear()
    history[:] = [[{"id": "d3", "status": "FAILED", "createdAt": "2026-10-24T02:00:00Z", "meta": meta}]]
    monkeypatch.setattr(check, "run", lambda *cmd, check=True: (calls.append(cmd[:3]), "error: No solution found for pillow==99")[1])
    assert not check.follow("askdnd-v2", "abc1234", appear=60)
    assert ("railway", "redeploy", "--service") not in calls


def test_beta_gets_a_moment_to_switch_over(monkeypatch):
    """Right after a deploy, beta can miss once while the new copy takes over; that isn't "beta is down"."""
    import urllib.request

    answers = iter([OSError("switching over"), OSError("still switching"), 200])

    class Page:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def urlopen(req, timeout):
        got = next(answers)
        if isinstance(got, Exception):
            raise got
        return Page()

    deploy_check = _deploy_check()
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(deploy_check.time, "sleep", lambda s: None)
    assert deploy_check.beta_answers()
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: (_ for _ in ()).throw(OSError("down")))
    assert not deploy_check.beta_answers(tries=3)


def test_the_browser_tests_image_matches_playwright():
    """The browser tests run in Playwright's image (.github/workflows/tests.yml), whose Chromium fits one Playwright
    version: upgrading Playwright in uv.lock means moving the image's tag with it."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    lock = re.search(r'name = "playwright"\nversion = "([\d.]+)"', (root / "uv.lock").read_text()).group(1)
    image = re.search(r"mcr\.microsoft\.com/playwright/python:v([\d.]+)-", (root / ".github/workflows/tests.yml").read_text()).group(1)
    assert image == lock, f"tests.yml uses Playwright's v{image} image but uv.lock has Playwright {lock}"
