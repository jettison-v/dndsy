"""GitHub tells askdnd about the pull requests (item 39, A sturdier loop; scope v4, Brett's OK Nov 24).

Run by .github/workflows/report.yml on GitHub itself, after each pull request event, each test run and each push to main,
with only Python's own library and GitHub's `gh`. It does two things:

1. Keeps waiting pull requests up to date: after main moves (or auto-merge is turned on), each open pull request set to
   merge by itself that is behind main gets main merged in, and its tests are started again (an update GitHub's own
   token makes starts no run of its own). Without this, main's "up to date before merging" rule left them waiting.
2. Reports every open pull request to askdnd (POST /api/fft/github/pulls, FFT_GITHUB_KEY), as a whole list so askdnd
   also closes any it still holds open, plus the one just closed: its title, branch, tests, whether it's behind main,
   and whether it merges by itself. askdnd links each to its work (app/fft/rules.py `pulls_seen`).

It never checks out a pull request's own code: it reads what GitHub says about them. A pull request from a fork isn't
ours, so it's left out. A report that can't reach askdnd is a warning on the run, never a failure: the next run sends
the whole list again.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

ASKDND = os.getenv("ASKDND_URL", "https://askdnd.ai")
TESTS = ("Server tests", "Browser tests")  # (the checks main's protection asks for; the freeze job is left out: a pause isn't a red test)
FIELDS = "number,title,headRefName,author,isCrossRepository,autoMergeRequest,mergeStateStatus,headRefOid,statusCheckRollup"
FAILED = {"failure", "timed_out", "action_required", "startup_failure", "error"}


def gh(*args: str) -> str:
    return subprocess.run(["gh", *args], check=True, capture_output=True, text=True).stdout


def tests_of(rollup: list | None) -> str:
    """The required checks' state: failed if one failed, passed once both passed, running while one is on its way, else
    "" (none reported yet, or cancelled by a newer push)."""
    seen = {}
    for c in rollup or []:
        name = c.get("name") or c.get("context") or ""
        if name in TESTS:
            state = (c.get("conclusion") or c.get("state") or "").lower()
            status = (c.get("status") or "").lower()
            seen[name] = state if state else ("running" if status in ("queued", "in_progress", "pending", "waiting", "requested") else "")
    if any(v in FAILED for v in seen.values()):
        return "failed"
    if len(seen) == len(TESTS) and all(v == "success" for v in seen.values()):
        return "passed"
    if any(v in ("running", "pending", "expected", "success") for v in seen.values()):
        return "running"
    return ""


def row(pr: dict, state: str = "open") -> dict:
    author = pr.get("author") or {}
    return {"number": pr["number"], "title": (pr.get("title") or "")[:200], "branch": (pr.get("headRefName") or "")[:200],
            "by_bot": bool(author.get("is_bot")) or (author.get("login") or "").endswith("[bot]") or (author.get("login") or "").startswith("app/"),
            "state": state, "tests": tests_of(pr.get("statusCheckRollup")), "merge_state": (pr.get("mergeStateStatus") or "").lower(),
            "auto_merge": bool(pr.get("autoMergeRequest")), "head": (pr.get("headRefOid") or "")[:40]}


def open_ones(settle: bool) -> list[dict]:
    """The open pull requests that are ours. `settle`: GitHub works out "behind" a moment after main moves, so ask
    again (up to three times) while any of them is still UNKNOWN."""
    for attempt in range(3):
        prs = [p for p in json.loads(gh("pr", "list", "--state", "open", "--limit", "100", "--json", FIELDS)) if not p.get("isCrossRepository")]
        if not settle or not any((p.get("mergeStateStatus") or "").upper() == "UNKNOWN" for p in prs) or attempt == 2:
            return prs
        time.sleep(10)
    return prs


def bring_up_to_date(prs: list[dict], repo: str) -> set[int]:
    """Merge main into each open pull request set to merge by itself that's behind it, and start its tests again."""
    done = set()
    for p in prs:
        if not p.get("autoMergeRequest") or (p.get("mergeStateStatus") or "").upper() != "BEHIND":
            continue
        try:
            gh("api", "-X", "PUT", f"repos/{repo}/pulls/{p['number']}/update-branch", "-f", f"expected_head_sha={p['headRefOid']}")
            gh("workflow", "run", "tests.yml", "--ref", p["headRefName"])
            done.add(p["number"])
            print(f"#{p['number']}: brought up to date with main; its tests started again")
        except subprocess.CalledProcessError as e:
            print(f"::warning::#{p['number']} couldn't be brought up to date: {(e.stderr or '').strip()[:300]}")
    return done


def send(rows: list[dict], key: str) -> None:
    req = urllib.request.Request(f"{ASKDND}/api/fft/github/pulls", data=json.dumps({"pulls": rows, "snapshot": True}).encode(), method="POST",
                                 headers={"X-Fft-Key": key, "Content-Type": "application/json", "User-Agent": "askdnd-github"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            print(f"askdnd has {len(json.loads(r.read()).get('seen', []))} pull request(s)")
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        print(f"::warning::Couldn't report to askdnd ({e}); the next run sends the whole list again")


def main() -> None:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    try:
        with open(os.environ.get("GITHUB_EVENT_PATH", "")) as f:
            payload = json.load(f)
    except (OSError, ValueError):
        payload = {}
    action = payload.get("action", "")
    catch_up = event == "push" or (event == "pull_request_target" and action == "auto_merge_enabled")
    prs = open_ones(settle=catch_up)
    updated = bring_up_to_date(prs, repo) if catch_up else set()
    rows = []
    for p in prs:
        r = row(p)
        if p["number"] in updated:
            r.update(updated=True, tests="running", merge_state="")
        rows.append(r)
    closed = payload.get("pull_request") if event == "pull_request_target" and action == "closed" else None
    if closed and not (closed.get("head", {}).get("repo") or {}).get("fork"):
        rows.append(row({"number": closed["number"], "title": closed.get("title"), "headRefName": closed.get("head", {}).get("ref"),
                         "author": {"login": (closed.get("user") or {}).get("login"), "is_bot": (closed.get("user") or {}).get("type") == "Bot"},
                         "headRefOid": closed.get("head", {}).get("sha")}, "merged" if closed.get("merged") else "closed"))
        for gone in ("tests", "merge_state", "auto_merge"):  # (kept as they were: GitHub doesn't say once it's closed)
            rows[-1].pop(gone)
    key = os.environ.get("FFT_GITHUB_KEY", "")
    if not key:
        print("No FFT_GITHUB_KEY: nothing reported")
        return
    send(rows, key)


if __name__ == "__main__":
    sys.exit(main())
