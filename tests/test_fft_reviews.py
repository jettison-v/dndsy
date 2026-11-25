"""Workshop's reviews (Roadmap item 46, Brett's picks on docs/mockups/review-catalog/, version 6): the catalog of ten in
six buckets; each run asked, then Starting, Running, Waiting on you, and Done with the same few numbers, Stopped or
Skipped; one at a time and never while Deploys is Paused; a scheduled one asked once for its latest slot within 7 days;
Run… asks only what that review needs."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import get_db
from app.fft import reviews, rules, views
from app.fft.models import FftEvent, FftReviewRun
from app.main import app

CLAUDE = "c" * 40
RESULT = {"summary": "Wild Shape checked against the books and Cole's sheet.", "covered": "A laptop", "missed": "A phone",
          "findings": [{"what": "Temporary Hit Points not shown", "became": "Issue 94", "ref": "i94"}],
          "numbers": {"found": 6, "fixed": 2, "picks": 1, "open": 4}}
DIG = {"feature": "hp", "issues": [92], "words": "Cole can't pick Elemental forms", "against": ["books", "sheet"],
       "characters": ["Cole"], "device": "laptop", "depth": "deep"}


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


H = {"X-Fft-Key": CLAUDE}


def test_the_catalog_is_ten_reviews_in_six_buckets_as_picked():
    cat = reviews.catalog()
    assert [b["key"] for b in cat["buckets"]] == ["experience", "correctness", "code", "trust", "running", "how"]
    assert len(cat["reviews"]) == 10
    assert len(set(reviews.keys())) == 10
    for r in cat["reviews"]:
        assert r["bucket"] in {b["key"] for b in cat["buckets"]}
        assert r["cadence"] in reviews.CADENCES
        assert r["launch"] in ("now", "polish", "dig")
        assert r["title"] and r["gets"] and r["does"] and r["limit"] > 0
    picked = {r["key"]: r["cadence"] for r in cat["reviews"]}
    assert picked["dig_feature"] == picked["polish_area"] == "on_demand"
    assert picked["the_week"] == "weekly"
    assert picked["rethink_build"] == picked["who_sees"] == "phase"


def test_slots_weekly_on_monday_morning_and_monthly_on_the_first():
    t = datetime(2026, 11, 25, 20, 0, tzinfo=UTC)  # (a Wednesday, noon at the table)
    wk = reviews.slot_before("weekly", t)
    assert (wk.weekday(), wk.hour, wk.day) == (0, 6, 23)
    assert reviews.slot_after("weekly", t).day == 30
    mo = reviews.slot_before("monthly", t)
    assert (mo.day, mo.hour, mo.month) == (1, 4, 11)
    assert (reviews.slot_after("monthly", t).day, reviews.slot_after("monthly", t).month) == (1, 12)
    early = datetime(2026, 12, 1, 10, 0, tzinfo=UTC)  # (the 1st at 2:00 at the table: before its slot)
    assert reviews.slot_before("monthly", early).month == 11
    assert reviews.slot_before("phase", t) is None and reviews.slot_after("on_demand", t) is None


def test_a_scheduled_review_is_asked_once_for_its_latest_slot_within_seven_days(db):
    rules.set_review(db, "claude", "the_week", scheduled=True)
    now = rules.now()
    assert reviews.due(db, now) == ["the_week"]
    rules.ask_review(db, "claude", "the_week", how="scheduled")
    assert reviews.due(db, now) == []  # (asked: not again for the same slot)
    rules.set_review(db, "claude", "every_number", scheduled=True)
    late = reviews.slot_before("monthly", now) + reviews.CATCH_UP + timedelta(hours=1)
    assert "every_number" not in reviews.due(db, late)  # (a slot older than a week is skipped)


def test_only_a_weekly_or_monthly_review_has_a_schedule(db):
    with pytest.raises(rules.RuleError):
        rules.set_review(db, "claude", "dig_feature", scheduled=True)
    with pytest.raises(rules.RuleError):
        rules.ask_review(db, "claude", "dig_feature", DIG, how="scheduled")
    with pytest.raises(rules.RuleError):
        rules.set_review(db, "claude", "the_week", cadence="daily")


def test_run_asks_only_what_that_review_needs(db):
    with pytest.raises(rules.RuleError, match="feature"):
        rules.ask_review(db, "claude", "dig_feature", {})
    with pytest.raises(rules.RuleError, match="against"):
        rules.ask_review(db, "claude", "dig_feature", {**DIG, "against": ["rumours"]})
    with pytest.raises(rules.RuleError, match="area"):
        rules.ask_review(db, "claude", "polish_area", {"area": "nowhere"})
    run = rules.ask_review(db, "claude", "dig_feature", DIG)
    assert run.inputs["feature"] == "hp" and run.inputs["against"] == ["books", "sheet"]
    polish = rules.ask_review(db, "claude", "polish_area", {"area": "battle", "devices": ["laptop", "phone"]})
    assert polish.inputs == {"area": "battle", "focus": "", "devices": ["laptop", "phone"]}
    assert rules.ask_review(db, "claude", "every_number", {"anything": 1}).inputs == {}  # (Run now asks nothing)
    with pytest.raises(rules.RuleError, match="waiting its turn"):
        rules.ask_review(db, "claude", "every_number")


def test_one_at_a_time_and_never_while_deploys_is_paused(db):
    a = rules.ask_review(db, "claude", "every_number")
    b = rules.ask_review(db, "claude", "test_tests")
    rules.set_freeze(db, "claude", True, by="Brett", why="Game night")
    assert rules.start_review(db, "claude") is None
    rules.set_freeze(db, "claude", False)
    assert rules.start_review(db, "claude") is a and a.state == "starting"
    assert rules.start_review(db, "claude") is None  # (b waits its turn)
    rules.review_on(db, "claude", a, "Battle's attacks for Cole")
    assert a.state == "running" and a.on == "Battle's attacks for Cole"
    rules.finish_review(db, "claude", a, RESULT)
    assert rules.start_review(db, "claude") is b


def test_waiting_on_brett_carries_on_once_he_answers(db):
    run = rules.ask_review(db, "claude", "dig_feature", DIG)
    rules.start_review(db, "claude")
    rules.review_on(db, "claude", run, "Elemental forms")
    q = rules.ask(db, "claude", about="review", about_id=run.id, text="Which should askdnd follow at this table?",
                  choices=[{"label": "The house rule", "detail": ""}, {"label": "D&D Beyond", "detail": ""}])
    rules.review_waits(db, "claude", run, q)
    assert run.state == "waiting" and run.question_id == q.id
    rules.answer(db, "user:1", q, choice=0)
    assert run.state == "running"


def test_done_keeps_one_page_and_the_same_numbers_every_run(db):
    run = rules.ask_review(db, "claude", "every_number")
    rules.start_review(db, "claude")
    with pytest.raises(rules.RuleError, match="summary"):
        rules.finish_review(db, "claude", run, {"numbers": RESULT["numbers"]})
    with pytest.raises(rules.RuleError, match="numbers"):
        rules.finish_review(db, "claude", run, {**RESULT, "numbers": {"found": -1}})
    rules.finish_review(db, "claude", run, RESULT)
    assert run.state == "done" and run.ended_at is not None
    assert run.result["numbers"] == {"found": 6, "fixed": 2, "picks": 1, "open": 4}
    assert reviews.numbers_over_time(db, "every_number")[0]["found"] == 6
    assert reviews.quiet_streak(db, "every_number") == 0
    with pytest.raises(rules.RuleError, match="can't be"):
        rules.stop_review(db, "claude", run)  # (done is done)


def test_stopped_and_skipped_say_why(db):
    a = rules.ask_review(db, "claude", "the_week")
    rules.skip_review(db, "claude", a, "No merged change since the last run")
    assert a.state == "skipped" and a.why.startswith("No merged")
    b = rules.ask_review(db, "claude", "the_week")
    rules.start_review(db, "claude")
    rules.stop_review(db, "user:1", b, "Not tonight")
    assert b.state == "stopped" and b.why == "Not tonight"
    kinds = [e.kind for e in db.scalars(select(FftEvent).where(FftEvent.thing == "review").order_by(FftEvent.id))]
    assert kinds == ["review_asked", "review_skipped", "review_asked", "review_starting", "review_stopped"]


def test_the_inbox_says_a_review_was_asked(db):
    run = rules.ask_review(db, "user:1", "dig_feature", DIG)
    ev = db.scalar(select(FftEvent).where(FftEvent.kind == "review_asked", FftEvent.thing_id == run.id))
    assert "Dig into a feature asked" in views.event_words(ev)


def test_the_api_runs_a_review_end_to_end(api, db):
    assert api.get("/api/fft/reviews").status_code == 404  # (no key, no API)
    got = api.post("/api/fft/reviews/dig_feature/ask", headers=H, json={"inputs": DIG})
    assert got.status_code == 200, got.text
    run_id = got.json()["run"]["id"]
    assert api.post("/api/fft/reviews/dig_feature/ask", headers=H, json={"inputs": {"feature": "nope"}}).status_code == 400
    nxt = api.post("/api/fft/reviews/next", headers=H).json()
    assert nxt["run"]["id"] == run_id and nxt["run"]["state"] == "starting"
    assert api.post("/api/fft/reviews/next", headers=H).json() == {"run": None, "why": "another review is running"}
    assert api.post(f"/api/fft/reviews/runs/{run_id}", headers=H, json={"do": "on", "words": "Wild Shape forms"}).json()["run"]["state"] == "running"
    assert api.post(f"/api/fft/reviews/runs/{run_id}", headers=H, json={"do": "fly"}).status_code == 400
    done = api.post(f"/api/fft/reviews/runs/{run_id}", headers=H, json={"do": "done", "result": RESULT})
    assert done.json()["run"]["state"] == "done"
    listed = api.get("/api/fft/reviews", headers=H).json()
    assert next(r for r in listed["reviews"] if r["key"] == "dig_feature")["last"]["state"] == "done"
    assert api.post("/api/fft/reviews/the_week/set", headers=H, json={"scheduled": True}).status_code == 200
    assert api.post("/api/fft/reviews/due", headers=H).json()["asked"]
    assert db.scalar(select(FftReviewRun).where(FftReviewRun.review == "the_week")).how == "scheduled"
