"""Each page's time on askdnd.ai, kept, and a weekly look at the slowest (app/speed.py; Performance: the whole tool,
Brett's Roadmap item, step 4, Nov 20)."""

from datetime import timedelta

from sqlalchemy import select

from app import config, speed
from app.fft.models import FftIssue
from app.models import RequestTime, ToolSetting


def _fresh():
    with speed._lock:
        speed._now.clear()


def test_a_routes_times_are_counted_and_saved_by_day_never_with_an_id(db):
    _fresh()
    for ms in (40, 90, 300, 1500):
        speed.record("GET", "/characters/{character_id}/battle", ms)
    speed.record("GET", "/static/app.js", 5)  # (not a page)
    assert speed.flush(db) == 1
    speed.record("GET", "/characters/{character_id}/battle", 6000)
    speed.flush(db)
    row = db.scalar(select(RequestTime).where(RequestTime.route == "/characters/{character_id}/battle"))
    assert (row.count, row.max_ms, row.day) == (5, 6000, config.table_today())
    assert sum(row.bands) == 5 and row.bands[-1] == 1  # (6 s: the band above the last edge)
    assert not db.scalar(select(RequestTime).where(RequestTime.route.like("/static%")))


def test_the_weekly_look_files_a_slow_page_once_and_reports_the_run(db, monkeypatch):
    _fresh()
    for _ in range(30):
        speed.record("GET", "/c/{slug}/party", 1500)
        speed.record("GET", "/help", 30)
    speed.flush(db)
    got = speed.review(db)
    assert [r["route"] for r in got["slow"]] == ["/c/{slug}/party"]
    issue = db.get(FftIssue, got["issues"][0])
    assert issue.title.startswith("Slow: GET /c/{slug}/party") and issue.feature == "speed" and issue.kind == "improvement"
    again = speed.review(db)  # (still slow next week: the same issue, brought up to date)
    assert again["issues"] == got["issues"] and db.scalar(select(FftIssue.id).where(FftIssue.title.like("Slow:%")).order_by(FftIssue.id.desc())) == issue.id
    report = db.get(ToolSetting, "fft_job:speed")
    assert report is not None and "/c/{slug}/party" in report.value


def test_old_rows_go_and_it_runs_on_mondays_once(db, monkeypatch):
    _fresh()
    db.add(RequestTime(day=config.table_today() - timedelta(days=speed.KEEP_DAYS + 1), method="GET", route="/old", count=1, total_ms=1, max_ms=1, bands=[1, 0, 0, 0, 0, 0, 0, 0]))
    db.flush()
    speed.review(db)
    assert not db.scalar(select(RequestTime).where(RequestTime.route == "/old"))
    monday = config.table_today() - timedelta(days=config.table_today().weekday())
    monkeypatch.setattr(config, "table_today", lambda: monday)
    db.merge(ToolSetting(key=speed.LAST, value=""))
    db.flush()
    assert speed.due(db)
    db.merge(ToolSetting(key=speed.LAST, value=monday.isoformat()))
    db.flush()
    assert not speed.due(db)


def test_the_stopwatch_counts_every_request_but_a_held_wait(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app import timing

    _fresh()
    app = FastAPI()

    @app.get("/page/{n}")
    def page(n: int):
        return {}

    @app.get("/held")
    def held():
        with timing.step(timing.HELD):
            pass
        return {}

    app.add_middleware(timing.Stopwatch)
    c = TestClient(app)
    c.get("/page/7")
    c.get("/held")
    assert ("GET", "/page/{n}") in speed._now and ("GET", "/held") in speed._now
    assert not any("7" in route for _, route in speed._now)
    _fresh()
