import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import admin_sessions, auth, config, conversation
from app.config import parse_allowlist
from app.db import get_db
from app.extraction import ExtractionRun, build_messages, store_result
from app.importer import import_bundle
from app.main import app
from app.models import GameSession, SessionMessage

HX = {"HX-Request": "true"}


class FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.response


def fake_claude(reply="1. How did the party get aboard the Leviathan?", ready=False, seen=None):
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps({"reply": reply, "ready": ready}))],
        usage=SimpleNamespace(input_tokens=500, output_tokens=100, cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )

    def stream(**kwargs):
        if seen is not None:
            seen.append(kwargs)
        return FakeStream(response)

    return lambda: SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "admin@example.com", "email_verified": True, "name": "Brett"}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    yield c
    app.dependency_overrides.clear()


def campaign_with_neighbors(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [
        {"number": 29, "played_on": "2026-02-07"}, {"played_on": "2026-08-29", "source": "transcript"}]})
    before, after = list(db.scalars(select(GameSession).order_by(GameSession.played_on)))
    for s, text in ((before, "They fought devils in a sea cave."), (after, "They woke in the brig of the Leviathan.")):
        run = ExtractionRun(session_id=s.id, source="notes", status="done")
        db.add(run)
        db.flush()
        store_result(db, s, run, {"title": "", "recap": text, "events": [], "entities": [], "glossary": [], "to_check": []})
    db.flush()


def test_add_session_flow(client, db, monkeypatch):
    campaign_with_neighbors(db)
    assert "Add a session" in client.get("/admin/sessions/new").text
    r = client.post("/admin/sessions/new", data={"played_on": "2026-05-01", "title": "Boarding", "account": "We sailed to the Leviathan."}, follow_redirects=False)
    sid = int(r.headers["location"].split("/")[3].split("?")[0])
    page = client.get(f"/admin/sessions/{sid}?check=1").text
    assert "We sailed to the Leviathan." in page and 'hx-trigger="load"' in page

    seen = []
    monkeypatch.setattr(conversation.anthropic, "Anthropic", fake_claude(seen=seen))
    r = client.post(f"/admin/sessions/{sid}/check", headers=HX)
    assert "How did the party get aboard" in r.text
    content = " ".join(b["text"] for b in seen[0]["messages"][0]["content"])
    assert "They fought devils in a sea cave." in content  # session before
    assert "They woke in the brig of the Leviathan." in content  # session after
    assert "We sailed to the Leviathan." in content

    monkeypatch.setattr(conversation.anthropic, "Anthropic", fake_claude(reply="Thanks, that covers it.", ready=True))
    r = client.post(f"/admin/sessions/{sid}/messages", data={"body": "A pirate captain smuggled us aboard."}, headers=HX)
    assert "Claude has enough to draft" in r.text
    msgs = list(db.scalars(select(SessionMessage).where(SessionMessage.session_id == sid).order_by(SessionMessage.id)))
    assert [m.role for m in msgs] == ["reviewer", "claude", "reviewer", "claude"]
    assert msgs[0].author == "Brett"

    started = []
    monkeypatch.setattr(admin_sessions, "_draft_in_background", lambda ids: started.append(ids) or True)
    client.post(f"/admin/sessions/{sid}/draft-account", headers=HX)
    assert started == [[sid]]

    s = db.get(GameSession, sid)
    source, _, _ = admin_sessions.source_for(db, s)
    assert source.kind == "account" and "smuggled us aboard" in source.text and "Claude:" in source.text
    prompt = " ".join(b.get("text", "") for b in build_messages(db, s, source)[0]["content"])
    assert "Later messages override earlier ones" in prompt


def test_conversation_runs_do_not_hide_review_questions(client, db, monkeypatch):
    campaign_with_neighbors(db)
    s = db.scalar(select(GameSession).where(GameSession.number == 29))
    run = ExtractionRun(session_id=s.id, source="notes", status="done", to_check=["Which ship?"])
    db.add(run)
    db.add(ExtractionRun(session_id=s.id, source="conversation", status="done"))
    db.flush()
    assert "Which ship?" in client.get(f"/admin/sessions/{s.id}").text


def test_duplicate_number_and_missing_account_rejected(client, db):
    campaign_with_neighbors(db)
    r = client.post("/admin/sessions/new", data={"played_on": "2026-05-01", "number": "29", "account": "x"})
    assert "already exists" in r.text
    r = client.post("/admin/sessions/new", data={"played_on": "2026-05-01", "account": "   "})
    assert "Write what happened" in r.text
