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
    monkeypatch.setattr(admin_sessions, "read_transcript_in_background", lambda sid, text: calls.append((sid, text)) or True)
    r = post(client)
    assert r.status_code == 202
    sid = db.scalar(select(GameSession)).id
    assert r.json()["session_id"] == sid and r.json()["review_url"].endswith(f"/manage/sessions/{sid}")
    assert calls == [(sid, "[0:42:00] Mary: You wake in the brig.")]


def test_upload_creates_session_for_new_date(client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    monkeypatch.setattr(admin_sessions, "read_transcript_in_background", lambda sid, text: True)
    assert post(client, played_on="2026-11-07").status_code == 202
    s = db.scalar(select(GameSession))
    assert (str(s.played_on), s.source) == ("2026-11-07", "transcript")


def test_busy_returns_conflict(client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    monkeypatch.setattr(admin_sessions, "read_transcript_in_background", lambda sid, text: False)
    assert post(client).status_code == 409


def test_transcript_text_is_not_stored(client, db, monkeypatch):
    """A standing rule (CLAUDE.md privacy rules; DECISIONS Oct 14, revised Nov 7): a transcript never lands in any
    database table. The cleaned one the Processor sends is kept in file storage, for drafting, with who talked."""
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    monkeypatch.setattr(admin_sessions, "read_transcript_in_background", lambda sid, text: True)
    post(client, text="SECRET-TRANSCRIPT-MARKER", talk={"speakers": {"Jordan Vale": 4530.2, "": 3, "Alex Moore": "x"}, "length": 12300})
    from app import files, session_story

    s = db.scalar(select(GameSession))
    assert session_story.text(s) == "SECRET-TRANSCRIPT-MARKER" and files.get(s.transcript_key) == b"SECRET-TRANSCRIPT-MARKER"
    assert s.talk == {"speakers": {"Jordan Vale": 4530.2}, "length": 12300}  # (checked: no empty name, no words)
    from sqlalchemy import text as sql

    tables = [r[0] for r in db.execute(sql("select tablename from pg_tables where schemaname='public'"))]
    for t in tables:
        hits = db.execute(sql(f'select count(*) from "{t}" where cast("{t}".* as text) like :m'), {"m": "%SECRET-TRANSCRIPT-MARKER%"}).scalar()  # noqa: S608
        assert hits == 0, t


def test_who_talked_reaches_a_session_already_sent_and_nothing_else(client, db, monkeypatch):
    """Brett, Nov 13: Terra in the Observatory went from a Processor opened before it counted speaking times. Its
    numbers can follow on their own: the session's talk is filled (a start set on the review page kept), no read starts."""
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"played_on": "2026-08-29", "source": "transcript"}]})
    s = db.scalar(select(GameSession))
    s.talk = {"start": "18:32"}
    db.commit()
    monkeypatch.setattr(admin_sessions, "read_transcript_in_background", lambda *a: pytest.fail("no read for who talked"))
    talk = {"speakers": {"A": 120.5, "B": 60}, "length": 3600}
    h = {"Authorization": f"Bearer {TOKEN}"}
    assert client.post("/api/transcripts/talk", json={"played_on": "2026-08-29", "talk": talk}).status_code == 401
    r = client.post("/api/transcripts/talk", json={"played_on": "2026-08-29", "talk": talk}, headers=h)
    assert r.status_code == 200 and r.json()["speakers"] == 2
    db.refresh(s)
    assert s.talk == {"start": "18:32", "speakers": {"A": 120.5, "B": 60.0}, "length": 3600}
    assert client.post("/api/transcripts/talk", json={"played_on": "2026-09-01", "talk": talk}, headers=h).status_code == 404
    assert client.post("/api/transcripts/talk", json={"played_on": "2026-08-29", "talk": {}}, headers=h).status_code == 422
