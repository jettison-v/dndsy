import json

import pytest
from fastapi.testclient import TestClient

from app import auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.main import app


def sign_in(client, monkeypatch, email):
    monkeypatch.setattr(
        auth.oauth.google,
        "authorize_access_token",
        lambda request: _token(email),
    )
    client.get("/auth/callback", follow_redirects=False)


async def _token(email):
    return {"userinfo": {"email": email, "email_verified": True, "name": email}}


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com,player@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


def upload(client, payload):
    data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return client.post("/manage/backups/import", files={"file": ("bundle.json", data, "application/json")})


def test_import_requires_admin(client, monkeypatch):
    assert client.get("/manage/backups", follow_redirects=False).status_code == 303
    sign_in(client, monkeypatch, "player@example.com")
    assert client.get("/manage/backups").status_code == 403
    assert upload(client, {"campaign": {"slug": "x", "name": "X"}}).status_code == 403


def token_in(page: str) -> str:
    import re

    return re.search(r'name="token" value="([^"]+)"', page).group(1)


def test_admin_can_import(client, monkeypatch, db):
    from sqlalchemy import select

    from app.models import Entity

    sign_in(client, monkeypatch, "admin@example.com")
    page = client.get("/")
    assert "Manage" in page.text and "/manage/backups" in page.text
    r = upload(client, {"campaign": {"slug": "x", "name": "X"}, "entities": [{"kind": "npc", "name": "Uni"}]})
    assert "Preview: bundle.json" in r.text and "Nothing saved yet" in r.text and "Uni" in r.text
    assert db.scalar(select(Entity)) is None  # nothing written by the preview
    r = client.post("/manage/backups/import/apply", data={"token": token_in(r.text)})
    assert "entities created: 1" in r.text and db.scalar(select(Entity)).name == "Uni"
    assert "expired or was already imported" in client.post("/manage/backups/import/apply", data={"token": "not-a-real-one"}).text


def test_preview_shows_what_would_change_and_can_keep_descriptions(client, monkeypatch, db):
    from sqlalchemy import select

    from app.importer import import_bundle
    from app.models import Entity

    bundle = {"campaign": {"slug": "x", "name": "X"}, "entities": [{"kind": "npc", "name": "Uni", "summary": "Old text."}]}
    import_bundle(db, bundle)
    uni = db.scalar(select(Entity))
    uni.summary = "Edited here since."
    db.flush()
    sign_in(client, monkeypatch, "admin@example.com")

    same = upload(client, {"campaign": {"slug": "x", "name": "X"}, "entities": [{"kind": "npc", "name": "Uni", "summary": "Edited here since."}]})
    assert "Nothing would change" in same.text

    r = upload(client, bundle)  # the old file again
    assert "1</b> existing entry would change" in r.text and "Edited here since." in r.text and "Old text." in r.text
    assert "Keep the current descriptions" in r.text
    db.refresh(uni)
    assert uni.summary == "Edited here since."  # previewing changed nothing
    client.post("/manage/backups/import/apply", data={"token": token_in(r.text), "keep_text": "1"})
    db.refresh(uni)
    assert uni.summary == "Edited here since."  # kept
    r = upload(client, bundle)
    client.post("/manage/backups/import/apply", data={"token": token_in(r.text)})
    db.refresh(uni)
    assert uni.summary == "Old text."  # replaced only when confirmed without keeping


def test_cancel_discards_the_upload(client, monkeypatch, db):
    sign_in(client, monkeypatch, "admin@example.com")
    r = upload(client, {"campaign": {"slug": "x", "name": "X"}, "entities": [{"kind": "npc", "name": "Uni"}]})
    token = token_in(r.text)
    assert "Nothing changed" in client.post("/manage/backups/import/cancel", data={"token": token}, follow_redirects=True).text
    assert "expired or was already imported" in client.post("/manage/backups/import/apply", data={"token": token}).text


def test_bad_file_shows_error(client, monkeypatch):
    sign_in(client, monkeypatch, "admin@example.com")
    assert "valid JSON" in upload(client, b"{not json").text
    assert "Nothing was imported" in upload(client, {"members": []}).text
