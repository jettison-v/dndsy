"""Usage Limit Awareness (Roadmap item 34, scope v1 agreed): Claude reads its plan usage before each piece of work and
each pull request (app/fft/rules.py `report_usage`, POST /api/fft/usage); askdnd says go, wait or stop against the
limits Brett sets (`usage_limits`, the Usage menu beside Deploys); over one, no new claim starts (api.py `claim`); each
Roadmap item's share of a week is counted from the readings (`usage_shares`) and written on its result when it ships."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import update

from app import config
from app.db import get_db
from app.fft import rules
from app.fft.models import FftArea, FftEvent, FftItem, FftUsageReading
from app.main import app

CLAUDE = "c" * 40
OWNER = "claude:main"
LIMITS = {"week": 85, "keep": 15, "game_day": None, "extra": 0.0, "window": "pause"}
MON = datetime(2026, 11, 23, 18, tzinfo=UTC)  # (a Monday, 10 AM at the table: the week resets the next Monday)
RESET = MON + timedelta(days=7)


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _verdict(**kw):
    lim = LIMITS | kw.pop("limits", {})
    args = {"five_hour": 10, "week": 50, "extra_spent": 0.0, "five_resets_at": None, "week_resets_at": RESET, "at": MON} | kw
    return rules.usage_verdict(lim, **args)


def test_under_every_limit_it_goes_on_and_says_whats_left():
    verdict, why, cap = _verdict(week=50)
    assert (verdict, cap) == ("go", 85) and "35% of the week left" in why


def test_at_the_weeks_limit_it_stops():
    verdict, why, _ = _verdict(week=85)
    assert verdict == "stop" and "85%" in why


def test_before_game_night_the_week_stops_lower_and_after_it_doesnt():
    """Keep 15% for game night (Brett's limit): before Friday's game the week stops at 85% even if he'd allow 95%;
    once Friday has passed, at 95%."""
    friday = {"week": 95, "keep": 15, "game_day": 4}
    verdict, why, cap = _verdict(week=86, limits=friday)
    assert (verdict, cap) == ("stop", 85) and "kept for game night, Friday" in why
    saturday = MON + timedelta(days=5)
    assert _verdict(week=86, limits=friday, at=saturday)[0] == "go"
    assert _verdict(week=86, limits=friday | {"game_day": None})[0] == "go"  # (no game night known: nothing kept)


def test_extra_usage_past_what_he_allows_stops():
    assert _verdict(extra_spent=0.01)[0] == "stop"  # (never, by default)
    assert _verdict(extra_spent=4.0, limits={"extra": 5.0})[0] == "go"
    assert _verdict(extra_spent=6.0, limits={"extra": 5.0})[0] == "stop"


def test_the_5_hour_window_nearly_full_pauses_or_stops_as_he_chose():
    assert _verdict(five_hour=92)[0] == "wait"
    assert _verdict(five_hour=92, limits={"window": "stop"})[0] == "stop"
    assert _verdict(five_hour=89)[0] == "go"


def test_his_limits_are_checked_and_kept_with_an_event(db):
    with pytest.raises(rules.RuleError):
        rules.set_usage_limits(db, "user:1", 120, 15, None, 0, "pause")
    with pytest.raises(rules.RuleError):
        rules.set_usage_limits(db, "user:1", 80, 15, 9, 0, "pause")
    rules.set_usage_limits(db, "user:1", 80, 10, 4, 5, "stop")
    got = rules.usage_limits(db)
    assert (got["week"], got["keep"], got["game_day"], got["extra"], got["window"]) == (80, 10, 4, 5.0, "stop")
    assert db.query(FftEvent).filter_by(kind="usage_limits").count() == 1


def test_new_work_starts_only_on_a_fresh_reading_that_says_go(db):
    """A standing rule (Brett, item 34: "can you stop if you see a development item that might go over?"): no reading,
    an old one, or one over a limit, and nothing new starts."""
    assert not rules.usage_lets_start(db)[0]
    rules.report_usage(db, "claude", OWNER, 10, 40)
    assert rules.usage_lets_start(db)[0]
    db.execute(update(FftUsageReading).values(created_at=rules.now() - timedelta(minutes=31)))
    assert not rules.usage_lets_start(db)[0]
    r = rules.report_usage(db, "claude", OWNER, 10, 90)
    assert r.verdict == "stop" and rules.usage_lets_start(db) == (False, r.why)


def test_a_changed_verdict_is_an_event_and_a_same_one_isnt(db):
    rules.report_usage(db, "claude", OWNER, 10, 40)
    rules.report_usage(db, "claude", OWNER, 12, 42)
    rules.report_usage(db, "claude", OWNER, 12, 90)
    assert [e.kind for e in db.query(FftEvent).filter(FftEvent.kind.like("usage_%")).order_by(FftEvent.id)] == ["usage_go", "usage_stop"]


def test_a_reading_goes_to_the_claim_held_then(db):
    a = rules.new_issue(db, "claude", "Something to fix", feature="feedback")
    db.flush()
    area = db.get(FftArea, a.area_id)
    assert rules.report_usage(db, "claude", OWNER, 5, 40).area_id is None
    rules.claim(db, OWNER, area)
    r = rules.report_usage(db, "claude", OWNER, 5, 41)
    assert (r.area_id, r.item_id) == (area.id, area.item_id)


def test_each_items_share_is_the_weeks_rise_from_its_readings(db):
    """Between two readings the week rose by so much (or reset and reached the newer one's); that went to the item
    claimed at the first of them."""
    one, two = rules.new_item(db, "claude", "One"), rules.new_item(db, "claude", "Two")
    db.flush()
    reset = rules.now() + timedelta(days=1)
    db.add_all([FftUsageReading(five_hour=1, week=40, item_id=one.id, week_resets_at=reset),
                FftUsageReading(five_hour=1, week=46, item_id=one.id, week_resets_at=reset),  # (+6 to one)
                FftUsageReading(five_hour=1, week=47, item_id=None, week_resets_at=reset),  # (+1 to one: it held the claim before)
                FftUsageReading(five_hour=1, week=50, item_id=two.id, week_resets_at=rules.now() - timedelta(minutes=1)),  # (+3, no one's)
                FftUsageReading(five_hour=1, week=4, item_id=two.id)])  # (the week reset: its 4% went to two)
    db.flush()
    assert rules.usage_shares(db) == {one.id: 7, two.id: 4}


def test_a_shipped_items_result_says_its_share_of_a_week(db):
    item = rules.new_item(db, "claude", "A small idea")
    db.flush()
    db.add_all([FftUsageReading(five_hour=1, week=10, item_id=item.id), FftUsageReading(five_hour=1, week=22)])
    db.flush()
    rules.ship_item(db, "claude", item, result="It did the thing")
    assert item.result.endswith("It used about 12% of a week of Claude's plan.")


def test_claude_reports_a_reading_and_a_claim_waits_for_one(api, db):
    rules.new_issue(db, "claude", "Back clears what you typed", feature="feedback")
    db.flush()
    refused = api.post("/api/fft/claim", headers={"X-Fft-Key": CLAUDE}, json={})
    assert refused.status_code == 409 and "Usage" in refused.json()["detail"]
    got = api.post("/api/fft/usage", headers={"X-Fft-Key": CLAUDE}, json={"five_hour": 3, "week": 53, "extra_spent": 0, "week_resets_at": "2026-12-01T04:00:00Z"}).json()
    assert got["verdict"] == "go"
    assert api.post("/api/fft/claim", headers={"X-Fft-Key": CLAUDE}, json={}).json()["area"]
    assert api.post("/api/fft/usage", headers={"X-Fft-Key": CLAUDE}, json={"five_hour": "lots", "week": 5}).status_code == 400
    state = api.get("/api/fft/usage", headers={"X-Fft-Key": CLAUDE}).json()
    assert state["last"]["week"] == 53 and state["lets_start"]


def test_the_usage_pill_shows_the_week_and_his_limits_set_from_its_menu(admin, db):
    rules.report_usage(db, "claude", OWNER, 3, 53)
    db.commit()
    page = admin.get("/manage/for-you").text
    assert "data-usage-menu" in page and "53% of the week" in page
    r = admin.post("/manage/for-you/usage", data={"week": "80", "keep": "10", "game_day": "4", "extra": "0", "window": "stop", "here": "/manage/work"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/manage/work"
    assert rules.usage_limits(db)["week"] == 80


def test_an_items_page_says_what_it_used_and_what_one_its_size_usually_takes(admin, db):
    done, idea = rules.new_item(db, "claude", "Done before"), rules.new_item(db, "claude", "Next up")
    db.flush()
    done.size = idea.size = "M"
    db.add_all([FftUsageReading(five_hour=1, week=10, item_id=done.id), FftUsageReading(five_hour=1, week=18, item_id=idea.id),
                FftUsageReading(five_hour=1, week=21)])
    db.flush()
    rules.ship_item(db, "claude", done, result="Built it")
    db.commit()
    page = admin.get(f"/manage/roadmap/{idea.id}").text
    assert "About 3% of a week of Claude's plan" in page and "about 8% of a week, from 1 shipped item of size M" in page


def test_a_pause_for_the_5_hour_window_ends_on_the_bar_once_it_has_reset(db):
    from app.fft import testing_page

    rules.report_usage(db, "claude", OWNER, 95, 40, five_resets_at=rules.now() + timedelta(hours=1))
    assert testing_page.usage_bar(db)["tone"] == "wait"
    db.execute(update(FftUsageReading).values(five_resets_at=rules.now() - timedelta(minutes=1)))
    assert testing_page.usage_bar(db)["tone"] != "wait"
