"""A test copy of your character (app/twins.py, temporary): each player's own steps and links, ticked by what VTT test
lists on D&D Beyond. Delete with the page once the twins are claimed."""

import pytest
from sqlalchemy import select

from app import characters, config
from app.importer import import_bundle
from app.models import Campaign, Character
from tests.table_setup import BUNDLE, COLE, char, owned_by

pytestmark = pytest.mark.usefixtures("no_network")
INVITE = "https://www.dndbeyond.com/campaigns/join/1234567890"


@pytest.fixture
def tables(db, monkeypatch):
    """Main (Cole, player@'s, on D&D Beyond as PatPlayer) and VTT test (Cathartic, whose sheet lists the campaign)."""
    monkeypatch.setattr(config, "VTT_TEST_INVITE_URL", INVITE)
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    characters.refresh(db, cole, fetch=lambda i: {**COLE, "userId": 501, "username": "PatPlayer"})
    import_bundle(db, {"campaign": {"slug": "vtt-test", "name": "VTT test"},
                       "entities": [{"kind": "pc", "name": "Cathartic", "character": {"ddb_id": "172986165"}}]})
    test = db.scalar(select(Campaign).where(Campaign.slug == "vtt-test"))
    test.is_test, test.ddb_campaign_id = True, "8224496"

    def listing(*entries):
        cathartic = db.scalar(select(Character).where(Character.name == "Cathartic"))
        mine = {"characterId": 172986165, "characterName": "Cathartic", "userId": 900, "username": "CatharticPlayer", "isAssigned": True}
        characters.refresh(db, cathartic, fetch=lambda i: {**COLE, "name": "Cathartic", "campaign": {"id": 8224496, "characters": [mine, *entries]}})
        db.flush()

    listing()
    return listing


def done(page: str) -> int:
    return page.count('class="tw-step done"')


def test_a_player_gets_their_own_steps_and_links_and_never_anothers(player, tables):
    page = player.get("/twin").text
    assert "A test copy of Cole" in page and "Hi, PatPlayer" in page
    assert config.BRIDGE_EXTENSION_URL in page and "https://www.dndbeyond.com/characters\"" in page
    assert "https://www.dndbeyond.com/characters/75423618" in page  # their own sheet
    assert INVITE in page and "https://www.dndbeyond.com/campaigns/8224496" in page
    assert "Cole Lockhard" in page and "Cole (twin)" in page
    main = page.split('<main class="page twin-page">')[1].split("</main>")[0]
    assert "Trah" not in main and "135831636" not in page  # another player's character (Party's menu names everyone)
    assert "Everyone's copy" not in page and "data-tour-start" in page  # (the optional last step: the tour)
    assert done(page) == 0


def test_each_step_ticks_itself_from_what_vtt_test_lists(player, tables):
    tables({"characterId": 999, "characterName": "Cole Lockhard", "userId": 501, "username": "PatPlayer", "isAssigned": True})
    page = player.get("/twin").text
    assert done(page) == 2 and "askdnd sees it in VTT test as Cole Lockhard" in page  # copied and joined

    tables({"characterId": 999, "characterName": "Cole Lockhard", "userId": 501, "username": "PatPlayer", "isAssigned": False})
    assert done(player.get("/twin").text) == 3  # unassigned

    tables({"characterId": 999, "characterName": "Cole (twin)", "userId": 900, "username": "CatharticPlayer", "isAssigned": True})
    page = player.get("/twin").text
    assert done(page) == 4 and "done, thank you" in page  # claimed by a test account

    tables({"characterId": 75423618, "characterName": "Cole Lockhard", "userId": 501, "username": "PatPlayer", "isAssigned": True})
    assert done(player.get("/twin").text) == 0  # the real Cole in VTT test is no copy


def test_an_admin_sees_where_everyones_copy_stands(admin, tables):
    tables({"characterId": 999, "characterName": "Cole (twin)", "userId": 900, "username": "CatharticPlayer", "isAssigned": True})
    page = admin.get("/twin").text
    assert "Everyone's copy" in page and "CatharticPlayer as Cole (twin)" in page


def test_without_the_invite_the_page_says_to_ask_and_signed_out_it_asks_to_sign_in(player, tables, monkeypatch, db):
    monkeypatch.setattr(config, "VTT_TEST_INVITE_URL", "")
    assert "Ask Brett for VTT test's invite link" in player.get("/twin").text
    from fastapi.testclient import TestClient

    from app.main import app

    assert TestClient(app).get("/twin", follow_redirects=False).headers["location"] == "/login"
