"""The DM's Workspace (Brett chose B, Nov 13, docs/mockups/dm-workspace/): Manage's list grouped by the DM's week with
DM Tools' kinds under The next game, a workbench home, and who may open each page given as a rule's name
(app/access.py), so narrowing what an admin sees is one line there."""

import pytest
from sqlalchemy import select

from app import access, manage
from app.importer import import_bundle
from app.models import Campaign, Place, ScenePin
from tests.menu import items
from tests.roles import set_role
from tests.table_setup import BUNDLE

pytestmark = pytest.mark.usefixtures("no_network")


def _setup(db) -> None:
    import_bundle(db, BUNDLE)
    set_role(db, "dm@example.com", "dm")  # (dm@ is the campaign's DM)
    db.commit()
    access.invalidate()


def _table_on(db) -> Campaign:
    c = db.scalar(select(Campaign).where(Campaign.slug == "main"))
    c.vtt_pieces = ["vtt", "labs"]  # (askdnd's table, in Labs)
    db.commit()
    access.invalidate()
    return c


def test_every_page_says_who_by_a_rule_access_knows():
    """A standing rule (Brett, Nov 13: "make sure the permission structure is robust and flexible"): every Manage page's
    who-may-open is a rule app/access.py answers, so the access chart, the menus and the pages can't disagree."""
    rules = set(access.allows.__code__.co_consts) | {"admin"}
    for key, *_, allowed, _extra in manage.PAGES:
        assert callable(allowed) or allowed in rules, key


def test_the_dm_sees_what_they_make_under_the_next_game(dm, db):
    _setup(db)
    _table_on(db)
    page = dm.get("/c/main/manage").text
    assert items(page, "manage")[:6] == ["needs", "inbox", "sessions", "dm-tools", "scene-notes", "places"]
    side = page.split('class="manage-side"')[1].split("</nav>")[0]
    assert 'data-item="planned:shops"' in side and 'href=""' not in side  # (planned kinds listed, never links)
    for tile in ("items", "scene-notes", "places", "shops"):
        assert f'data-tile="{tile}"' in page
    assert 'data-workbench="table"' in page and 'data-workbench="make"' in page


def test_without_askdnds_table_its_pages_stay_out_of_the_list(dm, db):
    _setup(db)
    page = dm.get("/c/main/manage").text
    assert "scene-notes" not in items(page, "manage") and "places" not in items(page, "manage")
    assert 'data-tile="scene-notes"' not in page and 'data-tile="items"' in page


def test_scene_notes_are_the_dms_alone(dm, admin, db):
    """A standing rule (Brett, Nov 6; app/scene_notes.py): the campaign's DM alone, not admins: they don't learn a scene
    exists."""
    _setup(db)
    c = _table_on(db)
    place = Place(campaign_id=c.id, name="The Observatory")
    db.add(place)
    db.flush()
    db.add(ScenePin(campaign_id=c.id, place_id=place.id, name="The orrery room"))
    db.commit()
    page = dm.get("/c/main/manage/scene-notes")
    assert page.status_code == 200 and "The orrery room" in page.text and f'href="/c/main/table?place={place.id}"' in page.text
    assert admin.get("/c/main/manage/scene-notes").status_code == 404
    assert "scene-notes" not in items(admin.get("/c/main/manage").text, "manage")
    assert "The orrery room" not in admin.get("/c/main/manage/places").text


def test_places_list_the_tables_places_and_open_it_there(admin, player, db):
    _setup(db)
    c = _table_on(db)
    db.add(Place(campaign_id=c.id, name="The Sunken Stair"))
    db.commit()
    page = admin.get("/c/main/manage/places").text
    assert "The Sunken Stair" in page and "/c/main/table?place=" in page
    assert player.get("/c/main/manage/places").status_code == 403


def test_dm_tools_pages_carry_the_manage_list(dm, db):
    _setup(db)
    page = dm.get("/c/main/dm").text
    side = page.split('class="manage-side"')[1].split("</nav>")[0]
    assert 'aria-current="page">Items' in side and 'data-item="needs"' in side
