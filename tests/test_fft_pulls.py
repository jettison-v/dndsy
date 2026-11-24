"""Pull requests as GitHub reports them (app/fft/rules.py `pulls_seen`, POST /api/fft/github/pulls, GET /api/fft/pulls,
the two gaps; item 39, A sturdier loop, scope v4, Brett's OK Nov 24): no pull request without a card, each linked to
its work, a red or conflicting one in Claude's hands."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import get_db
from app.fft import keys, rules, views
from app.fft.models import FftArea, FftEvent, FftKey, FftPull
from app.main import app

CLAUDE, RELAY, MINI = "c" * 40, "r" * 40, "m" * 40
URL = "https://github.com/jettison-v/dndsy/pull/"


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    monkeypatch.setenv("FFT_RELAY_KEY", RELAY)
    monkeypatch.setenv("FFT_MINI_KEY", MINI)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def github(db):
    key = keys.make(db, "GitHub", "github")
    db.flush()
    return {"X-Fft-Key": key}


def _pr(number, branch="some-work", **kw):
    return {"number": number, "title": f"Pull {number}", "branch": branch, "state": "open", "tests": "running",
            "merge_state": "blocked", "auto_merge": True, "head": "a" * 40} | kw


def _seen(db, *rows, snapshot=False):
    out = rules.pulls_seen(db, "github", list(rows), snapshot=snapshot)
    db.flush()
    return out


def test_only_githubs_key_reports_pull_requests_and_it_reads_nothing(api, db, github):
    """A standing rule (the audit, Nov 17; T6): each key does only its own job. GitHub's may report pull requests and
    its jobs, and read nothing; Claude's reads them and can't report them; staging's and the Mini's can do neither."""
    body = {"pulls": [_pr(480)], "snapshot": True}
    assert api.post("/api/fft/github/pulls", json=body).status_code == 404
    for key in (CLAUDE, RELAY, MINI):
        assert api.post("/api/fft/github/pulls", headers={"X-Fft-Key": key}, json=body).status_code == 403
    got = api.post("/api/fft/github/pulls", headers=github, json=body)
    assert got.status_code == 200 and got.json()["seen"] == [480]
    assert api.get("/api/fft/pulls", headers=github).status_code == 403
    assert api.get("/api/fft/notes", headers=github).status_code == 403
    listed = api.get("/api/fft/pulls", headers={"X-Fft-Key": CLAUDE}).json()["items"]
    assert [(x["number"], x["upkeep"], x["tests"]) for x in listed] == [(480, True, "running")]


def test_a_key_for_github_made_before_today_still_reports_only_its_jobs(db):
    """The drift job's key (Nov 21) was made with only "jobs": it isn't given pull requests by this change; a new key is."""
    db.add(FftKey(name="old", key_hash=keys.digest("o" * 40), actor="github", scopes=["jobs"]))
    db.flush()
    assert not keys.actor_for(db, "o" * 40).may("pulls")
    assert keys.actor_for(db, keys.make(db, "new", "github")).may("pulls")


def test_each_is_linked_to_its_work_by_its_branch_else_by_the_issue_that_names_it(db):
    """`a12-…` an area, `i110-…` an issue, `r39-…` a Roadmap item; else an issue whose pull request it is; else nothing,
    an Upkeep card (Dependabot's always)."""
    issue = rules.new_issue(db, "claude", "Back clears what you typed", feature="feedback")
    db.flush()
    item = rules.new_item(db, "claude", "A sturdier loop")
    db.flush()
    by_issue, by_area, plain, bot = _seen(db, _pr(1, f"i{issue.id}-back"), _pr(2, f"a{issue.area_id}-batch"), _pr(3, "phone-sweep"),
                                         _pr(4, "dependabot/uv/minor", by_bot=True))
    assert (by_issue.issue_id, by_issue.area_id) == (issue.id, issue.area_id)
    assert by_issue.item_id == by_area.item_id == db.get(FftArea, issue.area_id).item_id
    assert (by_area.issue_id, by_area.area_id) == (None, issue.area_id)
    assert rules.pull_upkeep(plain) and rules.pull_upkeep(bot) and bot.by_bot
    by_item = _seen(db, _pr(5, f"r{item.id}-github"))[0]
    assert (by_item.issue_id, by_item.area_id, by_item.item_id) == (None, None, item.id)
    # (an issue that names it later links it on GitHub's next report; a branch mark for something that isn't there doesn't)
    rules.fix_ready(db, "claude", issue, URL + "3")
    db.flush()
    assert _seen(db, _pr(3, "phone-sweep"))[0].issue_id == issue.id
    assert rules.pull_upkeep(_seen(db, _pr(6, "i99999-gone"))[0])
    assert not _seen(db, _pr(47, "other"))[0].issue_id  # (pull/3 isn't pull/47's prefix the other way round either)


def test_each_change_is_recorded_once_and_a_whole_list_closes_what_left_it(db):
    """The round trip reads the events: one when it first appears, one per change, none when nothing changed. A whole
    list (snapshot) of the open ones closes any this record held open that isn't on it; a closed one keeps its tests."""
    _seen(db, _pr(10), _pr(11))
    _seen(db, _pr(10), _pr(11))  # (nothing new)
    _seen(db, _pr(10, tests="passed"), _pr(11))
    evs = list(db.scalars(select(FftEvent).where(FftEvent.thing == "pull").order_by(FftEvent.id)))
    assert [e.kind for e in evs] == ["pull_new", "pull_new", "pull_changed"]
    assert evs[-1].data["changes"] == {"tests": "passed"}
    _seen(db, {"number": 10, "state": "merged"}, _pr(12), snapshot=True)
    rows = {p.number: p for p in db.scalars(select(FftPull))}
    assert (rows[10].state, rows[10].tests) == ("merged", "passed") and rows[10].closed_at is not None
    assert rows[11].state == "closed" and rows[12].state == "open"


def test_a_red_or_conflicting_pull_request_is_in_claudes_hands(db):
    """Gaps (Brett, Nov 17): a pull request whose tests failed, or that conflicts with main, waits on Claude; behind
    main isn't one (GitHub's run brings it up to date), nor is a closed one."""
    _seen(db, _pr(20, tests="failed"), _pr(21, merge_state="dirty"), _pr(22, merge_state="behind"), _pr(23, tests="passed"))
    got = {(g["kind"], g["title"].split()[0]) for g in views.gaps(db) if g["thing"] == "pull"}
    assert got == {("pull_red", "#20"), ("pull_conflicts", "#21")}
    _seen(db, {"number": 20, "state": "closed"})
    assert ("pull_red", "#20") not in {(g["kind"], g["title"].split()[0]) for g in views.gaps(db) if g["thing"] == "pull"}


def test_a_report_askdnd_cant_read_changes_nothing(api, db, github):
    """A bad report is refused whole, never half kept."""
    for body in ({"pulls": "x"}, {"pulls": [_pr(30), _pr(30)]}, {"pulls": [_pr(31, state="weird")]}, {"pulls": [_pr(0)]},
                 {"pulls": [_pr(32, tests="maybe")]}, {"pulls": [{"title": "no number"}]}, {"pulls": [_pr(n) for n in range(1, 202)]}):
        assert api.post("/api/fft/github/pulls", headers=github, json=body).status_code == 400, body
    db.expire_all()
    assert db.scalar(select(FftPull.id)) is None


def test_brought_up_to_date_is_recorded(db):
    """GitHub's run merged main into it: when, for the round trip and the board."""
    p = _seen(db, _pr(40, merge_state="behind"))[0]
    assert p.updated_by_askdnd_at is None
    p = _seen(db, _pr(40, merge_state="", tests="running") | {"updated": True})[0]
    assert p.updated_by_askdnd_at is not None
    assert db.scalar(select(FftEvent).where(FftEvent.thing == "pull").order_by(FftEvent.id.desc())).data["changes"]["updated"] is True


def test_a_reopened_one_is_open_again_and_a_closed_one_keeps_githubs_time(db):
    p = _seen(db, {"number": 50, "state": "closed", "closed_at": "2026-11-20T10:00:00Z"})[0]
    assert p.closed_at.isoformat().startswith("2026-11-20T10:00:00")
    p = _seen(db, _pr(50))[0]
    assert (p.state, p.closed_at) == ("open", None)
    with pytest.raises(rules.RuleError):
        _seen(db, {"number": 51, "state": "closed", "closed_at": "yesterday"})


def test_a_red_one_is_late_from_when_its_tests_failed_not_its_last_change(db):
    """Its merge state changing later doesn't restart the 15 minutes before it shows as waiting on Claude too long."""
    from datetime import timedelta

    from sqlalchemy import update

    p = _seen(db, _pr(60, tests="failed"))[0]
    db.execute(update(FftEvent).where(FftEvent.thing == "pull", FftEvent.thing_id == p.id).values(at=rules.now() - timedelta(hours=1)))
    _seen(db, _pr(60, tests="failed", merge_state="unknown"))
    red = next(g for g in views.gaps(db) if g["kind"] == "pull_red")
    assert red["since"] <= rules.now() - timedelta(minutes=59)


def test_what_github_reports_never_fills_claudes_inbox(api, db, github):
    """Every test run changes a pull request: kept on the record, never in an inbox (Nov 24: the first live reports woke
    Claude's listener for each one). A red one reaches Claude as a gap instead."""
    from datetime import timedelta

    from sqlalchemy import update

    assert api.post("/api/fft/github/pulls", headers=github, json={"pulls": [_pr(70, tests="failed")]}).status_code == 200
    db.execute(update(FftEvent).values(at=rules.now() - timedelta(seconds=30)))
    assert api.get("/api/fft/inbox", headers={"X-Fft-Key": CLAUDE}).json()["items"] == []
    assert api.get("/api/fft/inbox/wait?seconds=1", headers={"X-Fft-Key": CLAUDE}).json()["items"] == []
    assert any(g["kind"] == "pull_red" for g in api.get("/api/fft/gaps", headers={"X-Fft-Key": CLAUDE}).json()["items"])


def test_a_plans_history_says_what_happened_to_its_pull_requests_in_words(db):
    """Opened, tests passed or failed, brought up to date, merged: in words, on its plan's History; a flicker of its merge
    state isn't one."""
    issue = rules.new_issue(db, "claude", "Back clears what you typed", feature="feedback")
    db.flush()
    br = f"a{issue.area_id}-batch"
    _seen(db, _pr(90, br))
    _seen(db, _pr(90, br, merge_state="unknown"))
    _seen(db, _pr(90, br, tests="passed"))
    _seen(db, _pr(90, br, tests="running") | {"updated": True})
    _seen(db, {"number": 90, "state": "merged"})
    evs = db.scalars(select(FftEvent).where(FftEvent.thing == "pull").order_by(FftEvent.id))
    said = [views.event_words(e) for e in evs]
    assert said == ["Pull request #90 opened", "Pull request #90 changed", "Pull request #90's tests passed",
                    "Pull request #90 brought up to date with main", "Pull request #90 merged"]
    shown = [views.pull_worth_saying(e) for e in db.scalars(select(FftEvent).where(FftEvent.thing == "pull").order_by(FftEvent.id))]
    assert shown == [True, False, True, True, True]


def test_a_pile_of_pull_request_changes_never_hides_a_note(api, db, github, monkeypatch):
    """An inbox reads a page at a time (500): the quiet ones are left out of the read itself, so a night of test runs
    can't fill the page and hide what comes after them. Here the page is 2 and three quiet events come first."""
    from datetime import timedelta

    from sqlalchemy import update

    monkeypatch.setattr(rules, "INBOX_PAGE", 2)
    for _ in range(3):
        rules._event(db, "github", "pull_changed", "pull", 1, number=1, changes={"merge_state": "unknown"})
    rules.new_item(db, "user:1", "After the pile")  # (Brett's: Claude's inbox leaves out what Claude did itself)
    db.execute(update(FftEvent).values(at=rules.now() - timedelta(seconds=30)))
    got = api.get("/api/fft/inbox/wait?seconds=1", headers={"X-Fft-Key": CLAUDE}).json()["items"]
    assert [e["kind"] for e in got] == ["item_new"]


# ------------------------------------------------------------------ deploys mark themselves live (item 39, 2 of 4)

C1, C2, C3 = "1" * 40, "2" * 40, "3" * 40


def _merged(db, number, commit, at, **kw):
    return _seen(db, {"number": number, "state": "merged", "merge_commit": commit, "closed_at": at, "branch": kw.pop("branch", "x")} | kw)[0]


def test_a_deploy_releases_every_pull_request_merged_up_to_the_version_it_runs(db):
    """A standing rule (R4, Brett Nov 20): a fix is tried once it's live, never before. askdnd.ai's version is a pull
    request's merge commit; everything merged up to it is inside, nothing after it. Each released once: its issues ready
    to try, the checks that waited for it reach For you."""
    from app.fft.models import FftCheckWait

    issue = rules.new_issue(db, "claude", "Back clears what you typed", feature="feedback")
    db.flush()
    rules.fix_ready(db, "claude", issue, URL + "101")
    check = rules.write_check(db, "claude", title="t", steps=["s"], expect="e", issue_ids=[issue.id])
    rules.wait_for_deploy(db, "claude", check, URL + "102")
    _merged(db, 101, C1, "2026-11-24T01:00:00Z")
    _merged(db, 102, C2, "2026-11-24T02:00:00Z")
    _merged(db, 103, C3, "2026-11-24T03:00:00Z")
    _seen(db, {"number": 104, "state": "closed", "closed_at": "2026-11-24T01:30:00Z"})  # (closed unmerged: never live)
    got = rules.release_live(db, "askdnd", C2[:12])  # (askdnd.ai's /health shows 12 characters)
    db.flush()
    assert got == {"live": [101, 102], "issues": [issue.id], "checks": [check.id]}
    assert issue.state == "ready" and db.scalar(select(FftCheckWait.id)) is None
    assert rules.release_live(db, "askdnd", C2) == {"live": [], "issues": [], "checks": []}  # (once each)
    assert rules.release_live(db, "askdnd", C3)["live"] == [103]
    assert {p.number: p.live_at is not None for p in db.scalars(select(FftPull))} == {101: True, 102: True, 103: True, 104: False}


def test_a_version_askdnd_doesnt_know_yet_releases_nothing(db):
    """GitHub hasn't reported the merge yet, or it's a local copy or staging: nothing is marked live."""
    _merged(db, 110, C1, "2026-11-24T01:00:00Z")
    for version in ("", "local", "abc", "9" * 40):
        assert rules.release_live(db, "askdnd", version)["live"] == []


def test_githubs_next_report_releases_one_merged_just_before_the_deploy(api, db, github, monkeypatch):
    """The deploy started before GitHub said which pull request its commit is: the next report (any run) releases it."""
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", C1)
    got = api.post("/api/fft/github/pulls", headers=github, json={"pulls": [{"number": 120, "state": "merged", "merge_commit": C1,
                                                                             "closed_at": "2026-11-24T01:00:00Z"}]})
    assert got.json()["live"] == [120]
    monkeypatch.setattr(config, "STAGING", True)  # (staging runs another branch: it never marks askdnd.ai's work live)
    assert config.running_version() == ""


def test_a_commit_that_isnt_one_is_refused(api, db, github):
    bad = {"pulls": [{"number": 121, "state": "merged", "merge_commit": "not a commit"}]}
    assert api.post("/api/fft/github/pulls", headers=github, json=bad).status_code == 400


def test_githubs_close_time_wins_over_when_askdnd_first_noticed(db):
    """Missing from a whole list, a pull request is closed at once; its merge time, when GitHub says it, replaces that,
    since the order of merges says what's inside a deploy."""
    _seen(db, _pr(130))
    _seen(db, _pr(131), snapshot=True)  # (130 left the open list)
    p = _merged(db, 130, C1, "2026-11-20T10:00:00Z")
    assert (p.state, p.closed_at.isoformat()[:19]) == ("merged", "2026-11-20T10:00:00")


def test_releasing_never_stops_the_server(monkeypatch):
    """A failure is sent to Sentry and askdnd carries on: GitHub's next report asks again."""
    from app import main

    def boom(*a, **k):
        raise RuntimeError("database down")

    monkeypatch.setattr(rules, "release_live", boom)
    assert main.release_now() == {}
