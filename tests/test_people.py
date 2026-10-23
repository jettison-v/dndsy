"""People: tool roles (member, admin) on Manage › Accounts and roles per campaign (DM, reviewer, player) on each
campaign's Manage › Table (app/access.py, app/manage_accounts.py, app/manage_table.py)."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import access, auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.importer import import_bundle
from app.main import app
from app.models import Campaign, CampaignMember, Role, User


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


MAIN = {"campaign": {"slug": "main", "name": "Main"}}


def add(owner, email, role="player", name="", admin=False):
    """What an admin does: an account (Manage › Accounts), then a role in the campaign (its Table)."""
    if admin:
        owner.post("/manage/accounts", data={"email": email, "name": name, "admin": "1"})
    return owner.post("/manage/table/people/add", data={"new_email": email, "name": name, "role": role})


def test_owner_adds_a_reviewer_who_can_then_review(env, monkeypatch, db):
    import_bundle(db, MAIN)
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    add(owner, "New@Example.com", "reviewer", "Nia")
    nia_row = db.scalar(select(User).where(User.email == "new@example.com"))
    assert nia_row.access == "member" and access.role("new@example.com") == "reviewer"
    nia, r = sign_in(monkeypatch, "new@example.com")
    assert r.headers["location"] == "/"  # allowed in without being in ALLOWED_EMAILS
    assert nia.get("/manage/sessions").status_code == 200
    assert nia.get("/manage/accounts").status_code == 403 and nia.get("/manage/table").status_code == 403
    owner.post("/manage/accounts/update", data={"email": "new@example.com", "admin": "1"})
    assert nia.get("/manage/accounts").status_code == 200 and access.role("new@example.com") == "reviewer"


def test_reviewer_is_per_campaign(env, monkeypatch, db):
    import_bundle(db, MAIN)
    other = Campaign(slug="other", name="Other")
    db.add(other)
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    add(owner, "nia@example.com", "reviewer")
    first = db.scalar(select(Campaign).where(Campaign.slug == "main"))
    db.flush()
    assert access.role("nia@example.com", first.id) == "reviewer" and access.role("nia@example.com", other.id) is None
    assert auth.is_reviewer({"email": "nia@example.com"}, first.id) and not auth.is_reviewer({"email": "nia@example.com"}, other.id)


def test_role_changes_keep_the_membership_and_no_role_ends_it(env, monkeypatch, db):
    import_bundle(db, MAIN)
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    add(owner, "nia@example.com", "player")
    owner.post("/manage/table/people", data={"email": "nia@example.com", "role": "dm"})
    rows = list(db.scalars(select(CampaignMember).join(User).where(User.email == "nia@example.com")))
    assert [(m.role, m.left_on) for m in rows] == [(Role.DM, None)]
    owner.post("/manage/table/people", data={"email": "nia@example.com", "role": "none"})
    db.expire_all()
    assert rows[0].left_on is not None and access.role("nia@example.com") is None
    assert "nia@example.com" not in owner.get("/manage/table").text.split("<h2>People</h2>")[1].split("+ Add someone")[0]
    owner.post("/manage/table/people", data={"email": "nia@example.com", "role": "player"})  # back: a new membership
    assert len(list(db.scalars(select(CampaignMember).join(User).where(User.email == "nia@example.com")))) == 2


def test_removed_person_is_locked_out_even_if_on_railway_list(env, monkeypatch, db):
    import_bundle(db, MAIN)
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    player, _ = sign_in(monkeypatch, "player@example.com")
    assert player.get("/party").status_code == 200
    owner.post("/manage/accounts/update", data={"email": "player@example.com", "remove": "1"})
    assert player.get("/party", follow_redirects=False).headers["location"] == "/login"
    _, r = sign_in(monkeypatch, "player@example.com")
    assert "not_allowed" in r.headers["location"]
    assert "Removed or not invited yet (1)" in owner.get("/manage/accounts").text  # folded at the bottom


def test_owner_cant_be_demoted_and_admins_cant_lower_themselves(env, monkeypatch, db):
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    owner.post("/manage/accounts/update", data={"email": "owner@example.com", "remove": "1"})
    assert access.level("owner@example.com") == "admin"
    owner.post("/manage/accounts", data={"email": "boss@example.com", "admin": "1"})
    boss, _ = sign_in(monkeypatch, "boss@example.com")
    boss.post("/manage/accounts/update", data={"email": "boss@example.com"})  # no Admin box on your own row
    assert access.level("boss@example.com") == "admin"


def test_imported_members_need_an_invite(env, monkeypatch, db):
    import_bundle(db, {**MAIN, "members": [{"email": "mary@example.com", "name": "Mary", "role": "dm"}]})
    _, r = sign_in(monkeypatch, "mary@example.com")
    assert "not_allowed" in r.headers["location"]
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    page = owner.get("/manage/accounts").text
    assert "Mary" in page and "not invited yet" in page and "player@example.com" in page


def test_dm_never_sees_character_notes_even_as_admin(env, monkeypatch, db):
    from app.models import Character, NoteSnapshot, NoteSource

    import_bundle(db, {**MAIN, "entities": [{"kind": "pc", "name": "Cole", "character": {"player_name": "Brett"}}]})
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    add(owner, "dm@example.com", "dm", admin=True)
    dm, _ = sign_in(monkeypatch, "dm@example.com")
    assert dm.get("/manage/usage").status_code == 200
    assert "/manage/accounts" in dm.get("/").text
    # The campaign doc is for the whole table; an old character doc stays hidden from the DM
    campaign = db.scalar(select(Campaign))
    char = db.scalar(select(Character))
    src = NoteSource(campaign_id=campaign.id, google_doc_id="c" * 30, title="Secret Cole doc", character_id=char.id)
    src.snapshots.append(NoteSnapshot(content_hash="h", text="secret plan"))
    db.add(src)
    db.flush()
    assert "Secret Cole doc" not in dm.get("/manage/sessions/doc").text and "Secret Cole doc" in owner.get("/manage/sessions/doc").text
    assert "secret plan" not in dm.get(f"/manage/sessions/doc/snapshots/{src.snapshots[0].id}", follow_redirects=False).text
    assert dm.get("/manage/sessions/doc").status_code == 200 and owner.get("/manage/sessions/doc").status_code == 200
    assert dm.get(f"/characters/{char.id}/plan", follow_redirects=False).status_code == 303  # Plan is the players'


def test_a_dm_who_stops_dming_reads_the_notes_like_any_player(env, monkeypatch, db):
    """Decision 3: only characters in campaigns they DM now."""
    from app.models import Character

    import_bundle(db, {**MAIN, "entities": [{"kind": "pc", "name": "Cole", "character": {"player_name": "Brett"}}]})
    char = db.scalar(select(Character))
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    add(owner, "dm@example.com", "dm")
    assert not auth.can_see_character_notes({"email": "dm@example.com"}, char)
    owner.post("/manage/table/people", data={"email": "dm@example.com", "role": "player"})
    assert auth.can_see_character_notes({"email": "dm@example.com"}, char)


def test_players_cant_manage_people(env, monkeypatch, db):
    player, _ = sign_in(monkeypatch, "player@example.com")
    assert player.get("/manage/accounts").status_code == 403 and player.get("/manage/table").status_code == 403
    assert player.post("/manage/accounts", data={"email": "x@example.com", "admin": "1"}).status_code == 403
    assert player.post("/manage/table/people/add", data={"new_email": "x@example.com"}).status_code == 403
    assert db.scalar(select(User).where(User.email == "x@example.com")) is None


def test_sign_in_records_name_and_time(env, monkeypatch, db):
    sign_in(monkeypatch, "player@example.com")
    u = db.scalar(select(User).where(User.email == "player@example.com"))
    assert u.name == "Player" and u.last_seen_at is not None and u.access is None


def test_invite_from_the_list(env, monkeypatch, db):
    import_bundle(db, {**MAIN, "members": [{"email": "mary@example.com", "name": "Mary", "role": "dm"}]})
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    assert ">Invite</button>" in owner.get("/manage/accounts").text
    owner.post("/manage/accounts/update", data={"email": "mary@example.com"})
    assert access.level("mary@example.com") == "member" and access.is_dm("mary@example.com")


def test_who_plays_which_character_on_the_table(env, monkeypatch, db):
    from app.models import Character

    import_bundle(db, {**MAIN, "entities": [{"kind": "pc", "name": "Cole", "character": {"player_name": "Brett"}},
                                            {"kind": "pc", "name": "Trah", "character": {"player_name": "Mark"}}]})
    cole, trah = (db.scalar(select(Character).where(Character.name == n)) for n in ("Cole", "Trah"))
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    add(owner, "player@example.com", "player")
    player = db.scalar(select(User).where(User.email == "player@example.com"))
    assert f'<option value="{player.id}" >player@example.com</option>' in owner.get("/manage/table").text
    owner.post(f"/manage/table/characters/{cole.id}", data={"user_id": str(player.id)})
    assert cole.owner.email == "player@example.com"
    owner.post(f"/manage/table/characters/{trah.id}", data={"user_id": str(player.id)})  # one character each here
    assert trah.owner_id == player.id and cole.owner_id is None
    owner.post(f"/manage/table/characters/{trah.id}", data={"user_id": ""})
    assert trah.owner_id is None


def test_access_chart_is_drawn_from_the_rules_the_app_uses():
    rows = {r["what"]: r for r in access.chart()["rows"]}
    assert access.chart()["columns"] == ["Player", "Reviewer", "DM", "Admin"]
    assert rows["Decide on the table's suggestions"]["cells"] == ["no", "yes", "yes", "yes"]  # the DM includes Reviewer
    assert rows["Players' notes, pins, reminders and shortlists"]["cells"] == ["yes", "yes", "no", "yes"]
    assert rows["Table: roles, who plays which character, adding characters and D&D Beyond links"]["cells"] == ["no", "no", "no", "yes"]
    assert rows["See the Table: who plays which character, D&D Beyond links"]["cells"] == ["no", "no", "yes", "yes"]
    assert rows["Settings: the campaign's name and the DM's name"]["cells"] == ["no", "no", "yes", "yes"]
    assert rows["Notes, pins, reminders, shortlists, the Wild Shape switch and table rolls"]["cells"] == ["own"] * 4
    for r in access.CHART:  # every rule in the chart is one the app checks
        if r[2] != "own":
            access.allows(r[2], access.MEMBER, access.PLAYER)
    assert not access.allows("player_notes", access.ADMIN, access.DM)  # an admin who DMs still never sees the notes
    assert "never sees" in access.summary(access.ADMIN, access.DM)


def test_table_lists_people_by_role_and_folds_the_chart(env, monkeypatch, db):
    import_bundle(db, MAIN)
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    add(owner, "pat@example.com", "player", "Pat")
    add(owner, "rev@example.com", "reviewer", "Rev")
    add(owner, "dm@example.com", "dm", "Dee")
    page = owner.get("/manage/table").text
    assert "What each role can do" in page and "Not included for anyone" in page
    assert page.index("<b>Dee</b>") < page.index("<b>Rev</b>") < page.index("<b>Pat</b>")  # DM, reviewers, players
    assert "Runs this campaign" in page  # the DM's row explains the role
    accounts = owner.get("/manage/accounts").text
    assert "Main</a> (DM)" in accounts and "Main</a> (player)" in accounts  # Accounts shows each person's campaigns


def test_the_dm_sees_the_table_and_edits_settings_but_changes_no_roles(env, monkeypatch, db):
    import_bundle(db, MAIN)
    owner, _ = sign_in(monkeypatch, "owner@example.com")
    add(owner, "dm@example.com", "dm", "Dee")
    add(owner, "pat@example.com", "player", "Pat")
    dm, _ = sign_in(monkeypatch, "dm@example.com")
    page = dm.get("/manage/table").text
    assert "<b>Pat</b>" in page and 'name="role"' not in page and "+ Add a character" not in page  # sees, can't change
    assert dm.post("/manage/table/people", data={"email": "pat@example.com", "role": "dm"}).status_code == 403
    assert dm.get("/manage/accounts").status_code == 403
    dm.post("/manage/settings", data={"name": "The Lost Mine", "dm_name": "Dee", "ddb_campaign_id": "42"})
    main = db.scalar(select(Campaign))
    assert (main.name, main.dm_name, main.ddb_campaign_id, main.slug) == ("The Lost Mine", "Dee", "42", "main")
    pat, _ = sign_in(monkeypatch, "pat@example.com")
    assert pat.get("/manage/settings").status_code == 403 and pat.get("/manage/table").status_code == 403


def test_migration_moves_the_dm_tick_and_reviewer_into_campaign_roles(db_engine):
    """The step 2 migration on people shaped like production's, then back down and up again."""
    import os
    import subprocess

    from sqlalchemy import text

    from app.db import Base

    env = {"DATABASE_URL": db_engine.url.render_as_string(hide_password=False), "PATH": os.environ["PATH"]}

    def alembic(*args):
        r = subprocess.run(["alembic", *args], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    Base.metadata.drop_all(db_engine)
    try:
        alembic("upgrade", "9a5b7c1d4e60")
        with db_engine.begin() as c:
            c.execute(text("INSERT INTO campaigns (id, name, slug, dm_name) VALUES (1, 'Main', 'main', 'Mary')"))
            c.execute(text("""INSERT INTO users (id, email, name, access, is_dm) VALUES
                (1, 'brett@example.com', 'Brett', 'admin', false), (2, 'jay@example.com', 'Jay', 'player', false),
                (3, 'mary@example.com', 'Mary', 'reviewer', true), (4, 'old@example.com', 'Old', 'removed', false),
                (5, 'new@example.com', 'New', NULL, false)"""))
            c.execute(text("INSERT INTO campaign_members (campaign_id, user_id, role) VALUES (1, 1, 'player')"))
            c.execute(text("""INSERT INTO revisions ("table", row_id, label, field, old, new, actor, source)
                              VALUES ('users', 2, 'Jay', 'access', '"reviewer"', '"player"', 'brett@example.com', 'edit')"""))
        alembic("upgrade", "head")
        with db_engine.connect() as c:
            assert c.execute(text("SELECT user_id, role, left_on FROM campaign_members ORDER BY user_id")).all() == [
                (1, "player", None), (2, "player", None), (3, "dm", None)]  # removed and never-invited people get no role
            assert c.execute(text("SELECT id, access FROM users ORDER BY id")).all() == [
                (1, "admin"), (2, "member"), (3, "member"), (4, "removed"), (5, None)]
            assert c.execute(text("SELECT old, new FROM revisions")).one() == ("member", "member")
        alembic("downgrade", "9a5b7c1d4e60")
        with db_engine.connect() as c:
            assert c.execute(text("SELECT id, access, is_dm FROM users ORDER BY id")).all() == [
                (1, "admin", False), (2, "player", False), (3, "reviewer", True), (4, "removed", False), (5, None, False)]
        alembic("upgrade", "head")
    finally:
        subprocess.run(["alembic", "downgrade", "base"], env=env, capture_output=True)
        Base.metadata.create_all(db_engine)
