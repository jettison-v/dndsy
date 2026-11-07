"""Claude's side of the feedback queue (app/feedback.py; Brett, 2026-11-03, docs/mockups/feedback-queue/).

When Brett says "review the feedback", pull the queue from askdnd, then answer or close each note:

    uv run python scripts/feedback.py pull                       # new, question and planned notes
    uv run python scripts/feedback.py pull --status done         # any states, comma-separated
    uv run python scripts/feedback.py ask 42 "Do you mean …?"    # a question for Brett, on the note
    uv run python scripts/feedback.py set 42 planned             # new | question | planned | done | deleted
    uv run python scripts/feedback.py set 42 done --pr https://github.com/jettison-v/dndsy/pull/190
    uv run python scripts/feedback.py tell 42 "Fixed: …"     # a reply its sender sees on Your feedback

`pull` writes each note to private/feedback/<id>/ (never committed: notes hold campaign pages): note.md (the words,
who, where, when, the thread), context.json, page.html (the page as drawn), shot.jpg (its picture) and pasted.* (a
screenshot Brett added). Reads askdnd at --base (default https://askdnd.ai) with FEEDBACK_KEY, from the environment
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
    lines = [f"# Feedback {item['id']} · {item['status']}", "", item["text"], "",
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
        lines += ["", "## Thread", *[f"- **{'Claude' if m['who'] == 'claude' else 'Brett'}:** {m['text']}" for m in item["thread"]]]
    if item.get("pr"):
        lines += ["", f"Fixed in {item['pr']}"]
    return "\n".join(lines) + "\n"


DEFAULT_BASE, STAGING_BASE = "https://askdnd.ai", "https://staging.askdnd.ai"


def pull(base: str, status: str) -> None:
    items = json.loads(call(base, f"/api/feedback?status={status}"))["items"]
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
        print(f"{item['id']:>4}  {item['status']:<9} {item['sender'][:24]:<24} {item['text'][:90]}")
    print(f"{len(items)} note(s) in {OUT.relative_to(ROOT)}/")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--base", default=os.getenv("ASKDND_BASE", DEFAULT_BASE))
    p.add_argument("--staging", action="store_const", const=STAGING_BASE, dest="base",
                   help="staging's own queue (staging.askdnd.ai), filed as private/feedback/staging-<id>")
    sub = p.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("pull")
    pl.add_argument("--status", default="new,question,planned")
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
    a = p.parse_args()
    if a.cmd == "pull":
        pull(a.base, a.status)
        if a.base == DEFAULT_BASE:  # (and staging's own queue: notes sent from staging.askdnd.ai, filed as staging-<id>)
            print("Staging:")
            pull(STAGING_BASE, a.status)
    elif a.cmd == "tell":
        print(json.loads(call(a.base, f"/api/feedback/{a.id}", {"tell": a.text}))["status"])
    elif a.cmd == "ask":
        print(json.loads(call(a.base, f"/api/feedback/{a.id}", {"note": a.question, "status": "question"}))["status"])
    else:
        print(json.loads(call(a.base, f"/api/feedback/{a.id}", {"status": a.status, "note": a.note, "pr": a.pr}))["status"])


if __name__ == "__main__":
    main()
