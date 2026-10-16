"""Manage › People: access levels set in the app (app/access.py)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import access, auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.importer import import_bundle
from app.main import app
from app.models import User


@pytest.fixture
def env(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("owner@example.com,player@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("owner@example.com"))
    monkeypatch.setattr(config, "REVIEWER_EMAILS", frozenset())
    app.dependency_overrides[get_db] = lambda: db
    yield
    app.dependency_overrides.clear()


def sign_in(monkeypatch, email):
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": email, "email_verified": True, "name": email.split("@")[0].title()}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    r = c.get("/auth/callback", follow_redirects=False)
    return c, r


def test_owner_adds_a_reviewer_who_can_then_review(env, monkeypatch, db):
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    owner.post("/admin/people", data={"email": "New@Example.com", "name": "Nia", "level": "reviewer"})
    assert db.scalar(select(User).where(User.email == "new@example.com")).access == "reviewer"
    nia, r = sign_in(monkeypatch, "new@example.com")
    assert r.headers["location"] == "/"  # allowed in without being in ALLOWED_EMAILS
    assert nia.get("/admin/sessions").status_code == 200
    assert nia.get("/admin/people").status_code == 403
    owner.post("/admin/people/update", data={"email": "new@example.com", "level": "admin"})
    assert nia.get("/admin/people").status_code == 200


def test_removed_person_is_locked_out_even_if_on_railway_list(env, monkeypatch, db):
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    player, _ = sign_in(monkeypatch, "player@example.com")
    assert player.get("/characters").status_code == 200
    owner.post("/admin/people/update", data={"email": "player@example.com", "level": "player", "remove": "1"})
    assert player.get("/characters", follow_redirects=False).headers["location"] == "/login"
    _, r = sign_in(monkeypatch, "player@example.com")
    assert "not_allowed" in r.headers["location"]


def test_owner_cant_be_demoted_and_admins_cant_lower_themselves(env, monkeypatch, db):
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    owner.post("/admin/people/update", data={"email": "owner@example.com", "level": "removed"})
    assert access.level("owner@example.com") == "admin"
    owner.post("/admin/people", data={"email": "boss@example.com", "level": "admin"})
    boss, _ = sign_in(monkeypatch, "boss@example.com")
    boss.post("/admin/people/update", data={"email": "boss@example.com", "level": "player"})
    assert access.level("boss@example.com") == "admin"


def test_imported_members_need_an_invite(env, monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "members": [{"email": "mary@example.com", "name": "Mary", "role": "dm"}]})
    _, r = sign_in(monkeypatch, "mary@example.com")
    assert "not_allowed" in r.headers["location"]
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    page = owner.get("/admin/people").text
    assert "Mary" in page and "Not invited yet" in page and "player@example.com" in page


def test_dm_never_sees_character_notes_even_as_admin(env, monkeypatch, db):
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    owner.post("/admin/people", data={"email": "dm@example.com", "level": "admin", "is_dm": "1"})
    dm, _ = sign_in(monkeypatch, "dm@example.com")
    assert dm.get("/admin/usage").status_code == 200
    assert dm.get("/admin/notes").status_code == 403
    assert "/admin/notes" not in dm.get("/").text and "/admin/people" in dm.get("/").text
    assert owner.get("/admin/notes").status_code == 200


def test_players_cant_manage_people(env, monkeypatch, db):
    player, _ = sign_in(monkeypatch, "player@example.com")
    assert player.get("/admin/people").status_code == 403
    assert player.post("/admin/people", data={"email": "x@example.com", "level": "admin"}).status_code == 403
    assert db.scalar(select(User).where(User.email == "x@example.com")) is None


def test_sign_in_records_name_and_time(env, monkeypatch, db):
    sign_in(monkeypatch, "player@example.com")
    u = db.scalar(select(User).where(User.email == "player@example.com"))
    assert u.name == "Player" and u.last_seen_at is not None and u.access is None


def test_invite_from_the_list(env, monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "members": [{"email": "mary@example.com", "name": "Mary", "role": "dm"}]})
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    assert 'name="level"' in owner.get("/admin/people").text
    owner.post("/admin/people/update", data={"email": "mary@example.com", "level": "reviewer"})
    assert access.level("mary@example.com") == "reviewer" and access.is_dm("mary@example.com")
