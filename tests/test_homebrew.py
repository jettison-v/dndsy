"""DM Tools and homebrew items (Brett chose 1B, 2A, 3A, Nov 13; docs/mockups/homebrew-items/; app/homebrew.py)."""

import pytest
from sqlalchemy import select

from app import access
from app import character_views as views
from app import characters, homebrew, house_rules, rules_book
from app.models import CampaignContent
from tests.menu import items
from tests.roles import set_role
from tests.table_setup import char


@pytest.fixture(autouse=True)
def roles(db, sheet):
    """dm@ is the campaign's DM, player@ plays Cole (the `sheet` fixture)."""
    set_role(db, "dm@example.com", "dm")
    set_role(db, "player@example.com", "player")
    db.flush()
    access.invalidate()
    homebrew.invalidate()

FORM = {"name": "Leviathan Compass", "category": "Wondrous Item", "rarity": "Rare", "attunement": "1", "cost": "—", "weight": "1 lb",
        "text": "Its needle points to the Leviathan's heart.",
        "roll0_name": "Pulse", "roll0_dice": "2d6 force", "roll0_resolve": "save", "roll0_effect": "damage", "roll0_save": "Dex",
        "roll0_dc": "14", "roll0_half": "1",
        "add0_name": "Guiding needle", "add0_amount": "+1", "add0_when": "before", "add0_to": "check", "add0_says": "finding the Leviathan",
        "charges": "3", "charges_back": "dawn", "charges_regain": "1d3"}


def _carry(db, data, name="Leviathan Compass"):
    cole = char(db, "Cole")
    data.setdefault("customItems", []).append({"id": 9901, "name": name, "description": "<p>A homebrew compass.</p>", "quantity": 1})
    characters.refresh(db, cole)
    return cole


def test_dm_tools_is_the_dms_and_admins(dm, admin, player, db, sheet):
    """Whoever sets the campaign's house rules (its DM, admins): the door in the menu bar and the page. Players never see
    the campaign's homebrew items (3A: only once the DM gives one)."""
    assert dm.get("/c/main/dm").status_code == 200 and "dm-tools" in items(dm.get("/c/main/campaign").text, "manage")
    assert admin.get("/c/main/dm").status_code == 200
    assert player.get("/c/main/dm").status_code == 403
    assert 'href="/c/main/dm"' not in player.get("/c/main/campaign").text
    assert player.post("/c/main/dm/items", data=FORM).status_code == 403
    assert db.scalar(select(CampaignContent)) is None


def test_a_homebrew_item_plays_for_whoever_carries_it(dm, db, sheet):
    """Made in DM Tools, it plays through the same code as a book's item: a character with a custom item of that name
    has it on Battle with its roll (the save and DC set here), and its bonus is on the roll card. Retired, it stops."""
    cole = _carry(db, sheet)
    r = dm.post("/c/main/dm/items", data=FORM, follow_redirects=False)
    assert r.status_code == 303
    row = db.scalar(select(CampaignContent))
    assert row.name == "Leviathan Compass" and row.source == "Homebrew" and row.data["play"]["charges"] == {"count": 3, "back": "dawn", "regain": "1d3"}
    page = dm.get("/c/main/dm").text
    assert "Leviathan Compass" in page and "Pulse: Dex save DC 14: 2d6 force" in page and "Cole has it" in page
    homebrew.invalidate()
    raw = characters.character_summary(cole)
    s = views.apply_overrides(raw, house_rules.sheet_overrides(db, cole.campaign_id))
    o = next(o for o in views.options(s) if o["name"] == "Leviathan Compass")
    ev = o["recipe"]["events"][0]
    assert (ev["on"], ev["save"], ev["dc"], ev["success"], ev["parts"]) == ("save", "Dex", 14, "half", ["2d6 force"])
    assert any(a["name"] == "Guiding needle" and a["amount"] == "1" for a in rules_book.adds(s))
    # retired: its rolls and bonuses are off; Bring back puts them back
    dm.post(f"/c/main/dm/items/{row.key}/retire")
    homebrew.invalidate()
    s = views.apply_overrides(raw, house_rules.sheet_overrides(db, cole.campaign_id))
    assert not any(a["name"] == "Guiding needle" for a in rules_book.adds(s)) and "Retired" in dm.get("/c/main/dm").text


def test_the_form_says_what_is_wrong_and_keeps_what_was_typed(dm, db, sheet):
    bad = {**FORM, "name": "", "roll0_dice": "lots", "roll0_dc": "", "charges": "99"}
    r = dm.post("/c/main/dm/items", data=bad)
    assert r.status_code == 422 and "Give it a name." in r.text and "write its dice" in r.text and "Charges: a number" in r.text
    assert "Its needle points" in r.text and db.scalar(select(CampaignContent)) is None
    save = {**FORM, "roll0_dice": "2d6 force", "roll0_dc": ""}
    assert "needs its ability and DC" in dm.post("/c/main/dm/items", data=save).text
    dm.post("/c/main/dm/items", data=FORM)
    assert "already a homebrew item called" in dm.post("/c/main/dm/items", data=FORM).text  # (a second, not a change)


def test_a_custom_item_on_a_sheet_is_offered_as_a_start(dm, db, sheet):
    """The Beasty Bone, made up on D&D Beyond: listed under the table's custom items, with Make it homebrew, until it is one."""
    _carry(db, sheet, "Beasty Bone")
    page = dm.get("/c/main/dm").text
    assert "Beasty Bone" in page and "/c/main/dm/items/new?name=Beasty%20Bone" in page
    assert 'value="Beasty Bone"' in dm.get("/c/main/dm/items/new?name=Beasty%20Bone").text
    dm.post("/c/main/dm/items", data={**FORM, "name": "Beasty Bone"})
    assert "new?name=Beasty%20Bone" not in dm.get("/c/main/dm").text
    key = db.scalar(select(CampaignContent)).key
    edit = dm.get(f"/c/main/dm/items/{key}").text
    assert 'value="Beasty Bone"' in edit and "Retire" in edit
    renamed = {**FORM, "name": "Beasty Bone of the Deep", "key": key}
    dm.post("/c/main/dm/items", data=renamed)
    assert [r.name for r in db.scalars(select(CampaignContent))] == ["Beasty Bone of the Deep"]
