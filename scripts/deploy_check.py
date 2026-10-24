"""Follow a merge to beta, and retry Railway's own build-machine errors (docs/SETUP_LOG.md, 2026-10-24).

    uv run python scripts/deploy_check.py            # the newest commit on main
    uv run python scripts/deploy_check.py --sha abc1234
    uv run python scripts/deploy_check.py --set-backup-watch   # after changing BACKUP_WATCH below

1. Waits for GitHub's tests on that commit (Railway waits for them too).
2. Waits for each Railway service to deploy it. The backup service only rebuilds when a file it runs changed
   (BACKUP_WATCH, its Railway watch paths), so it may be skipped.
3. If a build failed because of Railway itself ("build daemon returned an error", the build machine dropping the
   connection), builds it again from source, up to twice. Any other failure is ours: it prints the end of the log
   and stops. Beta keeps running the previous version either way.
4. Checks beta answers.

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
BACKUP_WATCH = ["scripts/backup_db.py", "app/__init__.py", "app/backup.py", "app/config.py", "app/db.py", "app/history.py",
                "app/models.py", "pyproject.toml", "uv.lock", ".python-version"]
BETA = "https://beta.askdnd.ai/login"
DONE = {"SUCCESS", "SLEEPING", "FAILED", "CRASHED", "REMOVED", "SKIPPED"}
# Railway's build machines failing, not our code: worth building again
GLITCH = re.compile(r"build daemon returned an error|failed to solve: frontend grpc|buildkitd\.sock|failed to list workers"
                    r"|error reading server preface|context deadline exceeded", re.I)


def railway_glitch(log: str) -> bool:
    return bool(GLITCH.search(log or ""))


def run(*cmd: str, check: bool = True) -> str:
    out = subprocess.run(cmd, capture_output=True, text=True)
    if check and out.returncode != 0:
        sys.exit(f"{' '.join(cmd[:3])} failed: {out.stderr.strip()[:300]}")
    return out.stdout


def say(text: str) -> None:
    print(f"[{datetime.now():%H:%M:%S}] {text}", flush=True)


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
        runs = json.loads(run("gh", "run", "list", "--branch", "main", "--limit", "10", "--json", "headSha,databaseId,status,conclusion"))
        match = next((r for r in runs if r["headSha"].startswith(sha)), None)
        if match:
            if match["status"] != "completed":
                subprocess.run(["gh", "run", "watch", str(match["databaseId"]), "--exit-status"], capture_output=True)
                match = json.loads(run("gh", "run", "view", str(match["databaseId"]), "--json", "conclusion"))
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


def follow(service: str, sha: str, appear: int) -> bool:
    d = wait_deploy(service, sha, appear=appear)
    if d is None:
        say(f"{service}: no deploy for this commit (nothing it runs changed).")
        return True
    for attempt in range(3):
        if d["status"] == "SKIPPED":
            say(f"{service}: skipped (nothing it runs changed).")
            return True
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


def set_backup_watch() -> None:
    """Copy BACKUP_WATCH to the backup service's settings on Railway (signed in with the Railway CLI's login)."""
    status = json.loads(run("railway", "status", "--json"))
    env = next(e["node"]["id"] for e in status["environments"]["edges"] if e["node"]["name"] == "production")
    service = next(e["node"]["id"] for e in status["services"]["edges"] if e["node"]["name"] == SERVICES[1])
    user = json.load(open(os.path.expanduser("~/.railway/config.json")))["user"]

    def gql(query: str, variables: dict) -> dict:
        req = urllib.request.Request("https://backboard.railway.com/graphql/v2", json.dumps({"query": query, "variables": variables}).encode(),
                                     {"Authorization": "Bearer " + (user.get("accessToken") or user["token"]),
                                      "Content-Type": "application/json", "User-Agent": "askdnd-deploy-check"})
        return json.load(urllib.request.urlopen(req, timeout=30))

    ids = {"s": service, "e": env}
    out = gql("mutation($s:String!,$e:String!,$i:ServiceInstanceUpdateInput!){serviceInstanceUpdate(serviceId:$s,environmentId:$e,input:$i)}",
              {**ids, "i": {"watchPatterns": BACKUP_WATCH}})
    if out.get("errors"):
        sys.exit(f"Railway refused: {out['errors'][0]['message']}")
    now = gql("query($s:String!,$e:String!){serviceInstance(serviceId:$s,environmentId:$e){watchPatterns}}", ids)
    say(f"{SERVICES[1]} rebuilds only when these change: {', '.join(now['data']['serviceInstance']['watchPatterns'])}")


def beta_answers() -> bool:
    try:
        # Cloudflare turns away Python's default user agent
        req = urllib.request.Request(f"{BETA}?check={int(time.time())}", headers={"User-Agent": "askdnd-deploy-check"})
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status == 200
    except Exception:
        return False


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--sha", help="the commit to follow (default: the newest on main)")
    p.add_argument("--no-ci", action="store_true", help="don't wait for GitHub's tests")
    p.add_argument("--set-backup-watch", action="store_true", help="copy BACKUP_WATCH to the backup service on Railway, then stop")
    args = p.parse_args()
    if args.set_backup_watch:
        return set_backup_watch()
    run("git", "fetch", "-q", "origin", "main")
    sha = args.sha or run("git", "rev-parse", "origin/main").strip()
    if not args.no_ci:
        wait_ci(sha)
    ok = follow(SERVICES[0], sha, appear=600)
    ok = follow(SERVICES[1], sha, appear=120) and ok  # it starts with the app's deploy, or not at all
    up = beta_answers()
    say(f"Beta {'answers' if up else 'does NOT answer'}.")
    sys.exit(0 if ok and up else 1)


if __name__ == "__main__":
    main()
