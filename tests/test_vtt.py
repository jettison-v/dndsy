"""Features and Labs (app/vtt.py; Brett, 2026-11-03) and test campaigns: finished features one switch each, Labs one
switch over the features still being tried; a test campaign holds test data and switches nothing on; test copies of
characters keep the real ones untouched."""

import pytest
from sqlalchemy import select

from app import access, characters, vtt
from app.models import Campaign, Character, CharacterSnapshot, User
from tests.roles import set_role
from tests.test_campaigns import sign_in, two  # noqa: F401
from tests.table_setup import char

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)

def test_features_and_labs():
    """Brett, 2026-11-03: finished features are one switch each; Labs is one switch that shows the features still being
    tried, each with its own toggle; a test campaign switches nothing on by itself."""
    table = Campaign(name="Main", vtt_pieces=[])
    test = Campaign(name="VTT test", is_test=True, vtt_pieces=[])
    assert not vtt.on(test, "ddb_bridge") and not vtt.on(test, "vtt_table")  # test data only
    assert vtt.switch(table, "sync", True) == "Sync with D&D Beyond is on for Main." and table.vtt_pieces == ["sync"]
    assert all(vtt.on(table, p) for p in ("ddb_bridge", "live_state", "dm_backup")) and not vtt.on(table, "vtt_table")
    vtt.switch(table, "vtt", True)  # a Labs feature's toggle, kept while Labs is off
    assert not vtt.on(table, "vtt_table")
    assert vtt.switch(table, "labs", True) == "Labs is on for Main." and vtt.on(table, "vtt_table")
    assert vtt.on({"is_test": False, "vtt_pieces": ["labs", "vtt"]}, "vtt_table")  # the menu bar's `here`
    assert "keep how you left them" in vtt.switch(table, "labs", False) and not vtt.on(table, "vtt_table")
    assert sorted(table.vtt_pieces) == ["sync", "vtt"]
    assert vtt.switch(table, "nothing", True) == "There's no such feature." and not vtt.on(None, "ddb_bridge")
    r = vtt.rows(table)
    assert [x["f"].key for x in r["features"]] == ["sync"] and [x["f"].key for x in r["labs"]] == ["vtt", "creatures", "initiative"] and not r["labs_on"]
    assert all(f.roadmap and f.about for f in vtt.FEATURES + vtt.PERSONAL)  # each says what it does and where it is


def test_the_switches_on_settings(two, db, monkeypatch):  # noqa: F811
    admin, main = two["admin"], two["main"]
    page = admin.get("/c/main/manage/settings").text
    assert '<section class="section" id="features">' in page and "Sync with D&amp;D Beyond" in page
    assert 'aria-label="Labs on here"' in page and "askdnd&#39;s VTT" not in page  # Labs off: its features hidden
    assert 'aria-checked="false" aria-label="Test campaign"' in page
    # The table's DM switches things on for their table, but can't make it a test campaign
    set_role(db, "dee@example.com", "dm", "Dee", main).access = "member"
    db.flush()
    access.invalidate()
    dm = sign_in(monkeypatch, "dee@example.com")
    dm.post("/c/main/manage/settings/vtt/sync", data={"on": "1"})
    dm.post("/c/main/manage/settings/vtt/labs", data={"on": "1"})
    db.refresh(main)
    assert main.vtt_pieces == ["sync", "labs"]
    page = dm.get("/c/main/manage/settings").text
    assert "askdnd&#39;s VTT" in page and "Dice tray: less intrusive dice" in page and 'data-modal-url="/dice"' in page
    assert dm.post("/c/main/manage/settings/test", data={"is_test": "1"}).status_code == 403
    db.refresh(main)
    assert not main.is_test
    # An admin makes a campaign a test one: tagged in the menu bar and on Campaigns
    admin.post("/c/strahd/manage/settings/test", data={"is_test": "1"})
    db.refresh(two["strahd"])
    assert two["strahd"].is_test and two["strahd"].vtt_pieces == []
    assert 'Curse of Strahd <span class="tag draft campaign-test"' in admin.get("/c/strahd/").text
    assert 'Curse of Strahd <span class="tag draft" title="A test campaign' in admin.get("/manage/campaigns").text
    admin.post("/manage/campaigns", data={"name": "VTT test", "is_test": "1"})
    assert db.scalar(select(Campaign).where(Campaign.name == "VTT test")).is_test


def test_test_copies_leave_the_real_characters_alone(two, db):  # noqa: F811
    admin, main, strahd = two["admin"], two["main"], two["strahd"]
    cole = char(db, "Cole")
    cole.owner_id = db.scalar(select(User.id).where(User.email == "pat@example.com"))  # Pat plays Cole at the table
    characters.refresh(db, cole)
    # Only a test campaign offers test copies
    assert "+ Add test copies" not in admin.get("/c/strahd/manage/table").text
    admin.post("/c/strahd/manage/table/test-copies", data={"character_ids": [cole.id]})
    assert db.scalar(select(Character).where(Character.copy_of_id == cole.id)) is None
    strahd.is_test = True
    db.flush()
    access.invalidate()
    assert "+ Add test copies" in admin.get("/c/strahd/manage/table").text
    admin.post("/c/strahd/manage/table/test-copies", data={"character_ids": [cole.id]})
    copy = db.scalar(select(Character).where(Character.copy_of_id == cole.id))
    assert copy is not None and copy.campaign_id == strahd.id and copy.ddb_id == cole.ddb_id
    assert cole.owner_id and copy.owner_id is None  # its player isn't in the test campaign
    assert db.scalar(select(CharacterSnapshot).where(CharacterSnapshot.character_id == copy.id)).summary == cole.snapshot.summary
    db.refresh(cole)
    assert cole.campaign_id == main.id and cole.copy_of_id is None  # the real one stays in its campaign
    table = admin.get("/c/strahd/manage/table").text
    assert "Test copy</span>" in table and "copy of Cole in Main" in table and "Cole (already here)" in table
    assert "Test copy</span>" in admin.get(f"/characters/{copy.id}").text
    # Copying again does nothing
    admin.post("/c/strahd/manage/table/test-copies", data={"character_ids": [cole.id]})
    assert len(list(db.scalars(select(Character).where(Character.copy_of_id == cole.id)))) == 1
