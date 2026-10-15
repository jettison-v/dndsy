import pytest
from fastapi.testclient import TestClient

from app import auth, config
from app.config import is_allowed, parse_allowlist
from app.main import app


def test_parse_allowlist_normalizes():
    assert parse_allowlist(" A@x.com, b@Y.com ,,") == {"a@x.com", "b@y.com"}
    assert parse_allowlist(None) == frozenset()
    assert parse_allowlist("") == frozenset()


def test_is_allowed():
    allow = parse_allowlist("player@example.com")
    assert is_allowed("Player@Example.com", allow)
    assert not is_allowed("someone@example.com", allow)
    assert not is_allowed(None, allow)
    assert not is_allowed("", allow)
    assert not is_allowed("player@example.com", frozenset())


def fake_google(userinfo):
    async def authorize_access_token(request):
        return {"userinfo": userinfo}

    return authorize_access_token


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    return TestClient(app)


def test_allowed_user_signs_in(client, monkeypatch):
    monkeypatch.setattr(
        auth.oauth.google,
        "authorize_access_token",
        fake_google({"email": "Player@example.com", "email_verified": True, "name": "Player"}),
    )
    response = client.get("/auth/callback", follow_redirects=False)
    assert response.headers["location"] == "/"
    home = client.get("/")
    assert home.status_code == 200
    assert "Previously on" in home.text


def test_unlisted_user_is_rejected(client, monkeypatch):
    monkeypatch.setattr(
        auth.oauth.google,
        "authorize_access_token",
        fake_google({"email": "stranger@example.com", "email_verified": True}),
    )
    response = client.get("/auth/callback", follow_redirects=False)
    assert response.headers["location"] == "/login?error=not_allowed"
    assert client.get("/", follow_redirects=False).status_code == 303


def test_unverified_email_is_rejected(client, monkeypatch):
    monkeypatch.setattr(
        auth.oauth.google,
        "authorize_access_token",
        fake_google({"email": "player@example.com", "email_verified": False}),
    )
    response = client.get("/auth/callback", follow_redirects=False)
    assert response.headers["location"] == "/login?error=not_allowed"


def test_removing_from_allowlist_ends_session(client, monkeypatch):
    monkeypatch.setattr(
        auth.oauth.google,
        "authorize_access_token",
        fake_google({"email": "player@example.com", "email_verified": True}),
    )
    client.get("/auth/callback", follow_redirects=False)
    monkeypatch.setattr(config, "ALLOWED_EMAILS", frozenset())
    assert client.get("/", follow_redirects=False).status_code == 303


def test_logout(client, monkeypatch):
    monkeypatch.setattr(
        auth.oauth.google,
        "authorize_access_token",
        fake_google({"email": "player@example.com", "email_verified": True}),
    )
    client.get("/auth/callback", follow_redirects=False)
    client.post("/logout", follow_redirects=False)
    assert client.get("/", follow_redirects=False).status_code == 303


def test_dev_login_only_when_configured_and_not_production(monkeypatch):
    c = TestClient(app)
    monkeypatch.setattr(config, "DEV_LOGIN_EMAIL", "")
    assert c.get("/dev/login", follow_redirects=False).headers["location"] == "/login"
    monkeypatch.setattr(config, "DEV_LOGIN_EMAIL", "player@example.com")
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    assert c.get("/dev/login", follow_redirects=False).headers["location"] == "/login"
    monkeypatch.setattr(config, "IS_PRODUCTION", False)
    assert c.get("/dev/login", follow_redirects=False).headers["location"] == "/"
