"""Times of day (templating.py `clock`): the server keeps UTC and writes it, marked for the page to show in the
reader's own zone (app.js "clocks"; tests/browser/test_clocks.py)."""

from datetime import UTC, datetime, timedelta, timezone

from app.templating import _clock


def test_a_time_is_written_in_utc_for_the_page_to_turn():
    at = datetime(2026, 10, 30, 1, 22, tzinfo=UTC)
    assert str(_clock(at)) == '<time datetime="2026-10-30T01:22:00+00:00" data-clock="time">1:22 AM UTC</time>'
    assert _clock(at.isoformat()) == _clock(at) == _clock(at.timestamp())  # as JSON or the bridge's own clock carry it
    assert _clock(at.astimezone(timezone(timedelta(hours=-7)))) == _clock(at)
    assert 'data-clock="date">Oct 30, 2026, 1:22 AM UTC<' in _clock(at, date=True)
    assert _clock(None) == ""


def test_the_bridge_page_shows_its_times_that_way(admin, sheet):
    page = admin.get("/manage/bridge")
    assert page.status_code == 200 and 'data-clock="time"' in page.text and " UTC</time>" in page.text
