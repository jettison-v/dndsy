"""The VTT switch and test campaigns (VTT Phase 0, item 0.1; docs/mockups/vtt-switch.html): a test campaign sees every
VTT piece; another campaign only the Ready pieces switched on in its Settings; test copies of characters keep the real
ones untouched."""

from sqlalchemy import select

from app import access, characters, vtt
from app.models import Campaign, Character, CharacterSnapshot, User
from tests.roles import set_role
from tests.test_campaigns import sign_in, two  # noqa: F401
from tests.test_characters import char, no_network  # noqa: F401

HP = vtt.Piece("hp", "Hit points askdnd tracks", "1.1", "Damage by type, resistances, temporary HP", ready=True)
SLOTS = vtt.Piece("slots", "Casting spends spell slots", "1.2", "Upcasting and concentration")


def test_which_pieces_a_campaign_shows(monkeypatch):
    monkeypatch.setattr(vtt, "PIECES", [HP, SLOTS])
    table, test = Campaign(name="Main", vtt_pieces=[]), Campaign(name="VTT test", is_test=True, vtt_pieces=[])
    assert vtt.on(test, "hp") and vtt.on(test, "slots")  # a test campaign sees every piece, finished or not
    assert not vtt.on(table, "hp") and not vtt.on(table, "nothing") and not vtt.on(None, "hp")
    assert vtt.switch(table, "hp", True) == "Hit points askdnd tracks is on for Main." and vtt.on(table, "hp")
    assert vtt.on({"is_test": False, "vtt_pieces": ["hp"]}, "hp")  # the menu bar's `here`
    assert vtt.switch(table, "slots", True) == "Casting spends spell slots is still being built." and not vtt.on(table, "slots")
    assert vtt.switch(table, "hp", False) == "Hit points askdnd tracks is off for Main." and not vtt.on(table, "hp")
    assert "already has every piece" in vtt.switch(test, "hp", False)


def test_the_switch_on_settings(two, db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(vtt, "PIECES", [HP, SLOTS])
    admin, main = two["admin"], two["main"]
    page = admin.get("/c/main/manage/settings").text
    assert '<section class="section" id="vtt">' in page and "Hit points askdnd tracks" in page
    assert 'aria-checked="false" aria-label="Test campaign"' in page
    # The table's DM switches a Ready piece on for their table, but can't make it a test campaign
    set_role(db, "dee@example.com", "dm", "Dee", main).access = "member"
    db.flush()
    access.invalidate()
    dm = sign_in(monkeypatch, "dee@example.com")
    dm.post("/c/main/manage/settings/vtt/hp", data={"on": "1"})
    db.refresh(main)
    assert main.vtt_pieces == ["hp"]
    dm.post("/c/main/manage/settings/vtt/slots", data={"on": "1"})  # still being built
    assert dm.post("/c/main/manage/settings/test", data={"is_test": "1"}).status_code == 403
    db.refresh(main)
    assert main.vtt_pieces == ["hp"] and not main.is_test
    # An admin makes a campaign a test one: tagged in the menu bar and on Campaigns
    admin.post("/c/strahd/manage/settings/test", data={"is_test": "1"})
    db.refresh(two["strahd"])
    assert two["strahd"].is_test
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
