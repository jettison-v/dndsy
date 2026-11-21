"""What Claude left half done (app/fft/views.py `gaps`, `/api/fft/gaps`, `feedback.py gaps --hook`, Where it stands ›
Claude missed). Brett, Nov 17: "how are we going to make sure that you do not miss something?" after five fixes went
by with no check for him to try and three of his answers went unanswered."""

import io
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import get_db
from app.fft import rules, views
from app.fft.models import FftIssue, FftListener
from app.importer import import_bundle
from app.main import app
from tests.table_setup import BUNDLE

CLAUDE = "c" * 40


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


def _kinds(db, issue_id=None):
    return {g["kind"] for g in views.gaps(db) if issue_id is None or (g["thing"] == "issue" and g["id"] == issue_id)}


def test_a_standing_rule_a_fix_without_a_check_is_a_gap(db):
    """A standing rule (Brett, Nov 17: every fix gets its check, tried by Claude first): a fixed issue with no check, and
    a check Claude hasn't tried, are gaps until they're closed."""
    issue = rules.new_issue(db, "claude", "Back clears what you typed", feature="feedback")
    assert not _kinds(db)
    rules.fix_ready(db, "claude", issue, "https://github.com/jettison-v/dndsy/pull/417")
    rules.set_lane(db, "claude", db.get(rules.FftArea, issue.area_id), "look")  # (its lane: the next test's gap)
    assert _kinds(db, issue.id) == {"no_check"}
    check = rules.write_check(db, "claude", title="Back keeps what you typed", steps=["Press [Back]."], expect="It's kept.",
                              issue_ids=[issue.id])
    assert {(g["kind"], g["thing"]) for g in views.gaps(db)} == {("not_tried", "check")}
    rules.preflight(db, "claude", check, True)
    assert not views.gaps(db)
    rules.retire(db, "claude", check, "Replaced")
    assert _kinds(db, issue.id) == {"no_check"}  # (a retired check tries nothing)


def test_a_fix_with_no_lane_is_a_gap(db):
    """Brett, Nov 19: a fix never goes without its lane (Ship, Look, Careful decide whether he tries it first). A plan
    with a fix in a pull request and no lane is a gap until it has one; a plan with nothing in hand needs none."""
    issue = rules.new_issue(db, "claude", "The Count wraps", feature="feedback")
    area = db.get(rules.FftArea, issue.area_id)
    assert not [g for g in views.gaps(db) if g["kind"] == "no_lane"]
    rules.fix_ready(db, "claude", issue, "https://github.com/jettison-v/dndsy/pull/420")
    assert [(g["thing"], g["id"]) for g in views.gaps(db) if g["kind"] == "no_lane"] == [("area", area.id)]
    rules.set_lane(db, "claude", area, "look", "People see it")
    assert not [g for g in views.gaps(db) if g["kind"] == "no_lane"]


def _listening(db, at):
    db.merge(FftListener(name="main", heard_at=at))
    db.flush()


def test_brett_sees_a_gap_only_once_it_has_waited(db, monkeypatch):
    """Issue 39 (Brett, Nov 19): what just happened isn't late yet. Issue 21 (his pick 1A): everything in Claude's hands
    is a quiet line; a gap turns late (Development's amber panel) only once it has waited GAP_GRACE while a Claude
    session listens. Claude's own end-of-turn check sees it at once."""
    issue = rules.new_issue(db, "claude", "Fresh", feature="feedback")
    rules.fix_ready(db, "claude", issue, "https://github.com/jettison-v/dndsy/pull/421")
    db.flush()
    assert any(g["thing"] == "issue" and g["id"] == issue.id for g in views.gaps(db))
    assert not views.missed(db) and any(g["id"] == issue.id and not g["late"] for g in views.hands(db))
    for g in views.gaps(db):
        assert g["since"] is not None
    later = rules.now() + views.GAP_GRACE + timedelta(minutes=1)
    monkeypatch.setattr(rules, "now", lambda: later)
    assert not views.missed(db)  # (no session listening: it waits for the next one, nothing late)
    _listening(db, later)
    assert {(g["kind"], g["id"]) for g in views.missed(db) if g["thing"] == "issue"} == {("no_check", issue.id)}


def test_whatever_is_said_to_claude_waits_for_its_reply(db):
    """A note filed on an issue, a line from Brett, an answer to Claude's question: each is a gap until Claude says
    something after it. A question waiting on Brett isn't."""
    note = rules.send_note(db, user_id=None, first_name="Brett", role="admin", kind="problem", text="It did not work")
    issue = db.get(FftIssue, note.issue_id) if note.issue_id else rules.file_issue(db, "user:1", note)  # (an admin's note files itself)
    rules.set_feature(db, "claude", issue, "homebrew")
    t = rules.now()
    note.created_at = t
    assert _kinds(db, issue.id) == {"unanswered"}
    reply = rules.add_line(db, "claude", "Thanks: what went wrong?", issue=issue, to="")
    reply.created_at = t + timedelta(minutes=1)
    assert not _kinds(db, issue.id)
    q = rules.ask(db, "claude", about="issue", about_id=issue.id, text="Which part?", choices=[{"label": "A"}, {"label": "B"}])
    q.created_at = t + timedelta(minutes=2)
    assert issue.state == "asks" and not _kinds(db, issue.id)  # (Brett's turn: nothing for Claude)
    rules.answer(db, "user:1", q, choice=1)
    q.answered_at = t + timedelta(minutes=3)
    assert _kinds(db, issue.id) == {"unanswered"}
    later = rules.add_line(db, "claude", "Fixing B.", issue=issue)
    later.created_at = t + timedelta(minutes=4)
    assert not _kinds(db, issue.id)
    brett = rules.add_line(db, "user:1", "Also the save button.", issue=issue, who="admin")
    brett.created_at = t + timedelta(minutes=5)
    assert _kinds(db, issue.id) == {"unanswered"}
    rules.close(db, "user:1", issue, "withdrawn", "")
    assert not _kinds(db, issue.id)  # (closed: nothing left to do)


def test_an_open_issue_with_no_feature_is_a_gap(db):
    """The Product Taxonomy (Brett, Nov 18): every issue is about one Feature, which puts it in its Product Area's batch;
    one with none is Claude's to sort."""
    issue = rules.new_issue(db, "claude", "Loose")
    assert _kinds(db, issue.id) == {"no_feature"}
    rules.set_feature(db, "claude", issue, "hp")
    assert not _kinds(db, issue.id)


def test_claude_reads_its_gaps_and_brett_sees_them_on_where_it_stands(db, admin, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    before = app.dependency_overrides.get(get_db)  # (the signed-in client's: put back after)
    app.dependency_overrides[get_db] = lambda: db
    try:
        issue = rules.new_issue(db, "claude", "Loose")
        api = TestClient(app)
        assert api.get("/api/fft/gaps").status_code in (401, 403, 404)  # (no key: no one)
        got = api.get("/api/fft/gaps", headers={"X-Fft-Key": CLAUDE}).json()["items"]
        assert [(g["kind"], g["id"]) for g in got] == [("no_feature", issue.id)]
    finally:
        app.dependency_overrides[get_db] = before
    page = admin.get("/manage/work").text
    assert "data-missed" not in page and 'data-stat="hands"' in page  # (just made: in Claude's hands, not late yet, issues 39 and 21)
    _listening(db, rules.now())
    from sqlalchemy import update

    from app.fft.models import FftEvent
    db.execute(update(FftEvent).where(FftEvent.thing == "issue", FftEvent.thing_id == issue.id).values(at=rules.now() - timedelta(hours=1)))
    db.flush()
    page = admin.get("/manage/work").text
    assert "data-missed" in page and 'data-gap="no_feature"' in page and f"open=i{issue.id}" in page
    foryou = admin.get("/manage/for-you").text  # (no amber panel there: the line says it's late, issue 21)
    assert "data-missed" not in foryou and "data-late-count" in foryou and f"open=i{issue.id}" in foryou
    assert "data-late-count" not in page  # (Development has its panel instead)


def _hook(monkeypatch, tmp_path, items, active=False, env=None):
    """feedback.py gaps --hook against a stand-in askdnd answering `items`."""
    from scripts import feedback as fb

    monkeypatch.setattr(fb, "OUT", tmp_path)
    monkeypatch.setattr(fb, "key", lambda: CLAUDE)
    monkeypatch.setenv("ASKDND_BASE", "http://askdnd.test")
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)

    class Answer(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(fb.urllib.request, "urlopen", lambda req, timeout=0: Answer(json.dumps({"items": items}).encode()))
    monkeypatch.setattr(fb.sys, "stdin", io.StringIO(json.dumps({"session_id": "s1", "stop_hook_active": active})))
    try:
        fb.gaps(type("A", (), {"hook": True, "base": ""})())
    except SystemExit as e:
        return e.code
    return 0


def test_the_end_of_turn_hook_sends_claude_back_to_a_gap_and_never_loops(monkeypatch, tmp_path, capsys):
    gap = {"kind": "no_check", "thing": "issue", "id": 5, "title": "Back clears", "says": "Write its check."}
    assert _hook(monkeypatch, tmp_path, []) == 0
    assert _hook(monkeypatch, tmp_path, [gap, dict(gap, id=6)]) == 2
    assert "Back clears" in capsys.readouterr().err
    assert _hook(monkeypatch, tmp_path, [gap], active=True) == 2  # (one closed: progress, so once more)
    assert _hook(monkeypatch, tmp_path, [gap], active=True) == 0  # (no progress on a second go: the turn may end)
    assert _hook(monkeypatch, tmp_path, [gap], env={"ASKDND_GAPS": "off"}) == 0
