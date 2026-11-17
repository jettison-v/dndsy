"""Claude's side of the feedback queue (app/feedback.py; Brett, 2026-11-03, docs/mockups/feedback-queue/).

When Brett says "review the feedback", pull the queue from askdnd, then answer or close each note:

    uv run python scripts/feedback.py pull                       # new, question and planned notes
    uv run python scripts/feedback.py pull --status done         # any states, comma-separated
    uv run python scripts/feedback.py ask 42 "Do you mean …?"    # a question for Brett, on the note
    uv run python scripts/feedback.py set 42 planned             # new | question | planned | done | deleted
    uv run python scripts/feedback.py set 42 done --pr https://github.com/jettison-v/dndsy/pull/190  # a broken note (or a built idea) gets its check:
    #   add --do "…" (once a step) --expect "…"; it comes back to Brett (or asks the player who sent it) once live
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

Working with Claude (Brett's picks Nov 17, docs/mockups/working-together/): askdnd keeps what Claude hasn't read yet
(app/for_claude.py), and the areas notes and checks are sorted into, one at a time in Claude's hands:

    uv run python scripts/feedback.py inbox                 # what's new in askdnd since the last read, then marks it read (--peek: doesn't)
    uv run python scripts/feedback.py wait                  # run in the background: returns once something's new (asks every minute)
    uv run python scripts/feedback.py area list             # every area, where it is, its notes and checks; notes in none yet
    uv run python scripts/feedback.py area add "Item Builder" --notes 81,82,89 --checks 1,2,28
    uv run python scripts/feedback.py area set 3 --fixing on          # taking it up (only one at a time); --fixing off once merged and live
    uv run python scripts/feedback.py area set 3 --notes 96 --drop-checks 2 --title "…"
    uv run python scripts/feedback.py area show 3           # an area's whole record: its notes with their threads, its checks (a fresh session starts here)

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
                **({"feedback_id": a.note} if a.note else {}), **({"area_id": a.area_id} if a.area_id else {})}
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
        m = re.search(r"github\.com/jettison-v/dndsy/pull/(\d+)", c["pr"] or "")  # (only this repository's changes)
        if not m:
            print(f"Check {c['id']}: fixed, but no PR to follow")
            continue
        got = subprocess.run(["gh", "pr", "view", m.group(1), "--json", "state,mergeCommit"], capture_output=True, text=True, check=False)
        if got.returncode:
            print(f"Check {c['id']}: couldn't read PR {m.group(1)} ({got.stderr.strip()[:80]})")
            continue
        pr = json.loads(got.stdout)
        sha = (pr.get("mergeCommit") or {}).get("oid") or ""
        merged = pr.get("state") == "MERGED" and sha
        inside = merged and subprocess.run(["git", "merge-base", "--is-ancestor", sha, running], cwd=ROOT, capture_output=True).returncode == 0
        if inside:
            call(base, f"/api/checks/{c['id']}", {"status": "again"})
            print(f"Check {c['id']}: live, back as Try again")
        else:
            print(f"Check {c['id']}: PR {m.group(1)} isn't live yet")


def _get(base: str, path: str) -> dict | None:
    """A read that never ends the script (`wait` rides out a deploy or a dropped connection)."""
    try:
        return json.loads(call(base, path))
    except (SystemExit, urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def _line(i: dict) -> str:
    return f"#{i['id']:<5} {i['at'][5:16].replace('T', ' ')}  {i['what']:<7} {i['text']}"


def inbox(a) -> None:
    """What's new in askdnd for Claude since its last read (app/for_claude.py), oldest first; then marks it read."""
    got = json.loads(call(a.base, "/api/claude/inbox"))
    items = got["items"]
    while got.get("more"):
        got = json.loads(call(a.base, f"/api/claude/inbox?after={items[-1]['id']}"))
        items += got["items"]
    if not items:
        print("Nothing new in askdnd.")
        return
    for i in items:
        print(_line(i))
    if not a.peek:
        call(a.base, "/api/claude/inbox/read", {"upto": items[-1]["id"]})
        print(f"{len(items)} item(s), marked read.")


def wait(a) -> None:
    """Asks askdnd every `--every` seconds until something's new for Claude, then says what (without marking it read)
    and ends: run in the background, its ending starts Claude's next turn. Rides out errors; ends after `--hours`."""
    import time

    until, misses = time.monotonic() + a.hours * 3600, 0
    while time.monotonic() < until:
        got = _get(a.base, "/api/claude/inbox")
        if got is None:
            misses += 1
            if misses in (5, 30):
                print(f"askdnd hasn't answered {misses} times in a row; still trying.", flush=True)
        elif got["items"]:
            print(f"{len(got['items'])} new in askdnd (feedback.py inbox reads and marks them):")
            for i in got["items"][:20]:
                print(_line(i))
            return
        else:
            misses = 0
        time.sleep(a.every)
    print(f"Nothing new in askdnd in {a.hours} hours.")


def _id_list(v: str) -> list[int]:
    return [int(x) for x in v.split(",") if x.strip().isdigit()] if v else []


def area(a) -> None:
    """Areas (app/testing.py): list, add, set, show."""
    if a.do_what == "list":
        got = json.loads(call(a.base, "/api/areas"))
        for x in got["areas"]:
            print(f"{x['id']:>3}  {x['says']:<14} {x['title']:<28} {x['next']:<24} notes {','.join(str(n['id']) for n in x['notes']) or '-'}"
                  f"  checks {','.join(str(c['id']) for c in x['checks']) or '-'}" + ("  ← Claude's" if x["fixing"] else ""))
        if got["unsorted"]:
            print("Not in an area: " + ", ".join(f"{n['id']} ({n['kind'] or '?'}) {n['title'][:40]}" for n in got["unsorted"]))
        return
    if a.do_what == "show":
        x = next((x for x in json.loads(call(a.base, "/api/areas"))["areas"] if x["id"] == a.id), None)
        if x is None:
            sys.exit(f"No area {a.id}.")
        print(f"# Area {x['id']}: {x['title']} · {x['says']} · {x['next']}\n")
        for n in x["notes"]:
            full = json.loads(call(a.base, f"/api/feedback/{n['id']}"))
            print(note_md(full))
        checks = {c["id"]: c for c in json.loads(call(a.base, "/api/checks"))["items"]}
        for c in x["checks"]:
            c = checks.get(c["id"]) or c
            print(f"## Check {c['id']}: {c['title']} · {c.get('says', c.get('status'))}")
            for line in c.get("do") or []:
                print(f"- {line}")
            if c.get("expect"):
                print(f"Expect: {c['expect']}")
            for h in c.get("history") or []:
                print(f"  {h.get('at', '')[:16]} {h.get('who')}: {h.get('what')}")
            print()
        return
    body = {k: v for k, v in (("notes", _id_list(a.notes)), ("checks", _id_list(a.checks)), ("drop_notes", _id_list(getattr(a, "drop_notes", ""))),
                              ("drop_checks", _id_list(getattr(a, "drop_checks", "")))) if v}
    if a.do_what == "add":
        x = json.loads(call(a.base, "/api/areas", {"title": a.title, **body}))
    else:
        if a.title:
            body["title"] = a.title
        if a.fixing:
            body["fixing"] = a.fixing == "on"
        if a.place is not None:
            body["place"] = a.place
        x = json.loads(call(a.base, f"/api/areas/{a.id}", body))
    print(f"Area {x['id']}: {x['title']} · {x['says']} · notes {','.join(str(n['id']) for n in x['notes']) or '-'} · checks {','.join(str(c['id']) for c in x['checks']) or '-'}")


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
    st.add_argument("--do", dest="steps", action="append", default=[], help="with done: its check's steps (once each)")
    st.add_argument("--expect", default="", help="with done: what its check should see")
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
    ca.add_argument("--area-id", dest="area_id", type=int, default=None, help="its area (feedback.py area list)")
    cs = cks.add_parser("set")
    cs.add_argument("id", type=int)
    cs.add_argument("status", choices=["ready", "again", "failed", "fixed", "passed", "skipped", "claude"])
    cs.add_argument("--said", default="")
    cs.add_argument("--pr", default="", help="the fix (with fixed: it comes back as Try again once live)")
    cks.add_parser("live", help="checks whose fix is now on askdnd.ai: Try again (deploy_check.py runs it)")
    ib = sub.add_parser("inbox", help="what's new in askdnd for Claude")
    ib.add_argument("--peek", action="store_true", help="read without marking it read")
    wt = sub.add_parser("wait", help="returns once something's new in askdnd (run in the background)")
    wt.add_argument("--every", type=int, default=60)
    wt.add_argument("--hours", type=float, default=10)
    ar = sub.add_parser("area", help="Testing's areas")
    ars = ar.add_subparsers(dest="do_what", required=True)
    ars.add_parser("list")
    ash = ars.add_parser("show")
    ash.add_argument("id", type=int)
    aa = ars.add_parser("add")
    aa.add_argument("title")
    aa.add_argument("--notes", default="")
    aa.add_argument("--checks", default="")
    aset = ars.add_parser("set")
    aset.add_argument("id", type=int)
    aset.add_argument("--title", default="")
    aset.add_argument("--notes", default="")
    aset.add_argument("--checks", default="")
    aset.add_argument("--drop-notes", dest="drop_notes", default="")
    aset.add_argument("--drop-checks", dest="drop_checks", default="")
    aset.add_argument("--fixing", choices=["on", "off"], default="")
    aset.add_argument("--place", type=int, default=None)
    a = p.parse_args()
    if a.cmd == "check":
        check(a)
        return
    if a.cmd in ("inbox", "wait", "area"):
        {"inbox": inbox, "wait": wait, "area": area}[a.cmd](a)
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
        body = {"status": a.status, "note": a.note, "pr": a.pr, **({"check_do": "\n".join(a.steps)} if a.steps else {}),
                **({"check_expect": a.expect} if a.expect else {})}
        print(json.loads(call(a.base, f"/api/feedback/{a.id}", body))["status"])


if __name__ == "__main__":
    main()
