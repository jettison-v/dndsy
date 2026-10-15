import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import admin_sessions, auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.extraction import store_result
from app.importer import import_bundle
from app.main import app
from app.models import Correction, Entity, ExtractionRun, GameSession, GlossaryTerm, Proposal, Recap, StoryEvent

RESULT = {
    "title": "Devils",
    "recap": "The party fought devils.",
    "events": [{"kind": "event", "text": "Big fight.", "entities": []}],
    "entities": [{"name": "Horn Devil", "kind": "creature", "summary": "Stunned.", "aliases": ["horned devil"], "quest_status": "not_a_quest"}],
    "glossary": [{"term": "Hellhound", "description": "Fiery dog", "misheard_as": ["hell hound"]}],
    "to_check": ["Check the imp count."],
}


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "admin@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    yield c
    app.dependency_overrides.clear()


def drafted_session(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": 29}]})
    s = db.scalar(select(GameSession))
    run = ExtractionRun(session_id=s.id, source="notes", status="done")
    db.add(run)
    store_result(db, s, run, RESULT)
    db.flush()
    db.expire_all()
    return db.scalar(select(GameSession))


def test_sessions_page_and_draft_button(client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": 29}]})
    page = client.get("/admin/sessions").text
    assert "Session 29" in page and "no draft" in page
    started = []
    monkeypatch.setattr(admin_sessions, "_draft_in_background", lambda ids: started.append(ids) or True)
    sid = db.scalar(select(GameSession)).id
    r = client.post("/admin/sessions/draft", data={"session_ids": [sid]}, follow_redirects=False)
    assert started == [[sid]] and r.headers["location"] == f"/admin/sessions/{sid}"


def test_review_page_shows_draft(client, db):
    s = drafted_session(db)
    page = client.get(f"/admin/sessions/{s.id}").text
    assert "The party fought devils." in page
    assert "Check the imp count." in page
    assert "Horn Devil" in page and "Hellhound" in page


def test_edit_and_publish_records_correction(client, db):
    s = drafted_session(db)
    client.post(f"/admin/sessions/{s.id}/recap", data={"body": "The party fought three devils.", "action": "save", "note": "Count the devils", "standing": "1"})
    client.post(f"/admin/sessions/{s.id}/recap", data={"body": "The party fought three devils.", "action": "publish"})
    db.expire_all()
    recaps = list(db.scalars(select(Recap).order_by(Recap.version)))
    assert [(r.author, r.status.value) for r in recaps] == [("ai", "draft"), ("brett", "published")]
    c = db.scalar(select(Correction))
    assert (c.before, c.after, c.note, c.standing_instruction) == ("The party fought devils.", "The party fought three devils.", "Count the devils", True)
    assert all(e.status.value == "published" for e in db.scalars(select(StoryEvent)))


def test_edit_events(client, db):
    s = drafted_session(db)
    ev = db.scalar(select(StoryEvent))
    client.post(f"/admin/sessions/{s.id}/events", data={f"text-{ev.id}": "A huge fight.", f"kind-{ev.id}": "reveal", "new-text": "They rested.", "new-kind": "decision"})
    db.expire_all()
    events = list(db.scalars(select(StoryEvent).order_by(StoryEvent.position)))
    assert [(e.kind.value, e.text) for e in events] == [("reveal", "A huge fight."), ("decision", "They rested.")]
    client.post(f"/admin/sessions/{s.id}/events", data={f"delete-{events[0].id}": "1"})
    db.expire_all()
    assert [e.text for e in db.scalars(select(StoryEvent))] == ["They rested."]


def test_accept_proposals(client, db):
    s = drafted_session(db)
    entity_p = db.scalar(select(Proposal).where(Proposal.kind == "entity"))
    glossary_p = db.scalar(select(Proposal).where(Proposal.kind == "glossary"))
    client.post(f"/admin/proposals/{entity_p.id}", data={"decision": "accept", "summary": "Stunned by No Name."})
    client.post(f"/admin/proposals/{glossary_p.id}", data={"decision": "accept"})
    db.expire_all()
    devil = db.scalar(select(Entity).where(Entity.name == "Horn Devil"))
    assert devil.summary == "Stunned by No Name." and [a.alias for a in devil.aliases] == ["horned devil"]
    assert db.scalar(select(GlossaryTerm)).misheard_as == ["hell hound"]
    assert {p.status for p in db.scalars(select(Proposal))} == {"accepted"}


def test_player_cannot_open_admin_sessions(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "player@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    assert c.get("/admin/sessions").status_code == 403
    app.dependency_overrides.clear()


def test_story_shows_only_published(client, db):
    s = drafted_session(db)
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": [{"kind": "quest", "name": "Reach the library", "quest_open": True}]})
    assert "Nothing published yet" in client.get("/story").text
    client.post(f"/admin/sessions/{s.id}/recap", data={"body": "The party fought devils.", "action": "publish"})
    page = client.get("/story").text
    assert "The party fought devils." in page
    assert "Big fight." in page
    assert "Reach the library" in page
