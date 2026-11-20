"""Work (app/fft/work_page.py; The Work Pages, Brett's picks Nov 20, docs/mockups/work-pages/): the plans in his order
with the line Claude works down to (Hold puts one below it, and Claude's pick skips it), a plan's page (Overview,
Issues, Test round, Timeline), every check with its devices, scheduled jobs' runs, and How we work drawn from the lanes
file. Testing's old addresses forward here."""

import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import get_db
from app.fft import rules, views, work_page
from app.fft.models import FftArea, FftCheck, FftEvent, FftItem
from app.importer import import_bundle
from app.main import app
from tests.table_setup import BUNDLE

CLAUDE, MINI = "c" * 40, "m" * 40


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


def _plans(db):
    item = FftItem(title="The Roadmap in askdnd", section="now", place=1)
    db.add(item)
    db.flush()
    first, second = (rules.new_area(db, "claude", item, t) for t in ("Battle", "Party"))
    return item, first, second


def _check(db, area, issue=None, title="Rest stays on one line"):
    c = rules.write_check(db, "claude", title=title, steps=["Open the sheet.", "Press [Rest]."], expect="One line.", path="/party",
                          area_id=area.id, issue_ids=[issue.id] if issue else None)
    rules.preflight(db, "claude", c, True)
    db.flush()
    return c


# ------------------------------------------------------------------ the queue and the cut line


def test_the_queue_shows_each_plan_with_its_stage_and_hold_puts_it_below_the_line(db, admin):
    _, battle, party = _plans(db)
    rules.new_issue(db, "claude", "The Count wraps", area_id=battle.id)
    fixing = rules.new_issue(db, "claude", "Party's names cut off", area_id=party.id)
    rules.start_fixing(db, "claude", fixing)
    db.flush()
    page = admin.get("/manage/work").text
    assert re.findall(r'data-area="(\d+)" data-href', page) == [str(battle.id), str(party.id)]  # (in Brett's order)
    assert f'data-area="{battle.id}" data-href="/manage/work/{battle.id}" data-stage="next"' in page  # (Claude's next)
    assert f'data-area="{party.id}" data-href="/manage/work/{party.id}" data-stage="building"' in page
    assert rules.pick_next(db).area.id == battle.id

    admin.post(f"/manage/testing/areas/{battle.id}", data={"do": "hold", "back": "/manage/work"})
    assert battle.held and rules.pick_next(db).area.id == party.id  # (Claude skips a held plan)
    page = admin.get("/manage/work").text
    held = page[page.index("data-held"):]
    assert f'data-area="{battle.id}"' in held and f'data-area="{party.id}"' not in held and 'data-stage="held"' in held
    assert any(why == "held below the line" for _, why in rules.pick_next(db).skipped)
    admin.post(f"/manage/testing/areas/{battle.id}", data={"do": "unhold", "back": "/manage/work"})
    assert not battle.held and rules.pick_next(db).area.id == battle.id
    kinds = [e.kind for e in db.scalars(select(FftEvent).where(FftEvent.area_id == battle.id).order_by(FftEvent.id))]
    assert kinds[-2:] == ["area_held", "area_let_go"]


def test_an_issue_that_stops_bretts_round_marks_its_plan_a_blocker(db, admin):
    _, battle, party = _plans(db)
    c = _check(db, battle, rules.new_issue(db, "claude", "The Count wraps", area_id=battle.id))
    rules.new_issue(db, "claude", "Party's names cut off", area_id=party.id)
    r = rules.open_round(db, "user:1", None)
    rules.record_try(db, "user:1", c, result="failed", round_id=r.id, found=[rules.Found(title="The Count is gone", stops_round=True)])
    db.flush()
    assert rules.pick_next(db).blocker
    page = admin.get("/manage/work").text
    assert f'data-area="{battle.id}" data-href="/manage/work/{battle.id}" data-stage="blocker"' in page


def test_holding_is_brett_only_and_changes_nothing_twice(db, admin, dm, player):
    _, battle, _ = _plans(db)
    db.flush()
    for who in (dm, player):
        who.post(f"/manage/testing/areas/{battle.id}", data={"do": "hold"})
    assert not battle.held
    rules.hold_area(db, "claude", battle, False)  # (already above the line: no event)
    assert not db.scalar(select(FftEvent).where(FftEvent.kind == "area_let_go"))


def test_a_press_on_a_plans_page_comes_back_to_it_and_never_elsewhere(db, admin):
    _, battle, _ = _plans(db)
    db.flush()
    r = admin.post(f"/manage/testing/areas/{battle.id}", data={"do": "hold", "back": f"/manage/work/{battle.id}"}, follow_redirects=False)
    assert r.headers["location"] == f"/manage/work/{battle.id}"
    for back in ("https://elsewhere.example", "//elsewhere.example/manage/work", "/manage/feedback"):
        r = admin.post(f"/manage/testing/areas/{battle.id}", data={"do": "unhold", "back": back}, follow_redirects=False)
        assert r.headers["location"] == "/manage/work", back


# ------------------------------------------------------------------ a plan's page


def test_a_plans_page_has_its_issues_test_round_and_timeline(db, admin):
    _, battle, _ = _plans(db)
    old = rules.new_issue(db, "claude", "Death saves reset", area_id=battle.id)
    passed_before = _check(db, battle, old, title="Death saves stay")
    rules.record_try(db, "user:1", passed_before, result="passed")
    rules.close(db, "claude", old, "works", "It works now.")
    now = rules.new_issue(db, "claude", "The Count wraps", area_id=battle.id)
    current = _check(db, battle, now, title="The Count on one line")
    db.flush()
    page = admin.get(f"/manage/work/{battle.id}").text
    assert 'data-stats' in page and "Battle" in page and 'class="on" data-tab="overview"' in page
    issues = admin.get(f"/manage/work/{battle.id}?tab=issues").text
    assert issues.index(f'data-row="i{now.id}"') < issues.index(f'data-row="i{old.id}"')  # (open first)
    assert f'/manage/item/i{now.id}?from=plan:{battle.id}' in issues
    rnd = admin.get(f"/manage/work/{battle.id}?tab=round").text
    assert rnd.index(f'data-row="c{current.id}"') < rnd.index('data-group="earlier"') < rnd.index(f'data-row="c{passed_before.id}"')
    assert work_page.listed_keys(db, f"round:{battle.id}") == [f"c{current.id}", f"c{passed_before.id}"]
    timeline = admin.get(f"/manage/work/{battle.id}?tab=timeline").text
    assert "data-timeline" in timeline and f"Issue {old.id}: To fix → Closed" in timeline
    assert admin.get("/manage/work/999999").status_code == 404


def test_the_item_window_walks_works_lists(db, admin):
    _, battle, party = _plans(db)
    a, b = _check(db, battle, title="First"), _check(db, party, title="Second")
    db.flush()
    keys = work_page.listed_keys(db, "checks")
    assert keys.index(f"c{a.id}") < keys.index(f"c{b.id}")
    win = admin.get(f"/manage/item/c{a.id}?from=checks").text
    assert f'data-item-next="/manage/item/c{b.id}?from=checks"' in win or f"/manage/item/c{b.id}" in win
    assert "Open in Work" in win
    issue = rules.new_issue(db, "claude", "The Count wraps", area_id=battle.id)
    db.flush()
    win = admin.get(f"/manage/item/i{issue.id}?from=plan:{battle.id}").text
    assert f'href="/manage/work/{battle.id}?tab=issues"' in win  # (Open in its plan, not Feedback)


# ------------------------------------------------------------------ a check follows its issue


def test_a_check_follows_its_issue_into_another_plan_unless_it_tries_others_too(db):
    _, battle, party = _plans(db)
    one = rules.new_issue(db, "claude", "The Count wraps", area_id=battle.id)
    two = rules.new_issue(db, "claude", "The HP box is cramped", area_id=battle.id)
    alone = _check(db, battle, one, title="Only one")
    both = rules.write_check(db, "claude", title="Both", steps=["Look."], expect="Fine.", area_id=battle.id, issue_ids=[one.id, two.id])
    db.flush()
    rules.move_issue(db, "claude", one, party.id)
    db.flush()
    assert alone.area_id == party.id and both.area_id == battle.id  # (it still tries an issue in Battle)
    ev = db.scalar(select(FftEvent).where(FftEvent.kind == "check_moved"))
    assert ev.thing_id == alone.id and views.event_words(ev) == f"Check {alone.id} followed issue {one.id} into this plan"
    rules.move_issue(db, "claude", two, party.id)
    db.flush()
    assert both.area_id == party.id  # (now all it tries is in Party)


# ------------------------------------------------------------------ the other tabs


def test_checks_done_scheduled_and_how_we_work(db, admin, monkeypatch):
    _, battle, party = _plans(db)
    issue = rules.new_issue(db, "claude", "Death saves reset", area_id=party.id)
    c = _check(db, party, issue, title="Death saves stay")
    rules.record_try(db, "user:1", c, result="passed")
    rules.close(db, "claude", issue, "works", "It works now.")
    db.flush()
    checks = admin.get("/manage/work?tab=checks").text
    assert f'data-row="c{c.id}"' in checks and 'data-device="laptop"' in checks and "Passed" in checks
    assert f'data-open-item="/manage/item/c{c.id}?from=checks"' in admin.get(f"/manage/work?tab=checks&open=c{c.id}").text
    done = admin.get("/manage/work?tab=done").text
    assert f'data-area="{party.id}"' in done and f'data-area="{battle.id}"' not in done  # (a batch that never held anything isn't done work)

    sched = admin.get("/manage/work?tab=scheduled").text
    assert sched.count("data-job=") == len(work_page.job_keys()) and "Not reported yet" in sched
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    monkeypatch.setenv("FFT_MINI_KEY", MINI)
    before = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db
    try:
        api = TestClient(app)
        assert api.post("/api/fft/jobs/drift", json={"result": "ok", "words": "No drift"}).status_code == 404  # (no key)
        assert api.post("/api/fft/jobs/drift", headers={"X-Fft-Key": CLAUDE}, json={"result": "ok", "words": "No drift"}).status_code == 200
        assert api.post("/api/fft/jobs/nightly", headers={"X-Fft-Key": MINI}, json={"result": "failed", "words": "2 missed"}).status_code == 200
        assert api.post("/api/fft/jobs/drift", headers={"X-Fft-Key": MINI}, json={"result": "ok"}).status_code == 403  # (the Mini's own only)
        assert api.post("/api/fft/jobs/drift", headers={"X-Fft-Key": CLAUDE}, json={"result": "maybe"}).status_code == 400
        assert api.post("/api/fft/jobs/nope", headers={"X-Fft-Key": CLAUDE}, json={"result": "ok"}).status_code == 400
    finally:
        app.dependency_overrides[get_db] = before
    sched = admin.get("/manage/work?tab=scheduled").text
    drift = sched[sched.index('data-job="drift"'):]
    assert "No drift" in drift[:600] and "OK" in drift[:600]
    nightly = sched[sched.index('data-job="nightly"'):]
    assert "Failed" in nightly[:600] and "2 missed" in nightly[:600]

    how = admin.get("/manage/work?tab=how").text
    for lane in rules.LANES:
        assert f'data-lane-row="{lane}"' in how
    assert "app/access.py" in how  # (drawn from app/data/lanes.json, so it can't drift)


def test_a_standing_rule_work_is_for_admins_only(db, dm, player):
    """A standing rule (Brett, Nov 16: Testing, now Work, is admins'): the DM and a player get no Work page or plan."""
    _, battle, _ = _plans(db)
    db.flush()
    for who in (dm, player):
        for path in ("/manage/work", f"/manage/work/{battle.id}", "/manage/work?tab=checks"):
            r = who.get(path)
            assert r.status_code in (303, 403, 404) or "data-fft-page" not in r.text, path


def test_testing_is_gone_from_backstages_list_and_work_is_there(admin):
    page = admin.get("/manage/work").text
    assert 'data-item="work"' in page and 'data-item="testing"' not in page
    assert 'data-tab="work"' in page and 'data-tab="testing"' not in page and "data-held" in page  # (For you · Work · Feedback)
