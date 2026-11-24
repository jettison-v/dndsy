"""Claims and the Ready order (app/fft/rules.py `claim`, `heartbeat`, `pick_next`, `build_open`; POST /api/fft/claim; the
gaps `pull_unclaimed` and `pull_waiting`; item 39, A sturdier loop, 3 of 4, scope v4, Brett's OK Nov 24): Claude asks
askdnd for work and takes the top of Ready, one at a time; every call is its check-in; a quiet claim goes back to the
front; opening the pull request releases it."""

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app import config
from app.db import get_db
from app.fft import rules, views
from app.fft.models import FftArea, FftEvent
from app.main import app

CLAUDE, MINI = "c" * 40, "m" * 40
OWNER = "claude:main"


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    monkeypatch.setenv("FFT_MINI_KEY", MINI)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _issue(db, title, feature="feedback", **kw):
    i = rules.new_issue(db, "claude", title, feature=feature, **kw)
    db.flush()
    return i


def _pull(db, number, branch, **kw):
    out = rules.pulls_seen(db, "github", [{"number": number, "branch": branch, "state": "open", "title": f"Pull {number}"} | kw])[0]
    db.flush()
    return out


def test_claude_takes_the_top_of_ready_and_only_one_piece_at_a_time(api, db):
    """A standing rule (item 39, Brett Nov 23: "never have you starting on something too early, being busy when you
    shouldn't"): askdnd hands over the top, records it, and gives the same one back until it's released."""
    first = _issue(db, "Back clears what you typed")
    _issue(db, "The corner card stays over the panel", feature="hp")
    got = api.post("/api/fft/claim", headers={"X-Fft-Key": CLAUDE}, json={}).json()
    assert got["area"] == first.area_id and not got["already"]
    assert db.get(FftArea, first.area_id).lock_owner == OWNER
    again = api.post("/api/fft/claim", headers={"X-Fft-Key": CLAUDE}, json={}).json()
    assert (again["area"], again["already"]) == (first.area_id, True)
    assert api.post("/api/fft/claim", headers={"X-Fft-Key": MINI}, json={}).status_code == 403
    assert api.post("/api/fft/claim", headers={"X-Fft-Key": CLAUDE}, json={"release": True}).json()["released"] == first.area_id
    assert db.get(FftArea, first.area_id).lock_owner == ""


def test_a_claim_that_goes_quiet_returns_to_the_front_of_ready(db):
    """A session that stops leaves its claim; 20 minutes without a check-in and it's first in line again, ahead of the
    queue's order, branch and all."""
    first, second = _issue(db, "First in the queue"), _issue(db, "Second in the queue", feature="hp")
    area = db.get(FftArea, second.area_id)
    rules.lock_area(db, OWNER, area)
    assert rules.pick_next(db).area.id == first.area_id  # (a live claim is in hand: not Ready)
    area.lock_until = rules.now() - timedelta(minutes=1)
    pick = rules.pick_next(db)
    assert (pick.area.id, pick.reason) == (second.area_id, "quiet_claim")
    got, _, already = rules.claim(db, "claude:other", None)
    assert got.id == second.area_id and not already and area.lock_owner == "claude:other"


def test_a_fix_to_what_just_shipped_goes_ahead_of_new_work(db):
    """An issue Brett's try filed (Something's wrong…) is Ready at once, ahead of the queue's order."""
    from app.fft.models import FftTry

    _issue(db, "First in the queue")
    check = rules.write_check(db, "claude", title="t", steps=["s"], expect="e")
    tried = FftTry(check_id=check.id, version=1, actor="person", result="failed")
    db.add(tried)
    db.flush()
    later = _issue(db, "Found on a try", feature="hp", origin_try_id=tried.id)
    pick = rules.pick_next(db)
    assert (pick.area.id, pick.reason) == (later.area_id, "shipped_fix")


def test_a_sessions_own_listener_is_its_check_in(api, db):
    """Its listener's inbox and wait run in the background all the while it works (a long test run too): its claim runs
    another 20 minutes. Another session's listener never keeps it alive, a lapsed claim isn't revived, and the Mini's
    key checks no one in."""
    area = db.get(FftArea, _issue(db, "Back clears what you typed").area_id)
    rules.lock_area(db, OWNER, area)

    def left_after(path, key=CLAUDE):
        area.lock_until = rules.now() + timedelta(minutes=3)
        db.flush()
        api.get(path, headers={"X-Fft-Key": key})
        db.refresh(area)
        return area.lock_until - rules.now()

    assert left_after("/api/fft/inbox/wait?listener=main&seconds=1") > timedelta(minutes=19)
    assert left_after("/api/fft/inbox?listener=main&peek=1") > timedelta(minutes=19)
    assert left_after("/api/fft/inbox/wait?listener=sweep&seconds=1") < timedelta(minutes=4)  # (another session's)
    assert left_after("/api/fft/gaps") < timedelta(minutes=4)
    area.lock_until = rules.now() - timedelta(minutes=1)
    db.flush()
    api.get("/api/fft/inbox/wait?listener=main&seconds=1", headers={"X-Fft-Key": CLAUDE})
    db.refresh(area)
    assert area.lock_until < rules.now()


def test_opening_the_pull_request_releases_the_claim_and_one_for_unclaimed_work_is_a_gap(db):
    """Building → Shipping: the claim is given back the moment its pull request opens. One opened for work nobody
    claimed is a gap until the plan is claimed; Dependabot's and Upkeep are no one's to claim."""
    claimed, loose = _issue(db, "Claimed first"), _issue(db, "Nobody claimed this", feature="hp")
    a = db.get(FftArea, claimed.area_id)
    rules.lock_area(db, OWNER, a)
    p1 = _pull(db, 300, f"a{a.id}-fix")
    assert a.lock_owner == "" and not p1.unclaimed
    assert db.scalar(select(FftEvent.data).where(FftEvent.kind == "area_unlocked").order_by(FftEvent.id.desc()))["by_pull"] == 300
    p2 = _pull(db, 301, f"a{loose.area_id}-fix")
    p3 = _pull(db, 302, "dependabot/uv/x", by_bot=True)
    p4 = _pull(db, 303, "phone-sweep")
    assert (p2.unclaimed, p3.unclaimed, p4.unclaimed) == (True, False, False)
    assert {g["title"].split()[0] for g in views.gaps(db) if g["kind"] == "pull_unclaimed"} == {"#301"}
    rules.claim(db, OWNER, db.get(FftArea, loose.area_id))
    assert not p2.unclaimed
    rules.unlock_area(db, OWNER, db.get(FftArea, loose.area_id))
    it = rules.new_item(db, "claude", "A build", section="now")
    db.flush()
    plan = rules.new_area(db, "claude", it, "A build: the build")
    db.flush()
    p5 = _pull(db, 304, f"r{it.id}-board")
    assert p5.unclaimed  # (an item's branch, nothing claimed)
    rules.claim(db, OWNER, plan)
    assert not p5.unclaimed  # (claiming the item's plan claims it)


def test_a_green_pull_request_that_isnt_merging_is_a_gap(db):
    """GitHub turned auto-merge off on #481 with a race the moment its tests passed (Nov 24): passed, clean and not set
    to merge is Claude's to finish, unless it's meant to wait (Careful, Brett's open round, the pause)."""
    i = _issue(db, "Back clears what you typed")
    _pull(db, 310, f"a{i.area_id}-fix", tests="passed", merge_state="clean", auto_merge=False)
    _pull(db, 311, "phone-sweep", tests="passed", merge_state="clean", auto_merge=True)
    assert {g["title"].split()[0] for g in views.gaps(db) if g["kind"] == "pull_waiting"} == {"#310"}
    rules.set_lane(db, "user:1", db.get(FftArea, i.area_id), "careful", "Brett chose it", admin=True)
    assert not [g for g in views.gaps(db) if g["kind"] == "pull_waiting"]
    rules.set_lane(db, "user:1", db.get(FftArea, i.area_id), "look", "Brett chose it", admin=True)
    assert [g for g in views.gaps(db) if g["kind"] == "pull_waiting"]
    rules.set_available(db, "user:1", True, by="Brett")  # (Deploys: After my local try)
    rules.new_local_try(db, "claude", "Try it on your Mac", db.get(FftArea, i.area_id), ["c"], "l", "/", "x")
    assert not [g for g in views.gaps(db) if g["kind"] == "pull_waiting"]  # (After my local try: it waits for his)


def test_one_set_to_merge_that_falls_behind_main_is_claudes_to_bring_up_to_date(db):
    """Nov 24, #485: GitHub's robot brought it up to date and its tests waited for a person's approval, so it never
    merged. Behind main and set to merge is Claude's to update (under a person's sign-in), unless it's meant to wait."""
    i = _issue(db, "Back clears what you typed")
    _pull(db, 320, f"a{i.area_id}-fix", tests="passed", merge_state="behind", auto_merge=True)
    _pull(db, 321, "phone-sweep", tests="passed", merge_state="behind", auto_merge=False)  # (not set to merge: it waits as it is)
    behind = [g for g in views.gaps(db) if g["kind"] == "pull_behind"]
    assert [g["title"].split()[0] for g in behind] == ["#320"] and "gh pr update-branch 320" in behind[0]["says"]
    rules.set_lane(db, "user:1", db.get(FftArea, i.area_id), "careful", "Brett chose it", admin=True)
    assert not [g for g in views.gaps(db) if g["kind"] == "pull_behind"]
    _pull(db, 322, "dependabot/uv/x", by_bot=True, merge_state="behind", auto_merge=True)  # (Dependabot rebases its own)
    assert "dependabot rebase" in next(g["says"] for g in views.gaps(db) if g["kind"] == "pull_behind")


def test_a_builds_plan_with_claudes_steps_left_never_vanishes(db):
    """Area 17 showed as done and left Development, its lane control with it (Nov 24): a build's plan with no issues
    is Claude's while its item's scope is agreed, it isn't shipped and a step of Claude's is open."""
    it = rules.new_item(db, "claude", "A sturdier loop", section="now")
    db.flush()
    plan = rules.new_area(db, "claude", it, "A sturdier loop: the build")
    db.flush()
    assert rules.area_turn(db, plan) == "done"  # (no agreed scope yet)
    rules.write_scope(db, "claude", it, what="w", inside=["i"])
    rules.agree_scope(db, "user:1", it)
    rules.add_step(db, "claude", it, "Build 3 of 4")
    db.flush()
    assert rules.area_turn(db, plan) == "claude"
    it.next_whose = "brett"  # (its next step is Brett's: it waits on him, whatever comes after)
    assert rules.area_turn(db, plan) == "done"
    it.next_whose = "claude"
    rules.add_step(db, "claude", it, "Brett's own", whose="brett")
    db.execute(update(rules.FftStep).where(rules.FftStep.item_id == it.id, rules.FftStep.whose != "brett").values(done_at=rules.now()))
    db.flush()
    assert rules.area_turn(db, plan) == "done"  # (only Brett's step left: not Claude's)


def test_a_build_with_no_plan_gets_one_when_claimed(db):
    it = rules.new_item(db, "claude", "Something agreed", section="now")
    db.flush()
    rules.write_scope(db, "claude", it, what="w", inside=["i"])
    rules.agree_scope(db, "user:1", it)
    rules.add_step(db, "claude", it, "Build it")
    db.flush()
    got, why, _ = rules.claim(db, OWNER, None)
    assert got is not None and got.item_id == it.id and got.lock_owner == OWNER


def test_a_claim_lasts_twenty_minutes_without_a_check_in():
    assert timedelta(minutes=20) == rules.LOCK


def test_a_build_brett_holds_never_jumps_the_line(db):
    """A fix to what just shipped goes first, but not from a build Brett holds below the line."""
    from app.fft.models import FftTry

    it = rules.new_item(db, "claude", "Held build", section="now")
    db.flush()
    plan = rules.new_area(db, "claude", it, "Held build: the build")
    db.flush()
    check = rules.write_check(db, "claude", title="t", steps=["s"], expect="e")
    tried = FftTry(check_id=check.id, version=1, actor="person", result="failed")
    db.add(tried)
    db.flush()
    rules.new_issue(db, "claude", "Found on a try", area_id=plan.id, origin_try_id=tried.id)
    db.flush()
    assert rules.pick_next(db).reason == "shipped_fix"
    it.held = True
    db.flush()
    assert rules.pick_next(db).reason != "shipped_fix"


def test_the_listener_hears_news_not_its_own_sessions_or_routine_jobs(db):
    """Nov 24: the listener woke every few minutes for its own claims ("claude:main") and GitHub's routine job reports;
    a failed job and anything a person did still wake it."""
    from app.fft.models import FftEvent

    said = [FftEvent(actor="claude:main", kind="area_locked", thing="area", thing_id=1, data={}),
            FftEvent(actor="github", kind="job_ran", thing="tool", thing_id=0, data={"job": "drift", "result": "ok"}),
            FftEvent(actor="github", kind="job_ran", thing="tool", thing_id=0, data={"job": "drift", "result": "failed"}),
            FftEvent(actor="user:1", kind="question_answered", thing="question", thing_id=3, data={})]
    assert [rules.heard(e, "claude") for e in said] == [False, False, True, True]
