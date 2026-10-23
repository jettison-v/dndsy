import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.importer import import_bundle
from app.main import app
from app.models import GameSession


@pytest.fixture
def dm_client(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com,dm@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "dm@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    yield c
    app.dependency_overrides.clear()


def test_reviewer_can_review_but_not_see_admin_pages(dm_client, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": 29}]})
    sid = db.scalar(select(GameSession)).id
    assert dm_client.get("/c/main/manage/sessions").status_code == 200
    assert dm_client.get(f"/c/main/manage/sessions/{sid}").status_code == 200
    for path in ("/c/main/manage/sessions/doc", "/manage/backups", "/manage/usage"):
        assert dm_client.get(path).status_code == 403, path
    home = dm_client.get("/").text
    assert "Manage" in home and "/manage/sessions" in home
    assert "/manage/sessions/doc" not in home and "/manage/usage" not in home and "/manage/backups" not in home
