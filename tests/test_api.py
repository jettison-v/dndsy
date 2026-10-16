import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import admin_sessions, config
from app.db import get_db
from app.importer import import_bundle
from app.main import app
from app.models import GameSession

TOKEN = "t" * 40


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setattr(config, "UPLOAD_TOKEN", TOKEN)
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def post(client, token=TOKEN, **body):
    payload = {"played_on": "2026-08-29", "text": "[0:42:00] Mary: You wake in the brig.", **body}
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return client.post("/api/transcripts", json=payload, headers=headers)


def test_rejects_missing_or_wrong_token(client):
    assert post(client, token=None).status_code == 401
    assert post(client, token="nope").status_code == 401


def test_disabled_without_server_token(client, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_TOKEN", "")
    assert post(client).status_code == 503


def test_upload_matches_session_by_date_and_starts_draft(client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"played_on": "2026-08-29", "source": "transcript"}]})
    calls = []
    monkeypatch.setattr(admin_sessions, "draft_transcript_in_background", lambda sid, text: calls.append((sid, text)) or True)
    r = post(client)
    assert r.status_code == 202
    sid = db.scalar(select(GameSession)).id
    assert r.json()["session_id"] == sid and r.json()["review_url"].endswith(f"/admin/sessions/{sid}")
    assert calls == [(sid, "[0:42:00] Mary: You wake in the brig.")]


def test_upload_creates_session_for_new_date(client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    monkeypatch.setattr(admin_sessions, "draft_transcript_in_background", lambda sid, text: True)
    assert post(client, played_on="2026-11-07").status_code == 202
    s = db.scalar(select(GameSession))
    assert (str(s.played_on), s.source) == ("2026-11-07", "transcript")


def test_busy_returns_conflict(client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    monkeypatch.setattr(admin_sessions, "draft_transcript_in_background", lambda sid, text: False)
    assert post(client).status_code == 409


def test_transcript_text_is_not_stored(client, db, monkeypatch):
    """Privacy rule: the transcript must not land in any table."""
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    monkeypatch.setattr(admin_sessions, "draft_transcript_in_background", lambda sid, text: True)
    post(client, text="SECRET-TRANSCRIPT-MARKER")
    from sqlalchemy import text as sql

    tables = [r[0] for r in db.execute(sql("select tablename from pg_tables where schemaname='public'"))]
    for t in tables:
        hits = db.execute(sql(f'select count(*) from "{t}" where cast("{t}".* as text) like :m'), {"m": "%SECRET-TRANSCRIPT-MARKER%"}).scalar()
        assert hits == 0, t
