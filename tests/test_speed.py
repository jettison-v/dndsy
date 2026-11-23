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


def test_a_campaigns_pages_are_one_route_and_the_slowest_tenth_never_passes_the_slowest(db):
    """Nov 20, askdnd.ai's first numbers: /c/vtt-test/party kept the campaign's name, and its slowest tenth read 2 s
    when no request took more than 1.45."""
    _fresh()
    for slug in ("main", "vtt-test"):
        for _ in range(10):
            speed.record("GET", f"/c/{slug}/party", 1450)
    speed.flush(db)
    rows = speed.week(db)
    assert [r["route"] for r in rows] == ["/c/{slug}/party"] and rows[0]["count"] == 20
    assert rows[0]["p90_ms"] <= rows[0]["max_ms"] == 1450


def test_the_slowest_tenth_is_estimated_inside_its_band():
    """Nov 23, the first Monday: the band's upper edge alone read a page whose slowest tenth took 0.6 s as 1 s, over the
    0.8 s line, and 25 routes were filed. Inside the band, evenly spread, never past the slowest request."""
    def bands(**at):
        out = [0] * (len(speed.BANDS_MS) + 1)
        for edge, n in at.items():
            out[speed.band(int(edge[1:]))] = n
        return out
    assert speed._quantile(bands(b40=90, b600=10), .9, 620) == 50  # (the 90th of 100 is the last of the fast ones, under 50 ms)
    assert 500 < speed._quantile(bands(b40=80, b600=20), .9, 990) <= 750  # (halfway into 0.5-1 s, not 1 s)
    assert speed._quantile(bands(b600=10), .9, 640) <= 640  # (never past the slowest)
    assert speed._quantile(bands(b9000=10), .9, 9000) <= 9000 and speed._quantile([0] * 8, .9, 0) == 0


def test_a_page_at_0_6_s_is_not_filed_and_an_open_issue_hears_it_wasnt_slow(db):
    from app.fft import rules
    from app.fft.models import FftLine
    _fresh()
    for _ in range(30):
        speed.record("GET", "/c/{slug}/campaign", 600)
        speed.record("GET", "/c/{slug}/campaign/old", 1500)  # (a longer route that starts the same is its own issue)
    for _ in range(5):
        speed.record("GET", "/rare", 1500)  # (slow, but too few to be a finding)
    speed.flush(db)
    old = rules.new_issue(db, "askdnd", "Slow: GET /c/{slug}/campaign (slowest tenth 1.0 s, average 600 ms, 30 requests this week)",
                          feature="speed", kind="improvement")
    gone = rules.new_issue(db, "askdnd", "Slow: GET /gone (slowest tenth 1.0 s, average 900 ms, 30 requests this week)",
                           feature="speed", kind="improvement")
    rare = rules.new_issue(db, "askdnd", "Slow: GET /rare (slowest tenth 1.5 s, average 1500 ms, 25 requests this week)",
                           feature="speed", kind="improvement")
    got = speed.review(db)
    assert [r["route"] for r in got["slow"]] == ["/c/{slug}/campaign/old"] and old.id not in got["issues"]
    said = {x.issue_id: x.text for x in db.scalars(select(FftLine).where(FftLine.issue_id.in_([old.id, gone.id, rare.id])))}
    assert said[old.id].startswith("Not slow this week: slowest tenth 0.6 s") and said[gone.id] == "Not asked this week."
    assert said[rare.id].startswith("Too few requests this week to tell: slowest tenth 1.")


def test_rows_saved_with_a_campaigns_name_count_as_its_page(db):
    """Rows from before Nov 20 kept the campaign's name: /c/vtt-test/party was filed as a page of its own (issue 87)."""
    _fresh()
    db.add(RequestTime(day=config.table_today(), method="GET", route="/c/vtt-test/party", count=5, total_ms=500, max_ms=100,
                       bands=[5, 0, 0, 0, 0, 0, 0, 0]))
    db.commit()
    speed.record("GET", "/c/main/party", 40)
    speed.flush(db)
    rows = speed.week(db)
    assert [(r["route"], r["count"]) for r in rows] == [("/c/{slug}/party", 6)]
    db.add(RequestTime(day=config.table_today() - timedelta(days=1), method="GET", route="/c/{slug}/party", count=1, total_ms=40,
                       max_ms=40, bands=None))  # (a row with no bands never wipes the rest)
    db.commit()
    assert speed.week(db)[0]["p50_ms"] > 0
