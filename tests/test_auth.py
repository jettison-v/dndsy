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
def client(monkeypatch, db):
    from app.db import get_db

    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    yield TestClient(app)
    app.dependency_overrides.clear()


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
    """A standing rule (CLAUDE.md › Stack): only people on the email allowlist sign in; taking someone off ends their
    session at once."""
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
    """A standing rule (CLAUDE.md): the dev login is local only, never on beta or production."""
    c = TestClient(app)
    monkeypatch.setattr(config, "DEV_LOGIN_EMAIL", "")
    assert c.get("/dev/login", follow_redirects=False).headers["location"] == "/login"
    monkeypatch.setattr(config, "DEV_LOGIN_EMAIL", "player@example.com")
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    assert c.get("/dev/login", follow_redirects=False).headers["location"] == "/login"
    monkeypatch.setattr(config, "IS_PRODUCTION", False)
    assert c.get("/dev/login", follow_redirects=False).headers["location"] == "/"


def test_dev_login_opens_the_page_asked_for_on_this_site_only(monkeypatch):
    """A link to try a change locally lands on its page; never another site."""
    monkeypatch.setattr(config, "DEV_LOGIN_EMAIL", "player@example.com")
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    c = TestClient(app)
    where = lambda nxt: c.get("/dev/login", params={"next": nxt}, follow_redirects=False).headers["location"]  # noqa: E731
    assert where("/characters/1/battle") == "/characters/1/battle"
    for bad in ("https://evil.example", "//evil.example", "/\\evil.example", "battle"):
        assert where(bad) == "/", bad


def test_dev_login_as_someone_else_who_can_sign_in(monkeypatch):
    c = TestClient(app)
    monkeypatch.setattr(config, "DEV_LOGIN_EMAIL", "player@example.com")
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com,other@example.com"))
    assert c.get("/dev/login?as=stranger@example.com", follow_redirects=False).headers["location"] == "/login"
    assert c.get("/dev/login?as=other@example.com", follow_redirects=False).headers["location"] == "/"
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    assert TestClient(app).get("/dev/login?as=other@example.com", follow_redirects=False).headers["location"] == "/login"


def test_dev_login_as_the_campaigns_dm_or_a_player_needs_no_email(monkeypatch, db):
    """`?as=dm` / `?as=player`: the campaign's DM, or one of its players other than you, so a two-person link works."""
    from app.auth import _dev_person
    from tests.roles import set_role

    monkeypatch.setattr(config, "DEV_LOGIN_EMAIL", "player@example.com")
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com,other@example.com,dm@example.com"))
    set_role(db, "dm@example.com", "dm")
    set_role(db, "player@example.com", "player")
    set_role(db, "other@example.com", "player")
    assert _dev_person(db, "dm", "/c/main/party") == "dm@example.com"
    assert _dev_person(db, "player", "/c/main/") == "other@example.com"  # not you
    assert _dev_person(db, "dm", "/c/nowhere/") == "x@invalid"  # no such campaign: no sign-in
    assert _dev_person(db, "other@example.com", "/") == "other@example.com"  # an email as it is


def test_www_goes_to_askdnd_ai():
    """One address (Brett, 2026-11-02): www.askdnd.ai sends you to the same page at askdnd.ai, so one sign-in and one
    address Google returns to."""
    r = TestClient(app, base_url="https://www.askdnd.ai").get("/c/main/campaign?tab=map", follow_redirects=False)
    assert (r.status_code, r.headers["location"]) == (308, "https://askdnd.ai/c/main/campaign?tab=map")
    assert TestClient(app, base_url="https://askdnd.ai").get("/login", follow_redirects=False).status_code == 200


def test_a_page_opened_signed_out_opens_again_after_signing_in(monkeypatch, db):
    """Brett, 2026-11-05: askdnd.ai/twin, opened signed out, landed on the Story page after signing in."""
    from fastapi.testclient import TestClient

    from app import auth, config
    from app.config import parse_allowlist
    from app.db import get_db
    from app.main import app

    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)
    page = {"accept": "text/html,application/xhtml+xml"}
    r = c.get("/twin?x=1", headers=page, follow_redirects=False)
    assert r.headers["location"] == "/login?next=%2Ftwin%3Fx%3D1"
    assert 'href="/auth/google?next=/twin%3Fx%3D1"' in c.get(r.headers["location"]).text
    assert c.get("/twin", headers={**page, "HX-Request": "true"}, follow_redirects=False).headers["location"] == "/login"  # (not a page visit)

    c.get("/auth/google?next=/twin%3Fx%3D1", follow_redirects=False)

    async def token(request):
        return {"userinfo": {"email": "player@example.com", "email_verified": True, "name": "Pat"}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    assert c.get("/auth/callback", follow_redirects=False).headers["location"] == "/twin?x=1"
    assert c.get("/login?next=/party", follow_redirects=False).headers["location"] == "/party"  # (signed in already)
    app.dependency_overrides.clear()


def test_after_signing_in_askdnd_goes_only_to_its_own_pages():
    from app.auth import back_to

    assert back_to("https://evil.example/") == "/" and back_to("//evil.example/") == "/" and back_to("/\\evil.example") == "/"
    assert back_to("/login?next=/x") == "/" and back_to("") == "/" and back_to("/c/main/campaign?tab=map") == "/c/main/campaign?tab=map"
    # (code review, Nov 5: a browser drops tabs and newlines, so "/\t/evil" would open //evil)
    assert back_to("/\t/evil.example") == "/" and back_to("/\n/evil.example") == "/" and back_to("/x\r") == "/"
