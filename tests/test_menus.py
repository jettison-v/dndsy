"""The Three Menus (Brett approved all six parts, Nov 13, docs/mockups/menus/): three doors (your picture, Manage, the
gear), one shape, Help in your picture's menu and the ? gone, and the phone's More as the three doors stacked. Read by
what things are (tests/menu.py), not their words."""

import pytest
from sqlalchemy import select

from app.importer import import_bundle
from app.models import Campaign, Character
from tests.menu import door, has_door, items, topbar
from tests.table_setup import BUNDLE

pytestmark = pytest.mark.usefixtures("no_network")


def test_a_players_menu_is_short_and_help_is_in_it(player, db):
    import_bundle(db, BUNDLE)
    page = player.get("/c/main/campaign").text
    assert not has_door(page, "help") and "help-btn" not in topbar(page)  # (the ? left the bar)
    menu = items(page, "account")
    assert menu[0] == "me" and menu[-1] == "signout"
    assert {"notes", "tour", "help"} <= set(menu)
    assert not {"dice", "email", "guide"} & set(menu)  # (dice live in Table rolls' Roll; email and the guide are the DM's)


def test_the_dms_menu_adds_the_digest_and_the_dm_guide(dm, db):
    import_bundle(db, BUNDLE)
    page = dm.get("/c/main/campaign").text
    menu = items(page, "account")
    assert menu.index("notes") < menu.index("email") < menu.index("tour") < menu.index("guide") < menu.index("signout")
    assert 'href="/c/main/manage/dm-guide"' in door(page, "account")
    assert 'class="menu-state"' in door(page, "account")  # (On or Off beside the digest)


def test_more_on_a_phone_is_the_three_doors_stacked(admin, db):
    import_bundle(db, BUNDLE)
    more = items(admin.get("/c/main/campaign").text, "more")
    assert more.index("notes") < more.index("tour") < more.index("manage") < more.index("admin") < more.index("signout")
    assert "dice" not in more and "dm-tools" not in more  # (DM Tools is inside Manage)


def test_campaigns_starts_one_in_a_window_and_moves_only_what_ddb_moved(admin, db):
    """Part 5: + New campaign opens a small window; a character is offered a move only when its sheet is in another
    campaign's D&D Beyond game than its askdnd one, as one line with one button."""
    import_bundle(db, BUNDLE)
    other = Campaign(name="Second Wind", slug="second", ddb_campaign_id="777")
    db.add(other)
    main = db.scalar(select(Campaign).where(Campaign.slug == "main"))
    main.ddb_campaign_id = "111"
    cole = db.scalar(select(Character).where(Character.name == "Cole"))
    cole.ddb_campaign_id = "777"
    db.commit()
    page = admin.get("/manage/campaigns").text
    assert 'data-modal-url="/manage/campaigns/new"' in page and 'action="/manage/campaigns"' not in page.split('data-item="new-campaign"')[0]
    window = admin.get("/manage/campaigns/new").text
    assert 'action="/manage/campaigns"' in window and 'name="is_test"' in window
    moves = page.split("data-move=")[1:]
    assert len(moves) == 1 and moves[0].startswith(f'"{cole.id}"') and f'value="{other.id}"' in moves[0]
    assert "<select" not in page  # (no free moves)
    admin.post(f"/manage/campaigns/characters/{cole.id}/move", data={"campaign_id": str(other.id)})
    assert "data-move=" not in admin.get("/manage/campaigns").text


def test_no_one_else_opens_the_new_campaign_window(player, db):
    import_bundle(db, BUNDLE)
    assert player.get("/manage/campaigns/new").status_code == 403
