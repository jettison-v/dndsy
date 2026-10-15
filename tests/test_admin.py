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
    return client.post("/admin/import", files={"file": ("bundle.json", data, "application/json")})


def test_import_requires_admin(client, monkeypatch):
    assert client.get("/admin/import", follow_redirects=False).status_code == 303
    sign_in(client, monkeypatch, "player@example.com")
    assert client.get("/admin/import").status_code == 403
    assert upload(client, {"campaign": {"slug": "x", "name": "X"}}).status_code == 403


def test_admin_can_import(client, monkeypatch):
    sign_in(client, monkeypatch, "admin@example.com")
    page = client.get("/")
    assert "Manage" in page.text and "/admin/import" in page.text
    r = upload(client, {"campaign": {"slug": "x", "name": "X"}, "entities": [{"kind": "npc", "name": "Uni"}]})
    assert "entities created: 1" in r.text


def test_bad_file_shows_error(client, monkeypatch):
    sign_in(client, monkeypatch, "admin@example.com")
    assert "valid JSON" in upload(client, b"{not json").text
    assert "Nothing was imported" in upload(client, {"members": []}).text
