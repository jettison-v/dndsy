"""How long each page and call takes, and how many database reads it makes (Performance: the whole tool, Brett's
Roadmap item, Nov 20).

Runs askdnd in this process against the database in .env (the local copy of askdnd.ai: scripts/pull_beta.sh) and asks
every main page and the calls pages make on their own (polls, counts, the live pill), as the admin, the campaign's DM
and one of its players. On askdnd.ai each database read costs about 2 ms more than here (the database is across
Railway's network), so the reads column predicts the gap: a page with 300 reads is ~0.6 s slower there.

    uv run python scripts/page_speed.py               # every page, slowest first
    uv run python scripts/page_speed.py --runs 5      # more runs each (the median is shown)
    uv run python scripts/page_speed.py --json out.json
"""

import argparse
import json
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi.testclient import TestClient
from sqlalchemy import event

from app.db import engine
from app.main import app

RAILWAY_READ_MS = 2.0  # (measured Nov 20 from Railway's logs: a read across its network)
# Loading sheets crosses Railway's network at about 4 MB/s (Nov 20: twelve whole sheets, 8.5 MB, made a party page take 2 s)
RAILWAY_SHEET_MS = 128.0  # (a whole D&D Beyond sheet, ~540 KB)
RAILWAY_SUMMARY_MS = 40.0  # (its summary, ~170 KB)
CAMPAIGN = "main"
PLAYER = (f"/c/{CAMPAIGN}/campaign", f"/c/{CAMPAIGN}/campaign?tab=sessions", f"/c/{CAMPAIGN}/campaign?tab=world",
          f"/c/{CAMPAIGN}/campaign?tab=glossary", "/party", f"/c/{CAMPAIGN}/party", "/help", "/your-notes",
          "{char}/battle", "{char}", "{char}/plan", "{char}/spellbook", "/c/vtt-test/party",
          # (asked by pages on their own, again and again)
          "/hp/now?ids={ids}", "/live/pill", "/your-notes/news", "/rolls", "/search/index")
DM = (f"/c/{CAMPAIGN}/manage", f"/c/{CAMPAIGN}/manage/inbox", f"/c/{CAMPAIGN}/manage/sessions", f"/c/{CAMPAIGN}/manage/table",
      f"/c/{CAMPAIGN}/manage/house-rules", f"/c/{CAMPAIGN}/manage/history", f"/c/{CAMPAIGN}/manage/settings",
      f"/c/{CAMPAIGN}/manage/places", f"/c/{CAMPAIGN}/dm", f"/c/{CAMPAIGN}/manage/counts", "/party", "/rolls", "/hp/now?ids={ids}")
ADMIN = tuple(f"/manage/{p}" for p in ("askdnd", "campaigns", "accounts", "tool-corrections", "usage", "features", "backups",
                                       "history", "design", "dice", "for-you", "for-you/count", "feedback", "roadmap", "work",
                                       "work?tab=checks", "work?tab=scheduled", "product-areas", "documents")) \
        + (f"/c/{CAMPAIGN}/manage/counts", "/your-notes/news", "/live/pill")


def counted():
    seen = {"n": 0, "sheets": 0, "summaries": 0}

    def count(conn, cursor, statement, *_):
        seen["n"] += 1
        head = re.split(r"\sFROM\s", statement, maxsplit=1)[0]
        whole = r"(?=,|\s|$)(?!\s*->)"  # (the column itself, not a path into it)
        seen["sheets"] += len(re.findall(r"character_snapshots\.raw" + whole, head))
        seen["summaries"] += len(re.findall(r"character_snapshots\.summary" + whole, head))

    event.listen(engine, "before_cursor_execute", count)
    return seen, lambda: event.remove(engine, "before_cursor_execute", count)


def person(who: str) -> TestClient:
    c = TestClient(app, base_url="http://127.0.0.1")
    c.get(f"/dev/login?next=/c/{CAMPAIGN}/campaign" + (f"&as={who}" if who != "admin" else ""), follow_redirects=True)
    return c


def their_characters(c: TestClient) -> tuple[str, str]:
    """(the first character's address on Party, every character's id there)."""
    page = c.get("/party").text
    m = re.search(r'href="(/characters/[^"/?#]+)', page)
    return (m.group(1) if m else ""), ",".join(dict.fromkeys(re.findall(r'href="/characters/(\d+)', page)))


def measure(c: TestClient, path: str, runs: int) -> dict:
    c.get(path)  # (warm: caches, templates)
    times, reads, sheets, summaries, status = [], [], [], [], 0
    for _ in range(runs):
        seen, stop = counted()
        t = time.perf_counter()
        r = c.get(path)
        times.append((time.perf_counter() - t) * 1000)
        stop()
        reads.append(seen["n"])
        sheets.append(seen["sheets"])
        summaries.append(seen["summaries"])
        status = r.status_code
    ms, n = statistics.median(times), statistics.median(reads)
    k, s = int(statistics.median(sheets)), int(statistics.median(summaries))
    return {"path": path, "ms": round(ms), "reads": int(n), "sheets": k, "summaries": s, "status": status,
            "railway_ms": round(ms + n * RAILWAY_READ_MS + k * RAILWAY_SHEET_MS + s * RAILWAY_SUMMARY_MS)}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--json", default="")
    a = p.parse_args()
    out = []
    for who, paths in (("player", PLAYER), ("dm", DM), ("admin", ADMIN)):
        c = person(who)
        char, ids = their_characters(c)
        for path in paths:
            if "{char}" in path and not char:
                continue
            row = measure(c, path.format(char=char, ids=ids), a.runs)
            row["who"] = who
            out.append(row)
    out.sort(key=lambda r: -r["railway_ms"])
    print(f"{'on Railway':>10} {'here':>6} {'reads':>6} {'sheets':>6} {'summ.':>6}  who     page")
    for r in out:
        flag = "" if r["status"] < 400 else f"  ({r['status']})"
        print(f"{r['railway_ms']:>8}ms {r['ms']:>4}ms {r['reads']:>6} {r['sheets']:>6} {r['summaries']:>6}  {r['who']:<7} {r['path']}{flag}")
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
