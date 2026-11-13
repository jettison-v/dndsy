"""Follow a merge to beta, and retry Railway's own build-machine errors (docs/SETUP_LOG.md, 2026-10-24).

    uv run python scripts/deploy_check.py            # the newest commit on main
    uv run python scripts/deploy_check.py --sha abc1234
    uv run python scripts/deploy_check.py --set-backup-watch   # after changing BACKUP_WATCH below
    uv run python scripts/deploy_check.py --set-app-watch      # after changing APP_WATCH below

1. Waits for GitHub's tests on that commit (Railway waits for them too).
2. Waits for each Railway service to deploy it. The backup service only rebuilds when a file it runs changed
   (BACKUP_WATCH, its Railway watch paths), so it may be skipped.
3. If a build failed because of Railway itself ("build daemon returned an error", the build machine dropping the
   connection), builds it again from source, up to twice. Any other failure is ours: it prints the end of the log
   and stops. Beta keeps running the previous version either way.
4. Checks beta answers (a miss right after a switchover is tried again for about a minute and a half), and, when the
   app was deployed, that beta runs this commit (/health's version): Railway calls a deploy done a moment before the new
   copy takes over, and the Mac Mini's after-deploy check starts when the version changes.

Needs the GitHub (`gh`) and Railway (`railway`) CLIs, signed in. Prints no secrets.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

SERVICES = ["askdnd-v2", "askdnd-backup"]
# The backup service's watch paths: it rebuilds only when one of these changes. Every app module the backup script loads
# must be here (tests/test_deploy.py checks), so a new column in app/models.py still reaches the nightly backup.
# Railway keeps this list in the service's settings; --set-backup-watch copies it there. (Railway's config files are
# deprecated, and its replacement manages the whole project, the legacy service included, so we set just this.)
BACKUP_WATCH = ["scripts/backup_db.py", "app/__init__.py", "app/backup.py", "app/books.py", "app/config.py", "app/db.py", "app/errors.py",
                "app/files.py", "app/history.py", "app/models.py", "pyproject.toml", "uv.lock", ".python-version"]
# The app's watch paths: what beta runs. A merge that changes only what's left out (docs, tests, the workflow, notes)
# doesn't rebuild beta (Brett, Nov 4: each deploy costs). tests/test_deploy.py checks every file in git is in one list
# or the other, so something new the app needs can't be left out by accident. --set-app-watch copies it to Railway.
APP_WATCH = ["app/**", "migrations/**", "scripts/**", "extension/**", "transcript_filter/**", "pyproject.toml", "uv.lock",
             ".python-version", "Procfile", "alembic.ini"]
NOT_RUN = ["docs/", "tests/", ".github/", ".claude/", "CLAUDE.md", "README.md", ".gitignore", ".gitattributes", ".env.example"]
BETA = "https://beta.askdnd.ai/login"
DONE = {"SUCCESS", "SLEEPING", "FAILED", "CRASHED", "REMOVED", "SKIPPED"}
# Railway's build machines failing, not our code: worth building again
GLITCH = re.compile(r"build daemon returned an error|failed to solve: frontend grpc|buildkitd\.sock|failed to list workers"
                    r"|error reading server preface|context deadline exceeded", re.I)


def railway_glitch(log: str) -> bool:
    """A known build-machine error, or a build that never started: the log ends at Railway's own banner, before any
    step of ours ran (2026-10-26, the deploy after the repo went private; a fresh build passed)."""
    lines = [x for x in (log or "").splitlines() if x.strip()]
    return bool(GLITCH.search(log or "")) or (len(lines) <= 2 and all("All aboard" in x or "builder" in x for x in lines))


def run(*cmd: str, check: bool = True) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True)
    if check and out.returncode != 0:
        sys.exit(f"{' '.join(cmd[:3])} failed: {out.stderr.strip()[:300]}")
    return out.stdout


def say(text: str) -> None:
    print(f"[{datetime.now().astimezone():%H:%M:%S}] {text}", flush=True)


def deployments(service: str) -> list[dict]:
    try:
        return json.loads(run("railway", "deployment", "list", "--service", service, "--json", check=False) or "[]")
    except json.JSONDecodeError:
        return []


def for_commit(service: str, sha: str, after: str = "") -> dict | None:
    """The newest deploy of this commit (created after `after`, when given)."""
    mine = [d for d in deployments(service) if (d.get("meta") or {}).get("commitHash", "").startswith(sha) and d["createdAt"] > after]
    return max(mine, key=lambda d: d["createdAt"]) if mine else None


def wait_ci(sha: str) -> None:
    say(f"Waiting for GitHub's tests on {sha[:7]}…")
    for _ in range(60):
        # Only the tests' workflow: Dependabot's "Graph Update" also runs on main's commits
        runs = json.loads(run("gh", "run", "list", "--workflow", "tests.yml", "--branch", "main", "--limit", "10",
                              "--json", "headSha,databaseId,status,conclusion"))
        match = next((r for r in runs if r["headSha"].startswith(sha)), None)
        if match:
            while match["status"] != "completed":  # (`gh run watch` can stop early: only the run's own status counts)
                subprocess.run(["gh", "run", "watch", str(match["databaseId"]), "--exit-status"], capture_output=True)
                time.sleep(10)
                match = json.loads(run("gh", "run", "view", str(match["databaseId"]), "--json", "databaseId,status,conclusion"))
            if match["conclusion"] != "success":
                sys.exit(f"GitHub's tests didn't pass ({match['conclusion']}): Railway won't deploy {sha[:7]}. Fix the tests first.")
            say("Tests passed.")
            return
        time.sleep(10)
    sys.exit("No GitHub test run for that commit after 10 minutes.")


def wait_deploy(service: str, sha: str, after: str = "", appear: int = 600) -> dict | None:
    """Wait for this service's deploy of `sha` to finish; None if none started within `appear` seconds."""
    start = time.time()
    while time.time() - start < 1800:
        d = for_commit(service, sha, after)
        if d is None and time.time() - start > appear:
            return None
        if d is not None and d["status"] in DONE:
            return d
        time.sleep(10)
    sys.exit(f"{service}: still deploying after 30 minutes; look at the Railway dashboard.")


def last_built(service: str) -> str:
    """The commit of the service's newest successful deploy (what it runs now), or ""."""
    ok = [d for d in deployments(service) if d.get("status") in ("SUCCESS", "SLEEPING", "REMOVED") and (d.get("meta") or {}).get("commitHash")]
    return max(ok, key=lambda d: d["createdAt"])["meta"]["commitHash"] if ok else ""


def changes_what_it_runs(service: str, sha: str) -> bool:
    """Whether anything since the commit the service last deployed changes a file its watch paths cover (what Railway
    builds it for). Since its last deploy, not just this commit: Nov 10, PR 306's merge run failed a flaky test, the
    fix after it changed only a test, and Railway skipped it, so 306 never reached prod until built from source."""
    watch = APP_WATCH if service == SERVICES[0] else BACKUP_WATCH
    base = last_built(service)
    if not base or subprocess.run(["git", "cat-file", "-e", f"{base}^{{commit}}"], capture_output=True).returncode:
        base = f"{sha}~1"
    changed = run("git", "diff", "--name-only", base, sha, check=False).split()
    return any(f == w or (w.endswith("/**") and f.startswith(w[:-2])) for f in changed for w in watch)


def follow(service: str, sha: str, appear: int) -> bool:
    d = wait_deploy(service, sha, appear=appear)
    if d is None:
        say(f"{service}: no deploy for this commit (nothing it runs changed).")
        return True
    rebuilt = False
    for attempt in range(3):
        if d["status"] == "SKIPPED":
            if rebuilt or not changes_what_it_runs(service, sha):
                say(f"{service}: skipped (nothing it runs changed).")
                return True
            # (Railway also skips a commit whose tests failed when it was pushed, and doesn't go back when a rerun
            # passes: Nov 7, PR 261 never reached prod until it was built from source)
            say(f"{service}: Railway skipped it, though it changes what {service} runs (its tests failed at first?). Building it from source…")
            run("railway", "redeploy", "--service", service, "--from-source", "-y", check=False)
            rebuilt = True
            d = wait_deploy(service, sha, after=d["createdAt"], appear=300) or d
            if d["status"] == "SKIPPED":
                say(f"{service}: still not built. Build it on Railway: its service › Deployments › Redeploy.")
                return False
            continue
        if d["status"] in ("SUCCESS", "SLEEPING", "REMOVED"):
            say(f"{service}: deployed ({d['status'].lower()}).")
            return True
        log = run("railway", "logs", "--build", d["id"], check=False)[-4000:]
        if not railway_glitch(log) or attempt == 2:
            if not railway_glitch(log):
                log += run("railway", "logs", "--deployment", d["id"], check=False)[-3000:]
            say(f"{service}: {d['status']}. " + ("Railway's build machines failed three times; try again later." if railway_glitch(log)
                                                 else "This looks like our problem, not Railway's. The end of the log:"))
            print("\n".join(line for line in log.splitlines()[-25:] if "password" not in line.lower()))
            return False
        say(f"{service}: Railway's build machine failed (not our code). Building again from source ({attempt + 1} of 2)…")
        run("railway", "redeploy", "--service", service, "--from-source", "-y", check=False)
        d = wait_deploy(service, sha, after=d["createdAt"], appear=300) or d
    return False


def set_watch(name: str, patterns: list[str]) -> None:
    """Copy a watch list to a service's settings on Railway (signed in with the Railway CLI's login)."""
    status = json.loads(run("railway", "status", "--json"))
    env = next(e["node"]["id"] for e in status["environments"]["edges"] if e["node"]["name"] == "production")
    service = next(e["node"]["id"] for e in status["services"]["edges"] if e["node"]["name"] == name)
    user = json.load(open(os.path.expanduser("~/.railway/config.json")))["user"]

    def gql(query: str, variables: dict) -> dict:
        req = urllib.request.Request("https://backboard.railway.com/graphql/v2", json.dumps({"query": query, "variables": variables}).encode(),
                                     {"Authorization": "Bearer " + (user.get("accessToken") or user["token"]),
                                      "Content-Type": "application/json", "User-Agent": "askdnd-deploy-check"})
        return json.load(urllib.request.urlopen(req, timeout=30))

    ids = {"s": service, "e": env}
    out = gql("mutation($s:String!,$e:String!,$i:ServiceInstanceUpdateInput!){serviceInstanceUpdate(serviceId:$s,environmentId:$e,input:$i)}",
              {**ids, "i": {"watchPatterns": patterns}})
    if out.get("errors"):
        sys.exit(f"Railway refused: {out['errors'][0]['message']}")
    now = gql("query($s:String!,$e:String!){serviceInstance(serviceId:$s,environmentId:$e){watchPatterns}}", ids)
    say(f"{name} rebuilds only when these change: {', '.join(now['data']['serviceInstance']['watchPatterns'])}")


def beta_answers(tries: int = 6, wait: float = 15) -> bool:
    """Beta's sign-in page loads. Railway marks a deploy done a moment before the new copy takes over, so a miss is
    tried again (for about a minute and a half) before it counts."""
    for attempt in range(tries):
        try:
            # Cloudflare turns away Python's default user agent
            req = urllib.request.Request(f"{BETA}?check={int(time.time())}", headers={"User-Agent": "askdnd-deploy-check"})
            with urllib.request.urlopen(req, timeout=20) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        if attempt < tries - 1:
            time.sleep(wait)
    return False


def version(tries: int = 12, wait: float = 10, want: str = "") -> str:
    """The commit beta runs (its /health), waiting up to two minutes for `want`."""
    got = ""
    for attempt in range(tries):
        try:
            req = urllib.request.Request(f"{BETA.removesuffix('/login')}/health?check={int(time.time())}", headers={"User-Agent": "askdnd-deploy-check"})
            with urllib.request.urlopen(req, timeout=20) as r:
                got = json.load(r).get("version", "")
        except Exception:
            pass
        if not want or (got and (want.startswith(got) or got.startswith(want))):  # (either may be the short form)
            return got
        if attempt < tries - 1:
            time.sleep(wait)
    return got


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--sha", help="the commit to follow (default: the newest on main)")
    p.add_argument("--no-ci", action="store_true", help="don't wait for GitHub's tests")
    p.add_argument("--set-backup-watch", action="store_true", help="copy BACKUP_WATCH to the backup service on Railway, then stop")
    p.add_argument("--set-app-watch", action="store_true", help="copy APP_WATCH to the app's service on Railway, then stop")
    args = p.parse_args()
    if args.set_backup_watch:
        return set_watch(SERVICES[1], BACKUP_WATCH)
    if args.set_app_watch:
        return set_watch(SERVICES[0], APP_WATCH)
    run("git", "fetch", "-q", "origin", "main")
    sha = args.sha or run("git", "rev-parse", "origin/main").strip()
    if not args.no_ci:
        wait_ci(sha)
    ok = follow(SERVICES[0], sha, appear=600)
    ok = follow(SERVICES[1], sha, appear=120) and ok  # it starts with the app's deploy, or not at all
    up = beta_answers()
    say(f"Beta {'answers' if up else 'does NOT answer'}.")
    d = for_commit(SERVICES[0], sha)
    if up and d and d["status"] in ("SUCCESS", "SLEEPING"):
        now = version(want=sha)
        up = bool(now) and (sha.startswith(now) or now.startswith(sha))
        say(f"Beta runs {sha[:7]}." if up else f"Beta still runs {now or 'an unknown version'}, not {sha[:7]}.")
    sys.exit(0 if ok and up else 1)


if __name__ == "__main__":
    main()
