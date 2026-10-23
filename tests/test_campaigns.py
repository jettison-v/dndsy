"""More than one campaign (data organization step 4): /c/<campaign>/ addresses, the current campaign per person,
who can open which campaign, moving characters, and Manage › Campaigns."""

import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app import access, auth, characters, config
from app.config import parse_allowlist
from app.db import get_db
from app.importer import import_bundle
from app.main import app
from app.models import Campaign, CampaignCharacter, Character, Entity, PlayerNote, User
from tests.roles import set_role
from tests.test_characters import BUNDLE, char, fake_fetch, no_network  # noqa: F401

OTHER = {"campaign": {"slug": "strahd", "name": "Curse of Strahd", "dm_name": "Brett"},
         "entities": [{"kind": "npc", "name": "Ireena", "summary": "A burgomaster's daughter."}]}


def sign_in(monkeypatch, email):
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": email, "email_verified": True, "name": email.split("@")[0].title()}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    return c


@pytest.fixture
def two(monkeypatch, db):
    """Main (Cole, Trah, Big C) and Curse of Strahd. pat@ plays in Main only; sam@ plays in Strahd only;
    admin@ is an admin with no role anywhere."""
    monkeypatch.setattr(config, "ALLOWED_EMAILS", frozenset())
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    monkeypatch.setattr(config, "REVIEWER_EMAILS", frozenset())
    import_bundle(db, BUNDLE)
    import_bundle(db, OTHER)
    main, strahd = (db.scalar(select(Campaign).where(Campaign.slug == s)) for s in ("main", "strahd"))
    for email, campaign in (("pat@example.com", main), ("sam@example.com", strahd)):
        u = set_role(db, email, "player", email.split("@")[0].title(), campaign)
        u.access = "member"
    db.flush()
    access.invalidate()
    app.dependency_overrides[get_db] = lambda: db
    yield {"main": main, "strahd": strahd, "pat": sign_in(monkeypatch, "pat@example.com"),
           "sam": sign_in(monkeypatch, "sam@example.com"), "admin": sign_in(monkeypatch, "admin@example.com")}
    app.dependency_overrides.clear()


def test_story_pages_live_at_their_campaigns_address(two, db):
    pat, sam = two["pat"], two["sam"]
    r = pat.get("/", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/c/main/"
    assert pat.get("/sessions?x=1", follow_redirects=False).headers["location"] == "/c/main/sessions?x=1"
    assert sam.get("/campaign", follow_redirects=False).headers["location"] == "/c/strahd/campaign"
    assert "Ireena" in sam.get("/c/strahd/campaign").text and "Ireena" not in pat.get("/c/main/campaign").text
    assert pat.get("/c/strahd/campaign").status_code == 404  # not one of Pat's campaigns
    # Another campaign's entry, by its number: not in Pat's Reader or side panel
    ireena = db.scalar(select(Entity.id).where(Entity.name == "Ireena"))
    assert "Ireena" not in pat.get(f"/c/main/campaign?open={ireena}").text
    assert pat.get(f"/c/main/campaign/{ireena}/read").status_code == 404 and pat.get(f"/c/main/campaign/{ireena}/peek").status_code == 404
    assert pat.get("/c/nowhere/").status_code == 404
    assert pat.get("/campaign", headers={"HX-Request": "true"}, follow_redirects=False).status_code == 200  # page parts stay


def test_the_switcher_lists_your_campaigns_and_remembers_the_last(two, db):
    admin, pat = two["admin"], two["pat"]
    set_role(db, "admin@example.com", "dm", campaign=two["strahd"])
    access.invalidate()
    page = admin.get("/c/main/").text
    assert 'id="campaign-menu"' in page and 'href="/c/strahd/"' in page and 'href="/c/main/campaign"' in page
    menu = page.split('id="campaign-menu"')[1].split("</div>\n  </div>")[0]
    assert "Main<small>You're here</small>" in menu and "Curse of Strahd<small>DM</small>" in menu  # your role elsewhere
    one = pat.get("/c/main/").text
    assert 'id="campaign-menu"' not in one  # one campaign: no switcher…
    assert '<span class="campaign-name" title="The campaign you\'re in">Main</span>' in one  # …but its name is shown
    admin.get("/c/strahd/party")  # opening a campaign makes it the current one
    assert db.scalar(select(User).where(User.email == "admin@example.com")).current_campaign_id == two["strahd"].id
    assert admin.get("/", follow_redirects=False).headers["location"] == "/c/strahd/"
    assert "Curse of Strahd" in admin.get("/admin/people").text  # Manage pages show the current campaign


def test_party_and_characters_belong_to_the_campaign(two, db):
    pat, sam = two["pat"], two["sam"]
    cole = char(db, "Cole")
    assert "Cole" in pat.get("/party").text and "Cole" not in sam.get("/party").text
    assert pat.get(f"/characters/{cole.id}").status_code == 200
    assert sam.get(f"/characters/{cole.id}").status_code == 404  # not at Cole's table
    assert two["admin"].get(f"/characters/{cole.id}").status_code == 200


def test_roles_are_per_campaign(two, db):
    set_role(db, "pat@example.com", "dm", campaign=two["strahd"])
    assert access.role("pat@example.com", two["strahd"].id) == "dm" and access.role("pat@example.com", two["main"].id) == "player"
    pat = two["pat"]
    pat.get("/c/strahd/")
    assert pat.get("/manage/house-rules").status_code == 200  # the DM of the campaign Pat is in now
    pat.get("/c/main/")
    assert pat.get("/manage/house-rules").status_code == 403  # just a player here


def test_moving_a_character_keeps_its_story_in_the_old_campaign(two, db):
    cole = char(db, "Cole")
    old = cole.membership
    db.add(PlayerNote(character_id=cole.id, kind="quest", title="Find my sister", campaign_id=two["main"].id))
    db.add(PlayerNote(character_id=cole.id, kind="combo", title="Moonbeam then dodge"))
    db.flush()
    characters.move(db, cole, two["strahd"].id)
    assert old.left_on is not None and db.get(Entity, old.entity_id).campaign_id == two["main"].id  # the story stays
    assert cole.campaign_id == two["strahd"].id and cole.entity.campaign_id == two["strahd"].id and cole.entity.kind.value == "pc"
    from app.player_notes import notes_for

    titles = [n.title for n in notes_for(db, cole, {"email": "admin@example.com"})]
    assert titles == ["Moonbeam then dodge"]  # the quest stays with Main
    characters.move(db, cole, two["main"].id)  # back again: the same story page
    assert cole.entity.id == old.entity_id and len(cole.memberships) == 3
    assert len(list(db.scalars(select(CampaignCharacter).where(CampaignCharacter.character_id == cole.id,
                                                                  CampaignCharacter.left_on.is_(None))))) == 1


def test_manage_campaigns_creates_and_moves_and_table_adds(two, db):
    admin, pat = two["admin"], two["pat"]
    assert pat.get("/manage/campaigns").status_code == 403
    page = admin.get("/manage/campaigns").text
    assert "Curse of Strahd" in page and "/c/strahd" in page and "Move" in page
    r = admin.post("/manage/campaigns", data={"name": "Curse of Strahd", "dm_name": "Mary"}, follow_redirects=False)
    assert r.headers["location"] == "/c/curse-of-strahd/manage/table"  # straight to its people and characters
    assert db.scalar(select(Campaign).where(Campaign.slug == "curse-of-strahd")).dm_name == "Mary"
    trah = char(db, "Trah")
    admin.post(f"/manage/campaigns/characters/{trah.id}/move", data={"campaign_id": str(two["strahd"].id)})
    assert trah.campaign_id == two["strahd"].id
    admin.post(f"/manage/campaigns/characters/{trah.id}/move", data={"campaign_id": ""})
    assert trah.campaign_id is None and "Not in a campaign" in admin.get("/manage/campaigns").text
    admin.post("/c/strahd/manage/table/characters", data={"name": "Ismark"})  # added on the campaign's Table
    ismark = db.scalar(select(Character).where(Character.name == "Ismark"))
    assert ismark.campaign_id == two["strahd"].id and ismark.entity.name == "Ismark"
    assert pat.post("/c/main/manage/table/characters", data={"name": "Nope"}).status_code == 403


def test_a_character_dnd_beyond_puts_elsewhere_is_offered_a_move_never_moved(two, db):
    cole = char(db, "Cole")
    two["main"].ddb_campaign_id, two["strahd"].ddb_campaign_id = "111", "222"
    cole.ddb_campaign_id = "222"
    db.flush()
    page = two["admin"].get("/manage/campaigns").text
    assert "On D&amp;D Beyond, Cole is in" in page and "Move to Curse of Strahd" in page
    assert cole.campaign_id == two["main"].id


def test_new_campaign_offers_dnd_beyond_campaigns_not_set_up_yet(two, db):
    cole = char(db, "Cole")
    characters.refresh(db, cole, lambda _id: {**fake_fetch(_id), "campaign": {"id": 3005233, "name": "The Adventure Begins"}})
    db.flush()
    page = two["admin"].get("/manage/campaigns").text
    assert 'value="The Adventure Begins"' in page and '<option value="3005233">The Adventure Begins</option>' in page


def test_someone_with_no_role_anywhere_sees_no_campaign(two, db, monkeypatch):
    u = User(email="new@example.com", name="New", access="member")
    db.add(u)
    db.flush()
    new = sign_in(monkeypatch, "new@example.com")
    assert access.campaigns_for("new@example.com") == []
    assert new.get("/c/main/").status_code == 404 and new.get("/", follow_redirects=False).status_code == 200


def test_uploads_can_name_their_campaign(db, monkeypatch):
    monkeypatch.setattr(config, "UPLOAD_TOKEN", "t0ken")
    import_bundle(db, BUNDLE)
    import_bundle(db, OTHER)
    app.dependency_overrides[get_db] = lambda: db
    from app import api

    monkeypatch.setattr(api, "_start_draft", lambda *a, **k: None, raising=False)
    c = TestClient(app)
    r = c.post("/api/transcripts", json={"played_on": "2026-10-01", "text": "x", "campaign": "nowhere"},
               headers={"Authorization": "Bearer t0ken"})
    assert r.status_code == 404 and "nowhere" in r.json()["error"]
    app.dependency_overrides.clear()


def test_migration_moves_the_spending_limit_to_the_tool(db_engine):
    env = {"DATABASE_URL": db_engine.url.render_as_string(hide_password=False), "PATH": __import__("os").environ["PATH"]}
    from app.db import Base

    def alembic(*args):
        r = subprocess.run(["alembic", *args], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    Base.metadata.drop_all(db_engine)
    try:
        alembic("upgrade", "bc7d9e3f6a82")
        with db_engine.begin() as c:
            c.execute(text("INSERT INTO campaigns (id, name, slug, dm_name, monthly_limit_usd) VALUES (1, 'Main', 'main', '', 25)"))
        alembic("upgrade", "head")
        with db_engine.connect() as c:
            assert c.execute(text("SELECT key, value FROM tool_settings")).all() == [("monthly_limit_usd", "25")]
        alembic("downgrade", "bc7d9e3f6a82")
        with db_engine.connect() as c:
            assert c.execute(text("SELECT monthly_limit_usd FROM campaigns")).scalar() == 25
        alembic("upgrade", "head")
    finally:
        subprocess.run(["alembic", "downgrade", "base"], env=env, capture_output=True)
        Base.metadata.create_all(db_engine)


def test_a_campaigns_manage_pages_act_on_the_campaign_in_the_address(two, db):
    from app.models import GameSession

    admin = two["admin"]
    main_table, strahd_table = admin.get("/c/main/manage/table").text, admin.get("/c/strahd/manage/table").text
    assert "<b>Pat</b>" in main_table and "<b>Sam</b>" not in main_table and "Ismark" not in main_table
    assert "<b>Sam</b>" in strahd_table and "<b>Pat</b>" not in strahd_table
    admin.post("/c/strahd/manage/table/people", data={"email": "pat@example.com", "role": "reviewer"})
    assert access.role("pat@example.com", two["strahd"].id) == "reviewer" and access.role("pat@example.com", two["main"].id) == "player"
    admin.post("/c/strahd/manage/settings", data={"name": "Strahd", "dm_name": "Brett"})
    assert two["strahd"].name == "Strahd" and two["main"].name != "Strahd"
    s = GameSession(campaign_id=two["strahd"].id, number=1, source="manual")
    db.add(s)
    db.flush()
    r = admin.get(f"/c/main/manage/sessions/{s.id}", follow_redirects=False)  # a Strahd session opens in Strahd
    assert r.headers["location"] == f"/c/strahd/manage/sessions/{s.id}"
    assert two["sam"].get("/c/main/manage/sessions").status_code == 404  # not one of Sam's campaigns


def test_story_holds_previously_on_and_all_sessions(two):
    pat = two["pat"]
    assert pat.get("/c/main/sessions", follow_redirects=False).headers["location"] == "/c/main/?tab=sessions"
    page = pat.get("/c/main/").text
    assert '<div id="t-previously">' in page and '<div id="t-sessions" hidden>' in page
    page = pat.get("/c/main/?tab=sessions").text
    assert '<div id="t-previously" hidden>' in page and '<div id="t-sessions">' in page
