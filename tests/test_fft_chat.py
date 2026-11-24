"""What Brett says in chat, saved as it arrives (Roadmap item 42, his pick 2A on Talking both ways, Nov 24: "We need to
work here"): the Claude Code hook saves each message (feedback.py chat said, POST /api/fft/chat); Claude files it onto
its Roadmap item, its issue, or as just chat; one left unfiled is a gap; and saving his words never gives his OK."""

import io
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.db import get_db
from app.fft import rules, views
from app.fft.models import FftAddition, FftChat, FftLine
from app.main import app

CLAUDE = "c" * 40


@pytest.fixture
def api(db, monkeypatch):
    monkeypatch.setattr(config, "FEEDBACK_KEY", CLAUDE)
    monkeypatch.setenv("FFT_MINI_KEY", "m" * 40)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


def _said(api, words, key=CLAUDE):
    return api.post("/api/fft/chat", headers={"X-Fft-Key": key}, json={"words": words, "session": "s1"})


def test_a_message_said_in_chat_is_a_gap_until_filed_onto_its_item_or_issue(api, db):
    it = rules.new_item(db, "claude", "Our Work", section="now")
    issue = rules.new_issue(db, "claude", "Something to fix")
    db.flush()
    ids = [_said(api, w).json()["id"] for w in ("Put the plan in the window.", "This is broken on the iPhone.", "Pressed it")]
    gaps = [g for g in views.gaps(db) if g["kind"] == "chat_unfiled"]
    assert [g["id"] for g in gaps] == ids  # (each one Claude's to file before its turn ends)
    h = {"X-Fft-Key": CLAUDE}
    assert api.post(f"/api/fft/chat/{ids[0]}", headers=h, json={"as": "item", "id": it.id}).status_code == 200
    assert api.post(f"/api/fft/chat/{ids[1]}", headers=h, json={"as": "issue", "id": issue.id}).status_code == 200
    assert api.post(f"/api/fft/chat/{ids[2]}", headers=h, json={"as": "chat"}).status_code == 200
    assert not [g for g in views.gaps(db) if g["kind"] == "chat_unfiled"]
    a = db.scalar(select(FftAddition).where(FftAddition.item_id == it.id))
    assert (a.words, a.where) == ("Put the plan in the window.", "chat")  # (his words, as said)
    line = db.scalar(select(FftLine).where(FftLine.issue_id == issue.id))
    assert (line.text, line.who, line.to) == ("This is broken on the iPhone.", "admin", "claude")  # (his line, for Claude to answer)
    assert api.post(f"/api/fft/chat/{ids[2]}", headers=h, json={"as": "chat"}).status_code == 409  # (filed once)


def test_a_relayed_comment_the_apps_own_notices_and_an_empty_message_arent_saved(api, db):
    assert _said(api, "[Artifact comment sent to Claude]\nArtifact: …").json()["id"] is None  # (it comes in through its page)
    assert _said(api, "  ").json()["id"] is None
    for notice in ("<task-notification>\n<task-id>b1</task-id>", "<system-reminder>\n[SYSTEM NOTIFICATION - NOT USER INPUT]", "<system-reminder id=\"8e13\">\nAnother Claude session sent a message", "Another Claude session sent a message:\n<agent-message from=\"ae87\">", "Stop hook feedback:\n- pull 30"):
        assert _said(api, notice).json()["id"] is None  # (the app's own messages, not his words)
    assert db.scalar(select(FftChat)) is None


def test_a_standing_rule_saving_his_words_never_gives_his_ok(api, db):
    """A standing rule (CLAUDE.md: Scope looks right is Brett's alone; Nov 24, the chat log): Claude's key still can't
    agree a scope, with or without a saved chat message; only Claude's key saves or files chat."""
    it = rules.new_item(db, "claude", "Our Work", section="now")
    db.flush()
    rules.write_scope(db, "claude", it, what="w", inside=["i"])
    db.flush()
    cid = _said(api, "Scope looks right, go ahead").json()["id"]
    for body in ({"do": "agree"}, {"do": "agree", "chat": cid}):
        assert api.post(f"/api/fft/roadmap/{it.id}", headers={"X-Fft-Key": CLAUDE}, json=body).status_code == 403
    assert rules.latest_scope(db, it).agreed_at is None
    assert _said(api, "x", key="").status_code == 404 and _said(api, "x", key="m" * 40).status_code == 403


def test_the_hook_never_stops_his_message(monkeypatch, capsys):
    """feedback.py chat said: askdnd out of reach, or anything else wrong, and his message still goes to Claude."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location("feedback", Path(__file__).resolve().parent.parent / "scripts" / "feedback.py")
    fb = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fb)
    monkeypatch.setattr(fb.sys, "stdin", io.StringIO(json.dumps({"prompt": "Hello", "session_id": "s1"})))
    monkeypatch.setattr(fb, "call", lambda *a, **k: (_ for _ in ()).throw(SystemExit("askdnd answered 500")))
    fb.chat(type("A", (), {"do": "said", "base": ""})())
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(fb.sys, "stdin", io.StringIO(json.dumps({"prompt": "Hello", "session_id": "s1"})))
    monkeypatch.setattr(fb, "call", lambda *a, **k: {"id": 7})
    fb.chat(type("A", (), {"do": "said", "base": ""})())
    assert "chat 7" in capsys.readouterr().out


def test_an_unfiled_message_shows_in_claudes_hands_without_a_wrong_link(api, admin, db):
    _said(api, "Something to remember")
    page = admin.get("/manage/work").text
    li = page.split('data-gap="chat_unfiled"', 1)[1].split("</li>", 1)[0]
    assert "Something to remember" in li and "href=" not in li.split("Something to remember")[0]
