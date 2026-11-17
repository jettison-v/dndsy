"""Claude's side of the feedback queue (app/feedback.py; Brett, 2026-11-03, docs/mockups/feedback-queue/).

When Brett says "review the feedback", pull the queue from askdnd, then answer or close each note:

    uv run python scripts/feedback.py pull                       # new, question and planned notes
    uv run python scripts/feedback.py pull --status done         # any states, comma-separated
    uv run python scripts/feedback.py ask 42 "Do you mean …?"    # a question for Brett, on the note
    uv run python scripts/feedback.py set 42 planned             # new | question | planned | done | deleted
    uv run python scripts/feedback.py set 42 done --pr https://github.com/jettison-v/dndsy/pull/190
    uv run python scripts/feedback.py tell 42 "Rest stays on one line now …"   # a reply its sender sees on Notes you sent (not starting with its status: the note shows that)
    uv run python scripts/feedback.py kind 42 idea "It's a new feature, not a fix"   # what it is, and why
    uv run python scripts/feedback.py title 42 "Change forms beside Change spells"     # a short title, when taking it up
    uv run python scripts/feedback.py pull --kind none            # notes sent before kinds, to sort once

Testing (app/testing.py; Brett's picks, Nov 16): a check for Brett to try, with why it's there. Write one with every
fix to a broken note (--note) and every change he should look at (--pr); a run on the Mac Mini sets one `claude`:

    uv run python scripts/feedback.py check list                     # every check (--status ready,again,…)
    uv run python scripts/feedback.py check add "Column headings stay while a list scrolls" --area Sheet \
        --setup view_as --as "Cole's player" --path "/characters/1?tab=items" --minutes 2 --note 73 --pr <url> \
        --do "Scroll down the Inventory list." --do "Then Change forms, and scroll." --expect "They stay under the tabs." \
        --said "Fixed: every list's headings now stay at the top."
    uv run python scripts/feedback.py check set 12 again --said "Fixed in PR 401: …"   # ready | again | claude | …
    uv run python scripts/feedback.py check set 12 claude --said "12 of 12 on the Mini's seats"
    uv run python scripts/feedback.py check set 12 fixed --pr <url> --said "Fixed: …"   # comes back by itself once live
    uv run python scripts/feedback.py check live                    # (deploy_check.py runs it after each deploy)

Give each note a short title when you take it up (Brett, Nov 16: a few words saying what it's about; its sender sees it on
Notes you sent, and the queue lists it). What each kind gets (Brett, Nov 16): **broken**, fix it in the next round (one people would see still goes to Brett as a
local link first); **idea**, add it to the Roadmap's Ideas from feedback with a size (S, M or L) and set it planned:
nothing is built until Brett moves it up; **question**, answer it with `tell`, then set it done.

`pull` writes each note to private/feedback/<id>/ (never committed: notes hold campaign pages): note.md (the words,
who, where, when, the thread), context.json, page.html (the page as drawn), shot.jpg (its picture) and pasted.* (a
screenshot Brett added), and added-<id>.* (screenshots added later with Add to it). Reads askdnd at --base (default https://askdnd.ai) with FEEDBACK_KEY, from the environment
or .env (set with scripts/set-secret.sh FEEDBACK_KEY).
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "private" / "feedback"


def key() -> str:
    if os.getenv("FEEDBACK_KEY"):
        return os.environ["FEEDBACK_KEY"].strip()
    env = ROOT / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith("FEEDBACK_KEY="):
            return line.split("=", 1)[1].strip().strip('"')
    sys.exit("No FEEDBACK_KEY: set it with scripts/set-secret.sh FEEDBACK_KEY (the same on beta and here).")


def call(base: str, path: str, body: dict | None = None) -> bytes:
    req = urllib.request.Request(base.rstrip("/") + path, method="POST" if body is not None else "GET",
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"X-Feedback-Key": key(), "Accept": "application/json", "Content-Type": "application/json",
                                          "User-Agent": "askdnd-feedback-script"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"askdnd answered {e.code} for {path}" + (" (is FEEDBACK_KEY the same as beta's?)" if e.code == 404 and path == "/api/feedback" else ""))


def note_md(item: dict) -> str:
    c = item.get("context") or {}
    lines = [f"# Feedback {item['id']} · {item.get('kind') or 'not sorted'} · {item['status']}" + (f" · {item['title']}" if item.get("title") else ""), "", item["text"], "",
             f"- From: {item['sender']}" + (f", viewing as {c['viewing_as']}" if c.get("viewing_as") else ""),
             f"- Page: {c.get('page', '')} · {item['url']}", f"- When: {c.get('at', '')} (server {c.get('server_at', '')})",
             f"- Window: {c.get('window', '')} · zoom {c.get('zoom', '')} · screen {c.get('screen', '')}",
             f"- Browser: {c.get('browser', '')} · askdnd bridge {c.get('extension') or '?'}",
             f"- Live pill: {c.get('live', '')} · tab {c.get('tab', '')} · panel {c.get('panel', '')}"]
    if c.get("pointed"):
        lines.append(f"- Pointed at: {c['pointed'].get('label')} ({c['pointed'].get('path')})")
    if c.get("errors"):
        lines.append(f"- Page errors: {json.dumps(c['errors'])}")
    if item.get("thread"):
        lines += ["", "## Thread", *[f"- **{'Claude' if m['who'] == 'claude' else 'Brett'}:** {m['text']}"
                                     + (f" (screenshots: {', '.join(f'added-{p}' for p in m['pics'])})" if m.get("pics") else "") for m in item["thread"]]]
    if item.get("pr"):
        lines += ["", f"Fixed in {item['pr']}"]
    return "\n".join(lines) + "\n"


DEFAULT_BASE, STAGING_BASE = "https://askdnd.ai", "https://staging.askdnd.ai"


def pull(base: str, status: str, kind: str = "") -> None:
    items = json.loads(call(base, f"/api/feedback?status={status}" + (f"&kind={kind}" if kind else "")))["items"]
    OUT.mkdir(parents=True, exist_ok=True)
    for item in items:
        full = json.loads(call(base, f"/api/feedback/{item['id']}"))
        d = OUT / (f"staging-{item['id']}" if "staging." in base else str(item["id"]))  # (staging's ids overlap beta's)
        d.mkdir(exist_ok=True)
        (d / "note.md").write_text(note_md(full))
        (d / "context.json").write_text(json.dumps(full.get("context") or {}, indent=1))
        if full.get("html"):
            (d / "page.html").write_text(full["html"])
        for which in full.get("shots") or []:
            data = call(base, f"/api/feedback/{item['id']}/{which}")
            ext = ".jpg" if data[:3] == b"\xff\xd8\xff" else ".webp" if data[8:12] == b"WEBP" else ".png"
            (d / f"{which}{ext}").write_bytes(data)
        for m in full.get("thread") or []:  # (screenshots added with Add to it: added-<id>.*)
            for pid in m.get("pics") or []:
                data = call(base, f"/api/feedback/{item['id']}/pic/{pid}")
                ext = ".jpg" if data[:3] == b"\xff\xd8\xff" else ".webp" if data[8:12] == b"WEBP" else ".png"
                (d / f"added-{pid}{ext}").write_bytes(data)
        print(f"{item['id']:>4}  {item.get('kind') or '-':<8} {item['status']:<9} {item['sender'][:24]:<24} {item['text'][:90]}")
    print(f"{len(items)} note(s) in {OUT.relative_to(ROOT)}/")


def check(a) -> None:
    """Testing's checks (app/testing.py): list them, add one, or move one on."""
    if a.do_what == "list":
        for c in json.loads(call(a.base, "/api/checks" + (f"?status={a.status}" if a.status else "")))["items"]:
            print(f"{c['id']:>4}  {c['status']:<8} {c['group']:<24} {c['title']}" + (f"  (note {c['feedback_id']})" if c["feedback_id"] else ""))
    elif a.do_what == "add":
        body = {"title": a.title, "area": a.area, "setup": a.setup or "laptop", "as_who": a.as_who, "path": a.path, "do": "\n".join(a.steps),
                "expect": a.expect, "pr": a.pr, "said": a.said, "minutes": a.minutes, "place": a.place,
                **({"feedback_id": a.note} if a.note else {})}
        c = json.loads(call(a.base, "/api/checks", body))
        print(f"Check {c['id']}: {c['title']} ({c['says']})")
    elif a.do_what == "live":
        live(a.base)
    else:
        c = json.loads(call(a.base, f"/api/checks/{a.id}", {"status": a.status, **({"said": a.said} if a.said else {}), **({"pr": a.pr} if a.pr else {})}))
        print(f"Check {c['id']}: {c['says']}")


def live(base: str) -> None:
    """Every check marked fixed whose PR is merged and in what askdnd runs now (its /health version) comes back as
    Try again (Brett's 4A): a fix is tried once it's where he'll try it, never before."""
    import re
    import subprocess

    subprocess.run(["git", "fetch", "-q", "origin"], cwd=ROOT, check=False)  # (the running commit is known here)
    health = urllib.request.Request(base.rstrip("/") + "/health", headers={"User-Agent": "askdnd-feedback-script"})  # (a bare client is turned away)
    running = json.loads(urllib.request.urlopen(health, timeout=30).read())["version"]
    for c in json.loads(call(base, "/api/checks?status=fixed"))["items"]:
        m = re.search(r"/pull/(\d+)", c["pr"] or "")
        if not m:
            print(f"Check {c['id']}: fixed, but no PR to follow")
            continue
        pr = json.loads(subprocess.run(["gh", "pr", "view", m.group(1), "--json", "state,mergeCommit"], capture_output=True, text=True, check=True).stdout)
        sha = (pr.get("mergeCommit") or {}).get("oid") or ""
        merged = pr.get("state") == "MERGED" and sha
        inside = merged and subprocess.run(["git", "merge-base", "--is-ancestor", sha, running], cwd=ROOT, capture_output=True).returncode == 0
        if inside:
            call(base, f"/api/checks/{c['id']}", {"status": "again"})
            print(f"Check {c['id']}: live, back as Try again")
        else:
            print(f"Check {c['id']}: PR {m.group(1)} isn't live yet")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--base", default=os.getenv("ASKDND_BASE", DEFAULT_BASE))
    p.add_argument("--staging", action="store_const", const=STAGING_BASE, dest="base",
                   help="staging's own queue (staging.askdnd.ai), filed as private/feedback/staging-<id>")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("pull")
    pl.add_argument("--status", default="new,question,planned")
    pl.add_argument("--kind", default="", help="broken, idea, question or none (not sorted), comma-separated")
    kd = sub.add_parser("kind")
    kd.add_argument("id", type=int)
    kd.add_argument("kind", choices=["broken", "idea", "question"])
    kd.add_argument("why", nargs="?", default="")
    tt = sub.add_parser("title")
    tt.add_argument("id", type=int)
    tt.add_argument("title")
    ask = sub.add_parser("ask")
    ask.add_argument("id", type=int)
    ask.add_argument("question")
    tl = sub.add_parser("tell")
    tl.add_argument("id", type=int)
    tl.add_argument("text")
    st = sub.add_parser("set")
    st.add_argument("id", type=int)
    st.add_argument("status", choices=["new", "question", "planned", "done", "deleted"])
    st.add_argument("--note", default="")
    st.add_argument("--pr", default="")
    ck = sub.add_parser("check", help="Testing: checks for Brett to try")
    cks = ck.add_subparsers(dest="do_what", required=True)
    cl = cks.add_parser("list")
    cl.add_argument("--status", default="")
    ca = cks.add_parser("add")
    ca.add_argument("title")
    for flag, dest in (("--area", "area"), ("--setup", "setup"), ("--as", "as_who"), ("--path", "path"), ("--expect", "expect"), ("--pr", "pr"), ("--said", "said")):
        ca.add_argument(flag, dest=dest, default="")
    ca.add_argument("--do", dest="steps", action="append", default=[], help="a step; once for each")
    ca.add_argument("--minutes", type=int, default=1)
    ca.add_argument("--place", type=int, default=0)
    ca.add_argument("--note", type=int, default=None, help="the feedback note it came from")
    cs = cks.add_parser("set")
    cs.add_argument("id", type=int)
    cs.add_argument("status", choices=["ready", "again", "failed", "fixed", "passed", "skipped", "claude"])
    cs.add_argument("--said", default="")
    cs.add_argument("--pr", default="", help="the fix (with fixed: it comes back as Try again once live)")
    cks.add_parser("live", help="checks whose fix is now on askdnd.ai: Try again (deploy_check.py runs it)")
    a = p.parse_args()
    if a.cmd == "check":
        check(a)
        return
    if a.cmd == "pull":
        pull(a.base, a.status, a.kind)
        if a.base == DEFAULT_BASE:  # (and staging's own queue: notes sent from staging.askdnd.ai, filed as staging-<id>)
            print("Staging:")
            pull(STAGING_BASE, a.status, a.kind)
    elif a.cmd == "title":
        print(json.loads(call(a.base, f"/api/feedback/{a.id}", {"title": a.title}))["title"])
    elif a.cmd == "kind":
        print(json.loads(call(a.base, f"/api/feedback/{a.id}", {"kind": a.kind, "why": a.why}))["kind"])
    elif a.cmd == "tell":
        print(json.loads(call(a.base, f"/api/feedback/{a.id}", {"tell": a.text}))["status"])
    elif a.cmd == "ask":
        print(json.loads(call(a.base, f"/api/feedback/{a.id}", {"note": a.question, "status": "question"}))["status"])
    else:
        print(json.loads(call(a.base, f"/api/feedback/{a.id}", {"status": a.status, "note": a.note, "pr": a.pr}))["status"])


if __name__ == "__main__":
    main()
