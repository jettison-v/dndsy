"""How long each page takes on askdnd.ai, kept, and a weekly look at the slowest (Performance: the whole tool, Brett's
Roadmap item, step 4: "A weekly look at Railway's slowest requests, into Development").

Every HTTP request's time (app/timing.py's stopwatch, without a long-poll's held wait) is added to its route's count for
the day (`record`: the route as written, never an id; a few routes that aren't pages are left out), in memory, and
saved every few minutes (`flush`, `RequestTime`: per day and route, how many, the total, the slowest, and how many fell
in each time band). Once a week (`review`, Mondays) the week's numbers are read: each route whose slowest tenth takes
`SLOW_P90_MS` or more, often enough to matter, becomes an issue under Behind the scenes › Speed (one per route, kept
up to date while it's open), and the run is reported as the Scheduled job "speed" on Development. Rows older than
`KEEP_DAYS` go. `/api/fft/speed` gives Claude the week's table."""

import asyncio
import logging
import re
import threading
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config

log = logging.getLogger("askdnd.speed")

BANDS_MS = (50, 100, 250, 500, 1000, 2000, 5000)  # (upper edges; one more band above the last)
SLOW_P90_MS = 800  # a route whose slowest tenth takes this long or more is slow
MIN_COUNT = 20  # asked at least this often in the week, so one odd request isn't a finding
KEEP_DAYS = 60
TICK = 300  # seconds between saves
SKIP = ("/static", "/health", "/live/connect", "/favicon")  # (not pages: files, the health check, the live socket)
JOB = "speed"
LAST = "speed_review_at"  # (a ToolSetting: when the weekly look last ran)

_lock = threading.Lock()
_now: dict[tuple[str, str], list] = {}  # (method, route) -> [count, total_ms, max_ms, bands...]


def band(ms: float) -> int:
    return next((i for i, edge in enumerate(BANDS_MS) if ms <= edge), len(BANDS_MS))


CAMPAIGN = re.compile(r"^/c/[^/]+")  # (a campaign's pages reach the app with its name in the address: one route for all)


def record(method: str, route: str, ms: float) -> None:
    """One request's time, added to its route's count in memory (called by the stopwatch on every HTTP request). A
    campaign's address is counted without its name (/c/{slug}/party), so one page is one route and no name is kept."""
    if not route or route.startswith(SKIP):
        return
    route = CAMPAIGN.sub("/c/{slug}", route)
    with _lock:
        row = _now.setdefault((method, route), [0, 0.0, 0.0] + [0] * (len(BANDS_MS) + 1))
        row[0] += 1
        row[1] += ms
        row[2] = max(row[2], ms)
        row[3 + band(ms)] += 1


def flush(db: Session) -> int:
    """What's counted in memory, added to today's rows (the table's day). Returns how many routes it saved."""
    from app.models import RequestTime

    with _lock:
        taken = dict(_now)
        _now.clear()
    if not taken:
        return 0
    day = config.table_today()
    for (method, route), (count, total, top, *bands) in taken.items():
        row = db.scalar(select(RequestTime).where(RequestTime.day == day, RequestTime.method == method, RequestTime.route == route))
        if row is None:
            row = RequestTime(day=day, method=method, route=route[:200], count=0, total_ms=0, max_ms=0, bands=[0] * (len(BANDS_MS) + 1))
            db.add(row)
        row.count += count
        row.total_ms += int(total)
        row.max_ms = max(row.max_ms, int(top))
        row.bands = [a + b for a, b in zip(row.bands or [0] * len(bands), bands, strict=False)]
    db.commit()
    return len(taken)


def _quantile(bands: list[int], q: float) -> int:
    """The time band's upper edge where `q` of the requests have finished (an estimate: the bands are its resolution)."""
    total, seen = sum(bands), 0
    for i, n in enumerate(bands):
        seen += n
        if total and seen >= q * total:
            return BANDS_MS[i] if i < len(BANDS_MS) else BANDS_MS[-1] * 2
    return 0


def week(db: Session, days: int = 7) -> list[dict]:
    """The last `days` days per route, slowest tenth first: {method, route, count, avg_ms, p50_ms, p90_ms, max_ms}."""
    from app.models import RequestTime

    since = config.table_today() - timedelta(days=days - 1)
    acc: dict[tuple[str, str], dict] = {}
    for r in db.scalars(select(RequestTime).where(RequestTime.day >= since)):
        a = acc.setdefault((r.method, r.route), {"count": 0, "total": 0, "max": 0, "bands": [0] * (len(BANDS_MS) + 1)})
        a["count"] += r.count
        a["total"] += r.total_ms
        a["max"] = max(a["max"], r.max_ms)
        a["bands"] = [x + y for x, y in zip(a["bands"], r.bands or [], strict=False)]
    out = [{"method": m, "route": route, "count": a["count"], "avg_ms": round(a["total"] / a["count"]) if a["count"] else 0,
            "p50_ms": min(_quantile(a["bands"], .5), a["max"]), "p90_ms": min(_quantile(a["bands"], .9), a["max"]), "max_ms": a["max"]}
           for (m, route), a in acc.items()]
    return sorted(out, key=lambda r: (-r["p90_ms"], -r["count"]))


def review(db: Session) -> dict:
    """The weekly look: the week's slow routes become (or update) issues under Behind the scenes › Speed, the run is
    reported on Development's Scheduled tab, and rows older than KEEP_DAYS go."""
    from app.fft import rules, work_page
    from app.fft.models import FftIssue
    from app.models import RequestTime, ToolSetting

    rows = week(db)
    slow = [r for r in rows if r["p90_ms"] >= SLOW_P90_MS and r["count"] >= MIN_COUNT]
    filed = []
    for r in slow:
        title = f"Slow: {r['method']} {r['route']}"[:80]
        said = f"{title} (slowest tenth {r['p90_ms'] / 1000:.1f} s, average {r['avg_ms']} ms, {r['count']} requests this week)"
        issue = db.scalar(select(FftIssue).where(FftIssue.title.startswith(title), FftIssue.state != "closed"))
        if issue is None:
            issue = rules.new_issue(db, "askdnd", said[:120], feature="speed", kind="improvement")
        else:
            issue.title = said[:120]
        filed.append(issue.id)
    db.execute(RequestTime.__table__.delete().where(RequestTime.day < config.table_today() - timedelta(days=KEEP_DAYS)))
    words = (f"{len(rows)} routes this week; {len(slow)} slow (the slowest tenth {SLOW_P90_MS} ms or more): "
             + ", ".join(f"{r['route']} {r['p90_ms'] / 1000:.1f} s" for r in slow[:5])) if slow else f"{len(rows)} routes this week; none slow."
    work_page.report_job(db, "askdnd", JOB, "ok", words[:500])
    setting = db.get(ToolSetting, LAST) or ToolSetting(key=LAST)
    setting.value = config.table_today().isoformat()
    db.merge(setting)
    db.commit()
    return {"routes": len(rows), "slow": slow, "issues": filed}


def due(db: Session) -> bool:
    """Mondays (the table's day), once."""
    from app.models import ToolSetting

    today = config.table_today()
    last = db.get(ToolSetting, LAST)
    return today.weekday() == 0 and (last is None or last.value != today.isoformat())


def run_once() -> None:
    from app.db import SessionLocal

    with SessionLocal() as db:
        flush(db)
        if due(db):
            review(db)


async def loop() -> None:
    """Started with the app (app/main.py): a save every TICK seconds, the weekly look when it's due; never stops on an error."""
    while True:
        await asyncio.sleep(TICK)
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            log.warning("Saving request times failed this time", exc_info=True)
