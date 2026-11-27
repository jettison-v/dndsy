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
LOCK = 72_042_044  # (the weekly look runs in one copy only: two during a deploy filed each slow route twice, issue 157)

_lock = threading.Lock()
_now: dict[tuple[str, str], list] = {}  # (method, route) -> [count, total_ms, max_ms, bands...]


def band(ms: float) -> int:
    return next((i for i, edge in enumerate(BANDS_MS) if ms <= edge), len(BANDS_MS))


CAMPAIGN = re.compile(r"^/c/[^/]+")  # (a campaign's pages reach the app with its name in the address: one route for all)


def record(method: str, route: str, ms: float, db_ms: float = 0.0, reads: int = 0, before_ms: float = 0.0) -> None:
    """One request's time, added to its route's count in memory (called by the stopwatch on every HTTP request). A
    campaign's address is counted without its name (/c/{slug}/party), so one page is one route and no name is kept."""
    if not route or route.startswith(SKIP):
        return
    route = CAMPAIGN.sub("/c/{slug}", route)
    with _lock:
        row = _now.setdefault((method, route), [0, 0.0, 0.0, 0.0, 0, 0.0] + [0] * (len(BANDS_MS) + 1))
        row[0] += 1
        row[1] += ms
        row[2] = max(row[2], ms)
        row[3] += db_ms
        row[4] += reads
        row[5] += before_ms
        row[6 + band(ms)] += 1


def flush(db: Session) -> int:
    """What's counted in memory, added to today's rows (the table's day). Returns how many routes it saved. Not saved,
    the numbers go back in memory for the next save, never lost (issue 157)."""
    with _lock:
        taken = dict(_now)
        _now.clear()
    if not taken:
        return 0
    try:
        return _save(db, taken)
    except Exception:
        db.rollback()
        with _lock:
            for key, row in taken.items():
                was = _now.get(key)
                _now[key] = row if was is None else [*(a + b for a, b in zip(row[:2], was[:2], strict=True)), max(row[2], was[2]),
                                                     *(a + b for a, b in zip(row[3:], was[3:], strict=True))]
        raise


def _save(db: Session, taken: dict) -> int:
    """Each route's numbers added to today's row: the row made first if it isn't there (two copies saving at once both
    make it, one quietly), then locked while it's added to, so both copies' numbers land (issue 157)."""
    from sqlalchemy.dialects.postgresql import insert

    from app.models import RequestTime

    day = config.table_today()
    for (method, route), (count, total, top, db_ms, reads, before_ms, *bands) in sorted(taken.items()):  # (rows locked in one
        # order: two copies saving at once never wait on each other's)
        db.execute(insert(RequestTime).values(day=day, method=method, route=route[:200], count=0, total_ms=0, max_ms=0, db_ms=0, reads=0,
                                              before_ms=0, bands=[0] * (len(BANDS_MS) + 1)).on_conflict_do_nothing())
        row = db.scalar(select(RequestTime).where(RequestTime.day == day, RequestTime.method == method, RequestTime.route == route[:200])
                        .with_for_update())
        row.count += count
        row.total_ms += int(total)
        row.max_ms = max(row.max_ms, int(top))
        row.db_ms = (row.db_ms or 0) + int(db_ms)
        row.reads = (row.reads or 0) + reads
        row.before_ms = (row.before_ms or 0) + int(before_ms)
        row.bands = [a + b for a, b in zip(row.bands or [0] * len(bands), bands, strict=False)]
    db.commit()
    return len(taken)


def _quantile(bands: list[int], q: float, top: float) -> int:
    """Where `q` of the requests have finished, estimated inside its time band: the band's requests spread evenly from its
    lower edge to its upper one (the last band's upper edge, and any band's, is never past `top`, the slowest request).
    Nov 23, the first Monday: the band's upper edge alone read a 0.6 s page as 1 s, over the 0.8 s line."""
    total, seen = sum(bands), 0
    if not total:
        return 0
    want = q * total
    for i, n in enumerate(bands):
        if n and seen + n >= want:
            low = BANDS_MS[i - 1] if i else 0
            high = min(BANDS_MS[i] if i < len(BANDS_MS) else top, top)
            return round(low + (high - low) * (want - seen) / n) if high > low else round(high)
        seen += n
    return round(top)


def week(db: Session, days: int = 7) -> list[dict]:
    """The last `days` days per route, slowest tenth first: {method, route, count, avg_ms, p50_ms, p90_ms, max_ms}."""
    from app.models import RequestTime

    since = config.table_today() - timedelta(days=days - 1)
    acc: dict[tuple[str, str], dict] = {}
    for r in db.scalars(select(RequestTime).where(RequestTime.day >= since)):
        route = CAMPAIGN.sub("/c/{slug}", r.route)  # (rows saved before Nov 20 kept the campaign's name)
        a = acc.setdefault((r.method, route), {"count": 0, "total": 0, "max": 0, "db": 0, "reads": 0, "before": 0,
                                               "bands": [0] * (len(BANDS_MS) + 1)})
        a["count"] += r.count
        a["db"] += r.db_ms or 0
        a["reads"] += r.reads or 0
        a["before"] += r.before_ms or 0
        a["total"] += r.total_ms
        a["max"] = max(a["max"], r.max_ms)
        a["bands"] = [x + y for x, y in zip(a["bands"], r.bands or [0] * len(a["bands"]), strict=False)]  # (a row with none never wipes the rest)
    out = [{"method": m, "route": route, "count": a["count"], "avg_ms": round(a["total"] / a["count"]) if a["count"] else 0,
            "p50_ms": _quantile(a["bands"], .5, a["max"]), "p90_ms": _quantile(a["bands"], .9, a["max"]), "max_ms": a["max"],
            **({"avg_db_ms": round(a["db"] / a["count"]), "avg_reads": round(a["reads"] / a["count"], 1),
                "avg_before_ms": round(a["before"] / a["count"])} if a["count"] else {"avg_db_ms": 0, "avg_reads": 0, "avg_before_ms": 0})}
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
        issue = db.scalar(select(FftIssue).where(FftIssue.title.startswith(title + " ("), FftIssue.state != "closed"))  # (never a longer route that starts the same)
        if issue is None:
            issue = rules.new_issue(db, "askdnd", said[:120], feature="speed", kind="improvement", source="speed")
        else:
            issue.title = said[:120]
        filed.append(issue.id)
    seen = {f"Slow: {r['method']} {r['route']}"[:80]: r for r in rows}
    for issue in db.scalars(select(FftIssue).where(FftIssue.feature == "speed", FftIssue.state != "closed",
                                                   FftIssue.title.startswith("Slow: "), FftIssue.id.not_in(filed or [0]))):
        r = next((v for k, v in seen.items() if issue.title.startswith(k + " (")), None)  # (an open one that isn't slow now)
        nums = f"slowest tenth {r['p90_ms'] / 1000:.1f} s, average {r['avg_ms']} ms, {r['count']} requests." if r else ""
        rules.add_line(db, "askdnd", "Not asked this week." if r is None else f"Too few requests this week to tell: {nums}"
                       if r["p90_ms"] >= SLOW_P90_MS else f"Not slow this week: {nums}", issue=issue)
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
    from app import single
    from app.db import SessionLocal

    with SessionLocal() as db:
        flush(db)
    single.alone(LOCK, lambda db: review(db) if due(db) else None, None)  # (one copy, the look's due day checked inside it)


async def loop() -> None:
    """Started with the app (app/main.py): a save every TICK seconds, the weekly look when it's due; never stops on an error."""
    while True:
        await asyncio.sleep(TICK)
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            log.warning("Saving request times failed this time", exc_info=True)
