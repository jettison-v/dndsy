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
    assert player.get("/party").status_code == 200
    owner.post("/admin/people/update", data={"email": "player@example.com", "level": "player", "remove": "1"})
    assert player.get("/party", follow_redirects=False).headers["location"] == "/login"
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
    from app.models import Campaign, Character, NoteSnapshot, NoteSource

    owner, _ = sign_in(monkeypatch, "owner@example.com")
    owner.post("/admin/people", data={"email": "dm@example.com", "level": "admin", "is_dm": "1"})
    dm, _ = sign_in(monkeypatch, "dm@example.com")
    assert dm.get("/admin/usage").status_code == 200
    assert "/admin/people" in dm.get("/").text
    # The campaign doc is for the whole table; an old character doc stays hidden from the DM
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "entities": [{"kind": "pc", "name": "Cole", "character": {"player_name": "Brett"}}]})
    campaign = db.scalar(select(Campaign))
    char = db.scalar(select(Character))
    if True:
        src = NoteSource(campaign_id=campaign.id, google_doc_id="c" * 30, title="Secret Cole doc", character_id=char.id)
        src.snapshots.append(NoteSnapshot(content_hash="h", text="secret plan"))
        db.add(src)
        db.flush()
        assert "Secret Cole doc" not in dm.get("/admin/notes").text and "Secret Cole doc" in owner.get("/admin/notes").text
        assert "secret plan" not in dm.get(f"/admin/notes/snapshots/{src.snapshots[0].id}", follow_redirects=False).text
    assert dm.get("/admin/notes").status_code == 200 and owner.get("/admin/notes").status_code == 200


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


def test_assign_character_on_people_page(env, monkeypatch, db):
    from app.models import Character

    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "entities": [{"kind": "pc", "name": "Cole", "character": {"player_name": "Brett"}}]})
    cole = db.scalar(select(Character))
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    assert f'<option value="{cole.id}" >Cole</option>' in owner.get("/admin/people").text
    owner.post("/admin/people/update", data={"email": "player@example.com", "level": "player", "character_id": str(cole.id)})
    assert cole.owner.email == "player@example.com"
    owner.post("/admin/people/update", data={"email": "owner@example.com", "character_id": str(cole.id)})
    assert cole.owner.email == "owner@example.com" and access.level("owner@example.com") == "admin"
    owner.post("/admin/people/update", data={"email": "owner@example.com", "character_id": "none"})
    assert cole.owner_id is None


def test_access_chart_is_drawn_from_the_rules_the_app_uses():
    from app import access

    rows = {r["what"]: r for r in access.chart()["rows"]}
    assert access.chart()["levels"] == ["Player", "Reviewer", "Admin"]
    decide = rows["Decide on the table's suggestions"]
    assert decide["cells"] == ["no", "yes", "yes"] and decide["dm"] == "gains"  # the DM decides even as a Player
    notes = rows["Players' notes, stars, reminders and shortlists"]
    assert notes["cells"] == ["yes", "yes", "yes"] and notes["dm"] == "never"  # never the DM, even as Admin
    assert rows["People: invite, access, DM tick, who plays which character"]["cells"] == ["no", "no", "yes"]
    assert rows["Notes, stars, reminders, shortlists and the Wild Shape switch"]["cells"] == ["own"] * 3
    for r in access.CHART:  # every rule in the chart is one the app checks
        if r[2] != "own":
            access.allows(r[2], access.PLAYER)
    assert "Never, even as Admin" in access.summary(access.ADMIN, True) or "never sees" in access.summary(access.ADMIN, True)


def test_people_page_shows_the_chart_and_each_persons_summary(env, monkeypatch, db):
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    owner.post("/admin/people", data={"email": "dm@example.com", "level": "player", "is_dm": "1"})
    page = owner.get("/admin/people").text
    assert "What each access level can do" in page and "Yes, even as Player" in page and "Not included for anyone" in page
    assert "as DM, decides on suggestions" in page  # the DM's own row explains what the tick adds
