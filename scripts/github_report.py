"""GitHub tells askdnd about the pull requests (item 39, A sturdier loop; scope v4, Brett's OK Nov 24).

Run by .github/workflows/report.yml on GitHub itself, after each pull request event, each test run and each push to main,
with only Python's own library and GitHub's `gh`. It does two things:

1. Keeps waiting pull requests up to date: each open pull request set to merge by itself that is behind main gets main
   merged in, and its tests are started again (an update GitHub's own token makes starts no run of its own). Without
   this, main's "up to date before merging" rule left them waiting. It's done on every run, not only after main
   moves: a run waiting for its turn can be replaced by a newer one.
2. Reports every open pull request to askdnd (POST /api/fft/github/pulls, FFT_GITHUB_KEY), as a whole list so askdnd
   also closes any it still holds open, and how the last few closed ones ended (merged or not), so a replaced run
   loses nothing: each one's title, branch, tests, whether it's behind main, and whether it merges by itself. askdnd links each to its work (app/fft/rules.py `pulls_seen`).

It never checks out a pull request's own code: it reads what GitHub says about them. A pull request from a fork isn't
ours, so it's left out. A report that can't reach askdnd is a warning on the run, never a failure: the next run sends
the whole list again.
"""

import http.client
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
CLOSED_FIELDS = "number,title,headRefName,author,isCrossRepository,headRefOid,mergedAt,closedAt,mergeCommit"
RECENT = 20  # (how many lately closed pull requests each run reports)
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


def row(pr: dict, state: str = "open", closed_at: str | None = None, merge_commit: str | None = None) -> dict:
    """What askdnd keeps of one. A closed one's tests, merge state and auto-merge aren't sent: GitHub no longer says,
    so askdnd keeps them as they last were."""
    author = pr.get("author") or {}
    login = author.get("login") or ""
    out = {"number": pr["number"], "title": (pr.get("title") or "")[:200], "branch": (pr.get("headRefName") or "")[:200],
           "by_bot": bool(author.get("is_bot")) or login.endswith("[bot]") or login.startswith("app/"), "state": state,
           "head": (pr.get("headRefOid") or "")[:40]}
    if state == "open":
        out |= {"tests": tests_of(pr.get("statusCheckRollup")), "merge_state": (pr.get("mergeStateStatus") or "").lower(),
                "auto_merge": bool(pr.get("autoMergeRequest"))}
    else:
        if closed_at:
            out["closed_at"] = closed_at
        if merge_commit and state == "merged":  # (askdnd finds what's inside the version it runs by this: rules.release_live)
            out["merge_commit"] = merge_commit[:40]
    return out


def open_ones() -> list[dict]:
    """The open pull requests that are ours. GitHub works out "behind" a moment after main moves, so while one set to
    merge by itself is still UNKNOWN, ask again (up to three times)."""
    for attempt in range(3):
        prs = [p for p in json.loads(gh("pr", "list", "--state", "open", "--limit", "100", "--json", FIELDS)) if not p.get("isCrossRepository")]
        if attempt == 2 or not any(p.get("autoMergeRequest") and (p.get("mergeStateStatus") or "").upper() == "UNKNOWN" for p in prs):
            return prs
        time.sleep(10)
    return prs


def closed_ones() -> list[dict]:
    """The pull requests closed lately, merged or not: a run that would have reported one may have been replaced by a
    newer one while it waited (one waits per group), so every run says how the last few ended."""
    got = json.loads(gh("pr", "list", "--state", "closed", "--limit", str(RECENT), "--json", CLOSED_FIELDS))
    return [row(p, "merged" if p.get("mergedAt") else "closed", closed_at=p.get("closedAt"), merge_commit=(p.get("mergeCommit") or {}).get("oid"))
            for p in got if not p.get("isCrossRepository")]


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
    except (OSError, ValueError, http.client.HTTPException) as e:  # (URLError, HTTPError and timeouts are OSErrors)
        print(f"::warning::Couldn't report to askdnd ({e}); the next run sends the whole list again")


def gather(event: str, payload: dict, repo: str) -> list[dict]:
    """Every open pull request (each behind one set to merge by itself brought up to date first: on every run, since a
    run waiting for its turn can be replaced by a newer one), then how the last few closed ones ended. One closed
    since it was listed as open counts as closed: the closed state wins."""
    prs = open_ones()
    updated = bring_up_to_date(prs, repo)
    rows = {}
    for p in prs:
        r = row(p)
        if p["number"] in updated:
            r.update(updated=True, tests="running", merge_state="")
        rows[p["number"]] = r
    for r in closed_ones():
        rows[r["number"]] = r
    closed = payload.get("pull_request") if event == "pull_request_target" and payload.get("action") == "closed" else None
    if closed and not (closed.get("head", {}).get("repo") or {}).get("fork"):
        user = closed.get("user") or {}
        rows[closed["number"]] = row({"number": closed["number"], "title": closed.get("title"), "headRefName": closed.get("head", {}).get("ref"),
                                      "author": {"login": user.get("login"), "is_bot": user.get("type") == "Bot"}, "headRefOid": closed.get("head", {}).get("sha")},
                                     "merged" if closed.get("merged") else "closed", closed_at=closed.get("closed_at"),
                                     merge_commit=closed.get("merge_commit_sha"))
    return list(rows.values())


def main() -> None:
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    try:
        with open(os.environ.get("GITHUB_EVENT_PATH", "")) as f:
            payload = json.load(f)
    except (OSError, ValueError):
        payload = {}
    try:
        rows = gather(event, payload, os.environ.get("GITHUB_REPOSITORY", ""))
    except (subprocess.CalledProcessError, ValueError) as e:
        print(f"::warning::Couldn't read the pull requests from GitHub ({getattr(e, 'stderr', '') or e}); the next run tries again")
        return
    key = os.environ.get("FFT_GITHUB_KEY", "")
    if not key:
        print("No FFT_GITHUB_KEY: nothing reported")
        return
    send(rows, key)


if __name__ == "__main__":
    sys.exit(main())
