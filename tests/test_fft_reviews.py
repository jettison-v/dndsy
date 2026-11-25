"""Workshop's reviews (Roadmap item 46, Brett's picks on docs/mockups/review-catalog/, version 6): the catalog of ten in
six buckets; each run asked, then Starting, Running, Waiting on you, and Done with the same few numbers, Stopped or
Skipped; one at a time and never while Deploys is Paused; a scheduled one asked once for its latest slot within 7 days;
Run… asks only what that review needs."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

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
       "characters": ["Cole"], "device": "phone", "depth": "deep"}


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
    assert a.state == "running" and a.doing == "Battle's attacks for Cole"
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


def test_a_word_where_a_word_is_asked(api):
    """The review of #534: a list where Run… expects a word is refused, never a 500."""
    for bad in ({**DIG, "feature": ["hp"]}, {**DIG, "device": {}}, {**DIG, "depth": 3}):
        assert api.post("/api/fft/reviews/dig_feature/ask", headers=H, json={"inputs": bad}).status_code == 400
    assert api.post("/api/fft/reviews/polish_area/ask", headers=H, json={"inputs": {"area": ["battle"]}}).status_code == 400


def test_a_run_that_ends_while_it_waits_withdraws_its_question(db):
    """Nothing superseded waits on Brett: Stop (or done) on a run waiting on him takes its question out of For you."""
    run = rules.ask_review(db, "claude", "dig_feature", DIG)
    rules.start_review(db, "claude")
    rules.review_on(db, "claude", run, "Elemental forms")
    q = rules.ask(db, "claude", about="review", about_id=run.id, text="Which should askdnd follow?")
    rules.review_waits(db, "claude", run, q)
    rules.stop_review(db, "user:1", run, "Not now")
    assert run.state == "stopped" and q.answered_at is not None and q.answer_text.startswith("Withdrawn")


def test_a_cadence_with_no_slots_turns_its_schedule_off(db):
    rules.set_review(db, "claude", "the_week", scheduled=True)
    row = rules.set_review(db, "claude", "the_week", cadence="on_demand")
    assert row.scheduled is False
    assert rules.set_review(db, "claude", "the_week", cadence="weekly").scheduled is False  # (back to weekly: off until turned on)


# ------------------------------------------------------------------ Development › Scheduled (step 2)


def test_scheduled_lists_each_review_by_bucket_with_how_often_and_next(admin, db):
    sched = admin.get("/manage/work?tab=scheduled").text
    assert sched.count("data-review=") == 10 and sched.count('data-bucket="') == 6
    assert "data-jobs" in sched  # (the jobs stay, under the reviews)
    assert 'data-review="dig_feature"' in sched
    rules.set_review(db, "claude", "the_week", scheduled=True)
    rules.ask_review(db, "user:1", "every_number")
    db.flush()
    sched = admin.get("/manage/work?tab=scheduled").text
    row = sched[sched.index('data-review="every_number"'):][:1500]
    assert 'data-run-state="asked"' in row and 'data-do="review-stop"' in row


def test_run_now_asks_it_and_says_when_it_starts(admin, db):
    win = admin.get("/manage/work/reviews/every_number/run").text
    assert 'data-review-run="every_number"' in win and "data-steps" not in win and 'data-covers="all"' in win
    r = admin.post("/manage/work/reviews/every_number/run", data={}, follow_redirects=False)
    assert r.status_code == 303
    run = db.scalar(select(FftReviewRun).where(FftReviewRun.review == "every_number"))
    assert run.state == "asked" and run.asked_by.startswith("user:")
    again = admin.post("/manage/work/reviews/every_number/run", data={}, follow_redirects=False)  # (already waiting its turn)
    assert again.status_code == 303 and db.scalar(select(func.count()).select_from(FftReviewRun)) == 1


def test_run_dig_into_a_feature_asks_four_steps_and_keeps_what_was_picked(admin, db):
    win = admin.get("/manage/work/reviews/dig_feature/run").text
    assert "data-steps" in win and win.count('role="tab"') == 4 and 'name="feature"' in win and 'name="characters"' in win
    admin.post("/manage/work/reviews/dig_feature/run", data={"feature": ""})
    assert db.scalar(select(FftReviewRun)) is None  # (refused: said in a corner card)
    r = admin.post("/manage/work/reviews/dig_feature/run", data={"feature": "hp", "against": ["books", "house"], "characters": ["Cole"],
                                                                 "device": "phone", "depth": "quick", "words": "It's off by one"},
                   follow_redirects=False)
    assert r.status_code == 303
    run = db.scalar(select(FftReviewRun).where(FftReviewRun.review == "dig_feature"))
    assert run.inputs["against"] == ["books", "house"] and run.inputs["device"] == "phone" and run.inputs["characters"] == ["Cole"]


def test_run_polish_an_area_asks_two_steps(admin, db):
    win = admin.get("/manage/work/reviews/polish_area/run").text
    assert win.count('role="tab"') == 2 and 'name="area"' in win and 'name="devices"' in win
    admin.post("/manage/work/reviews/polish_area/run", data={"area": "battle", "devices": ["laptop", "phone"]})
    assert db.scalar(select(FftReviewRun).where(FftReviewRun.review == "polish_area")).inputs["devices"] == ["laptop", "phone"]


def test_stop_and_the_one_page_result_and_the_panel(admin, db):
    run = rules.ask_review(db, "user:1", "dig_feature", DIG)
    rules.start_review(db, "claude")
    db.flush()
    assert admin.post(f"/manage/work/reviews/runs/{run.id}/stop", follow_redirects=False).status_code == 303
    assert run.state == "stopped"
    done = rules.ask_review(db, "claude", "dig_feature", DIG)
    rules.start_review(db, "claude")
    rules.finish_review(db, "claude", done, RESULT)
    db.flush()
    page = admin.get(f"/manage/work/reviews/runs/{done.id}").text
    assert f'data-review-result="{done.id}"' in page and 'data-found="6"' in page and page.count("<tr>") >= 1
    assert 'href="/manage/item/i94"' in page
    panel = admin.get("/manage/work/reviews/dig_feature").text
    assert 'data-review-panel="dig_feature"' in panel and 'data-found="6"' in panel and 'data-run-state="stopped"' in panel
    assert "Is what askdnd says right?" in panel  # (the words are the point: the product's name, filled in)


def test_reviews_are_admins_only(player, db):
    """A standing rule (Workshop is admins only: Brett, Nov 17): a player can't see, run or stop a review."""
    run = rules.ask_review(db, "claude", "every_number")
    db.flush()
    for url in ("/manage/work/reviews/every_number", "/manage/work/reviews/every_number/run", f"/manage/work/reviews/runs/{run.id}"):
        assert "data-review" not in player.get(url).text
    player.post("/manage/work/reviews/the_week/run", data={})
    player.post(f"/manage/work/reviews/runs/{run.id}/stop")
    assert db.scalar(select(FftReviewRun).where(FftReviewRun.review == "the_week")) is None and run.state == "asked"


# ------------------------------------------------------------------ mutation testing's survivors (the review of #534)


def _pt(*a):
    from app.config import TABLE_TIME

    return datetime(*a, tzinfo=TABLE_TIME)


def test_slots_to_the_minute_on_each_side_of_their_hour():
    assert reviews.slot_before("weekly", _pt(2026, 11, 25, 12, 34, 56, 789)) == _pt(2026, 11, 23, 6, 0)
    assert reviews.slot_before("weekly", _pt(2026, 11, 23, 6, 0)) == _pt(2026, 11, 23, 6, 0)  # (at its slot: that one)
    assert reviews.slot_before("weekly", _pt(2026, 11, 23, 5, 59)) == _pt(2026, 11, 16, 6, 0)  # (Monday before 6: last week's)
    assert reviews.slot_after("weekly", _pt(2026, 11, 23, 5, 59)) == _pt(2026, 11, 23, 6, 0)
    assert reviews.slot_after("weekly", _pt(2026, 11, 23, 6, 0)) == _pt(2026, 11, 30, 6, 0)  # (at its slot: the next one)
    assert reviews.slot_after("weekly", _pt(2026, 11, 25, 9, 30, 15)) == _pt(2026, 11, 30, 6, 0)
    assert reviews.slot_before("monthly", _pt(2026, 11, 25, 9, 30, 15, 1)) == _pt(2026, 11, 1, 4, 0)
    assert reviews.slot_before("monthly", _pt(2026, 12, 1, 4, 0)) == _pt(2026, 12, 1, 4, 0)
    assert reviews.slot_before("monthly", _pt(2026, 12, 1, 3, 59)) == _pt(2026, 11, 1, 4, 0)
    assert reviews.slot_after("monthly", _pt(2026, 12, 1, 3, 59)) == _pt(2026, 12, 1, 4, 0)
    assert reviews.slot_after("monthly", _pt(2026, 12, 1, 4, 0)) == _pt(2027, 1, 1, 4, 0)
    assert reviews.slot_after("monthly", _pt(2026, 1, 31, 23, 0)) == _pt(2026, 2, 1, 4, 0)
    for how in ("phase", "on_demand", "off"):
        assert reviews.slot_before(how, _pt(2026, 11, 25, 12, 0)) is None and reviews.slot_after(how, _pt(2026, 11, 25, 12, 0)) is None


def test_due_needs_a_schedule_and_no_run_since_its_latest_slot(db):
    now = _pt(2026, 12, 3, 12, 0)  # (two days after the 1st's slot)
    slot = _pt(2026, 12, 1, 4, 0)
    assert reviews.due(db, now) == []  # (none scheduled)
    rules.set_review(db, "claude", "every_number", scheduled=True)
    rules.set_review(db, "claude", "test_tests", scheduled=False)
    assert reviews.due(db, now) == ["every_number"]
    early = rules.ask_review(db, "claude", "every_number", how="scheduled")
    early.created_at = slot - timedelta(minutes=1)  # (a run from before the slot doesn't count for it)
    rules.skip_review(db, "claude", early, "Nothing changed")
    db.flush()
    assert reviews.due(db, now) == ["every_number"]
    since = rules.ask_review(db, "claude", "every_number", how="scheduled")
    since.created_at = slot  # (asked at its slot: done for that slot)
    db.flush()
    assert reviews.due(db, now) == []
    rules.set_review(db, "claude", "test_tests", scheduled=True)
    assert "test_tests" in reviews.due(db, slot + reviews.CATCH_UP)  # (a week late to the second: still caught up)
    assert "test_tests" not in reviews.due(db, slot + reviews.CATCH_UP + timedelta(seconds=1))  # (later: skipped till the next)


def test_a_workspace_cadence_overrides_the_catalog(db):
    assert reviews.cadence(db, "every_number") == "monthly"
    rules.set_review(db, "claude", "every_number", cadence="weekly")
    assert reviews.cadence(db, "every_number") == "weekly"
    assert reviews.cadence(db, "test_tests") == "monthly"  # (another review keeps its own)
    rules.set_review(db, "claude", "test_tests", scheduled=False)
    assert reviews.cadence(db, "test_tests") == "monthly"  # (a row with no cadence of its own: the catalog's)
    assert reviews.review("every_number")["title"] == "Check every number" and reviews.review("nope") is None


def _done(db, key, found, **more):
    run = rules.ask_review(db, "claude", key)
    rules.start_review(db, "claude")
    rules.finish_review(db, "claude", run, {"summary": "Checked.", "numbers": {"found": found, "fixed": more.get("fixed", 0),
                                                                              "picks": more.get("picks", 0), "open": more.get("open", 0)}})
    db.flush()
    return run


def test_numbers_over_time_newest_first_with_every_number(db):
    a = _done(db, "every_number", 3, fixed=1, picks=2, open=2)
    b = _done(db, "every_number", 0)
    _done(db, "test_tests", 9)
    rows = reviews.numbers_over_time(db, "every_number")
    assert [r["id"] for r in rows] == [b.id, a.id]
    assert rows[1] == {"id": a.id, "at": a.ended_at, "found": 3, "fixed": 1, "picks": 2, "open": 2}
    assert len(reviews.numbers_over_time(db, "every_number", 1)) == 1
    stopped = rules.ask_review(db, "claude", "every_number")
    rules.stop_review(db, "claude", stopped)
    assert len(reviews.numbers_over_time(db, "every_number")) == 2  # (only finished runs count)
    assert [r.id for r in reviews.runs(db, "every_number")][:1] == [stopped.id]
    assert len(reviews.runs(db, None, 2)) == 2 and len(reviews.runs(db, "test_tests")) == 1


def test_three_quiet_runs_in_a_row_count_from_the_newest(db):
    _done(db, "every_number", 2)
    for _ in range(3):
        _done(db, "every_number", 0)
    assert reviews.quiet_streak(db, "every_number") == 3
    _done(db, "every_number", 1)
    assert reviews.quiet_streak(db, "every_number") == 0
    for _ in range(11):
        _done(db, "test_tests", 0)
    assert reviews.quiet_streak(db, "test_tests") == 10  # (it reads the latest ten)
    assert reviews.quiet_streak(db, "runs_well") == 0


def test_the_live_run_is_the_oldest_that_holds_the_others(db):
    assert reviews.live_run(db) is None
    a = rules.ask_review(db, "claude", "every_number")
    assert reviews.live_run(db) is None  # (asked isn't live)
    rules.start_review(db, "claude")
    assert reviews.live_run(db) is a


def test_a_refused_run_is_a_corner_card_and_polish_needs_its_area(admin, db):
    """The review of #535: a Run or Stop that's refused comes back to Scheduled with its words in a corner card, never
    a bare page; Polish an area's area is required before Next."""
    assert 'name="area" value="battle" required' in admin.get("/manage/work/reviews/polish_area/run").text
    r = admin.post("/manage/work/reviews/polish_area/run", data={"area": ""}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("tab=scheduled")
    assert db.scalar(select(FftReviewRun).where(FftReviewRun.review == "polish_area")) is None


def test_a_run_waiting_behind_its_own_live_one_can_be_stopped(admin, db):
    live = rules.ask_review(db, "user:1", "the_week")
    rules.start_review(db, "claude")
    behind = rules.ask_review(db, "claude", "the_week", how="scheduled")
    db.flush()
    panel = admin.get("/manage/work/reviews/the_week").text
    assert f'data-run="{behind.id}"' in panel and live.state == "starting"
    admin.post(f"/manage/work/reviews/runs/{behind.id}/stop")
    assert behind.state == "stopped" and live.state == "starting"
