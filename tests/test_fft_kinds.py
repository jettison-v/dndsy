"""Two kinds of change to a Product Area (Brett, Nov 20): a fix (something that exists is broken) or an improvement
(something that exists, made better). An idea that needs discussion is the Roadmap's. A note is sorted into one; an
issue can be changed to the other; Feedback filters by them; Claude sets them through the API."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import get_db
from app.fft import rules, views
from app.fft.models import FftEvent, FftIssue
from app.importer import import_bundle
from app.main import app
from tests.table_setup import BUNDLE

CLAUDE = "c" * 40


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


def _note(db, kind="problem", text="The rest button does nothing."):
    return rules.send_note(db, user_id=None, first_name="Trah", role="player", kind=kind, text=text)


def test_a_note_becomes_a_fix_or_an_improvement(db, admin):
    problem, idea = _note(db), _note(db, "idea", "Could the rest button say how long it takes?")
    db.flush()
    page = admin.get(f"/manage/item/n{problem.id}").text  # (its sender's own word first)
    assert page.index('data-do="fix"') < page.index('data-do="improvement"') and 'data-do="issue"' not in page
    page = admin.get(f"/manage/item/n{idea.id}").text
    assert page.index('data-do="improvement"') < page.index('data-do="fix"')
    admin.post(f"/manage/feedback/notes/{problem.id}", data={"do": "fix"})
    admin.post(f"/manage/feedback/notes/{idea.id}", data={"do": "improvement"})
    assert db.get(FftIssue, problem.issue_id).kind == "fix" and db.get(FftIssue, idea.issue_id).kind == "improvement"
    assert rules.file_issue(db, "claude", _note(db, "idea")).kind == "improvement"  # (as its sender called it)


def test_an_issue_changes_kind_and_feedback_filters_by_it(db, admin):
    fix = rules.new_issue(db, "claude", "The Count wraps")
    better = rules.new_issue(db, "claude", "Show temporary HP beside the total", kind="improvement")
    db.flush()
    page = admin.get("/manage/feedback?tab=open").text
    assert 'data-kind-word="fix"' in page and 'data-kind-word="improvement"' in page and 'data-chip="improvement"' in page
    only = admin.get("/manage/feedback?tab=open&chip=improvement").text
    assert f'data-row="i{better.id}"' in only and f'data-row="i{fix.id}"' not in only
    win = admin.get(f"/manage/item/i{fix.id}").text
    assert 'data-do="kind"' in win and 'data-kind-word="fix"' in win
    admin.post(f"/manage/feedback/issues/{fix.id}", data={"do": "kind", "kind": "improvement"})
    assert fix.kind == "improvement"
    ev = db.scalar(select(FftEvent).where(FftEvent.kind == "issue_kind"))
    assert views.event_words(ev) == f"Issue {fix.id} is an improvement" and "to" not in ev.data
    assert admin.post(f"/manage/feedback/issues/{fix.id}", data={"do": "kind", "kind": "nonsense"}).status_code == 400
    with pytest.raises(rules.RuleError):
        rules.new_issue(db, "claude", "x", kind="nonsense")


def test_claude_sets_an_issues_kind(db, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    before = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = lambda: db
    try:
        api, h = TestClient(app), {"X-Fft-Key": CLAUDE}
        made = api.post("/api/fft/issues", headers=h, json={"title": "Show the round's length", "kind": "improvement"}).json()
        assert made["kind"] == "improvement"
        assert api.post(f"/api/fft/issues/{made['id']}", headers=h, json={"do": "kind", "kind": "fix"}).json()["kind"] == "fix"
        assert api.post(f"/api/fft/issues/{made['id']}", headers=h, json={"do": "kind", "kind": "big"}).status_code == 400
    finally:
        app.dependency_overrides[get_db] = before
