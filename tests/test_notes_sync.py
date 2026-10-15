import io
import zipfile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import admin_notes, auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.gdocs import doc_id_from_url, html_to_text, parse_export
from app.importer import import_bundle
from app.main import app
from app.models import NoteSnapshot, NoteSource
from app.notes_sync import store_export, sync_sources

HTML = """<html><head><style>.c1{color:red}</style><title>t</title></head><body>
<h1>Session 17</h1><p>The party met <b>Uni</b>.</p>
<ul><li>First</li><li>Second<ul><li>Nested</li></ul></li></ul>
<p><img src="images/image1.png"></p>
<table><tr><td>A</td><td>B</td></tr></table></body></html>"""


def make_zip(html=HTML, images={"images/image1.png": b"\x89PNG fake"}):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Notes.html", html)
        for name, data in images.items():
            z.writestr(name, data)
    return buf.getvalue()


def test_doc_id_from_url():
    url = "https://docs.google.com/document/d/1OLwxN8HOXO2E5VlpTcxH0Dm8cYZXYBftlIWowGQm3wg/edit?tab=t.0#heading=h.x"
    assert doc_id_from_url(url) == "1OLwxN8HOXO2E5VlpTcxH0Dm8cYZXYBftlIWowGQm3wg"
    assert doc_id_from_url("not a link") is None


def test_html_to_text_keeps_structure():
    text = html_to_text(HTML)
    assert "# Session 17" in text
    assert "The party met Uni." in text
    assert "- First" in text and "  - Nested" in text
    assert "[image: images/image1.png]" in text
    assert "color:red" not in text


def test_parse_export_collects_images():
    doc = parse_export(make_zip())
    assert doc.images["images/image1.png"] == ("image/png", b"\x89PNG fake")


def source(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    from app.models import Campaign

    s = NoteSource(campaign_id=db.scalar(select(Campaign)).id, google_doc_id="x" * 30)
    db.add(s)
    db.flush()
    return s


def test_snapshot_only_when_content_changes(db):
    s = source(db)
    assert store_export(db, s, parse_export(make_zip()), "Notes")
    assert not store_export(db, s, parse_export(make_zip()))
    assert store_export(db, s, parse_export(make_zip(images={"images/image1.png": b"new picture"})))
    assert len(s.snapshots) == 2
    assert s.title == "Notes"


def test_one_failing_doc_does_not_stop_others(db):
    good, bad = source(db), None
    from app.models import NoteSource as NS

    bad = NS(campaign_id=good.campaign_id, google_doc_id="y" * 30, title="Bad")
    db.add(bad)
    db.flush()

    def fetch(doc_id):
        if doc_id.startswith("y"):
            raise ValueError("boom")
        return "Good doc", parse_export(make_zip())

    results = sync_sources(db, [good, bad], fetch)
    assert results["Good doc"].startswith("updated")
    assert results["Bad"] == "failed: boom"


@pytest.fixture
def admin_client(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com,player@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "admin@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    client.get("/auth/callback", follow_redirects=False)
    yield client
    app.dependency_overrides.clear()


def test_notes_page_admin_only(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "player@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    client.get("/auth/callback", follow_redirects=False)
    assert client.get("/admin/notes").status_code == 403
    app.dependency_overrides.clear()


def test_add_source_and_sync(admin_client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    url = "https://docs.google.com/document/d/" + "a" * 44 + "/edit"
    admin_client.post("/admin/notes/sources", data={"url": url})
    assert db.scalar(select(NoteSource)).google_doc_id == "a" * 44

    async def drive_token(request):
        return {"userinfo": {"email": "admin@example.com"}, "scope": f"openid email {admin_notes.DRIVE_READONLY}"}

    class Resp:
        def __init__(self, status=200, content=b"", json_data=None):
            self.status_code, self.content, self._json, self.text = status, content, json_data, ""

        def raise_for_status(self):
            pass

        def json(self):
            return self._json

    async def fake_get(url, token=None, timeout=None):
        return Resp(json_data={"name": "DnD Notes"}) if "fields=name" in url else Resp(content=make_zip())

    monkeypatch.setattr(admin_notes.oauth.google_drive, "authorize_access_token", drive_token)
    monkeypatch.setattr(admin_notes.oauth.google_drive, "get", fake_get)
    page = admin_client.get("/admin/notes/callback")
    assert "DnD Notes: updated" in page.text
    snap = db.scalar(select(NoteSnapshot))
    view = admin_client.get(f"/admin/notes/snapshots/{snap.id}")
    assert "/admin/notes/images/" in view.text


def test_sync_rejects_missing_drive_scope(admin_client, db, monkeypatch):
    async def drive_token(request):
        return {"userinfo": {"email": "admin@example.com"}, "scope": "openid email"}

    monkeypatch.setattr(admin_notes.oauth.google_drive, "authorize_access_token", drive_token)
    assert "read-only Drive access" in admin_client.get("/admin/notes/callback").text


def test_google_errors_explained_and_shown_in_red(admin_client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    admin_client.post("/admin/notes/sources", data={"url": "https://docs.google.com/document/d/" + "b" * 44 + "/edit"})

    async def drive_token(request):
        return {"userinfo": {"email": "admin@example.com"}, "scope": admin_notes.DRIVE_READONLY}

    class Resp:
        status_code = 403
        text = ""

        def json(self):
            return {"error": {"code": 403, "message": "Drive API has not been used", "errors": [{"reason": "accessNotConfigured"}]}}

    async def fake_get(url, token=None, timeout=None):
        return Resp()

    monkeypatch.setattr(admin_notes.oauth.google_drive, "authorize_access_token", drive_token)
    monkeypatch.setattr(admin_notes.oauth.google_drive, "get", fake_get)
    page = admin_client.get("/admin/notes/callback").text
    assert "Sync failed." in page
    assert 'class="bad"' in page
    assert "Google Drive API isn't turned on" in page
    assert db.scalar(select(NoteSource)).last_synced_at is None
