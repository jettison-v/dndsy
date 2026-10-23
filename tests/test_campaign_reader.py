"""The Campaign page (roadmap step 11, option E): quests on top, then the Reader (names down the left, one entry
on the page, ?open=<id> its address), with the last session marked."""

from sqlalchemy import select

from app.importer import import_bundle
from app.models import Entity, Fact
from tests.roles import set_role
from tests.test_entities import BUNDLE, HX, admin, lillippi, player, published_events  # noqa: F401
from tests.test_suggestions import client_for

QUESTS = {"campaign": {"slug": "main", "name": "Main"}, "entities": [
    {"kind": "quest", "name": "Reach the library", "summary": "Climb the tower.", "quest_open": True},
    {"kind": "quest", "name": "Clear the road", "quest_open": False},
]}


def entry(db, name):
    return db.scalar(select(Entity).where(Entity.name == name))


def test_quests_on_top_and_the_rest_in_the_reader(player, db):  # noqa: F811
    import_bundle(db, BUNDLE)
    import_bundle(db, QUESTS)
    published_events(db)
    page = player.get("/campaign").text
    quests, reader = page.index('class="section quests"'), page.index('class="reader"')
    assert quests < page.index("Reach the library") < page.index("Done (1)") < page.index("Clear the road") < reader
    assert '<span class="count">1 open</span>' in page
    names = page[reader:page.index('id="reader-article"')]
    assert "Lillippi Lemon" in names and "Saltmarsh" in names and "Reach the library" not in names  # quests stay on top
    # Lillippi is in the last session's key moments: marked, and in the Last session view; Saltmarsh isn't
    assert f'data-rd-id="{lillippi(db).id}" data-views="recent all"' in names
    assert f'data-rd-id="{entry(db, "Saltmarsh").id}" data-views="all"' in names
    # Nothing asked for: the Reader opens on something from the last session, with its key moments as a timeline
    assert f'data-reader-id="{lillippi(db).id}"' in page and 'class="moment-line"' in page and "Last seen Session 2" in page


def test_an_entry_has_its_own_address_and_swaps_in(player, db):  # noqa: F811
    import_bundle(db, BUNDLE)
    salt = entry(db, "Saltmarsh")
    page = player.get(f"/campaign?open={salt.id}").text
    assert f'data-reader-id="{salt.id}"' in page and f'class="rd-item sel" data-ls-row data-rd-id="{salt.id}"' in page
    part = player.get(f"/campaign/{salt.id}/read").text
    assert '<article class="reader-article" id="reader-article"' in part
    assert "Fishing town." in part and "peek-close" not in part
    # Adding what the party learned from the Reader answers with the Reader
    r = player.post(f"/campaign/{salt.id}/facts?in=reader", data={"text": "Smells of fish."}, headers=HX)
    assert '<article class="reader-article"' in r.text and "Smells of fish." in r.text
    assert db.scalar(select(Fact).where(Fact.entity_id == salt.id)).status == "pending"
    # The side panel elsewhere offers the Reader
    assert f'href="/c/main/campaign?open={salt.id}">Open in Campaign' in player.get(f"/campaign/{salt.id}/peek").text


def test_hidden_entries_and_quest_status_are_for_the_dm(monkeypatch, db):
    import_bundle(db, BUNDLE)
    import_bundle(db, QUESTS)
    set_role(db, "dm@example.com")
    dm, player = client_for(monkeypatch, db, "dm@example.com"), client_for(monkeypatch, db, "mark@example.com")
    dm.post("/campaign/new", data={"kind": "npc", "name": "The Grey Widow", "hidden": "1"}, headers=HX)
    widow, quest = entry(db, "The Grey Widow"), entry(db, "Reach the library")
    assert "The Grey Widow" in dm.get("/campaign").text and "The Grey Widow" not in player.get("/campaign").text
    assert player.get(f"/campaign/{widow.id}/read").status_code == 404
    assert "+ New quest" in dm.get("/campaign").text and "+ New quest" not in player.get("/campaign").text
    assert "Mark done" in dm.get(f"/campaign?open={quest.id}").text and "Mark done" not in player.get(f"/campaign?open={quest.id}").text
    assert player.post(f"/campaign/{quest.id}/quest", data={"open": "0"}).status_code == 403
    r = dm.post(f"/campaign/{quest.id}/quest", data={"open": "0"}, follow_redirects=False)
    db.refresh(quest)
    assert quest.quest_open is False and r.headers["location"] == f"/c/main/campaign?open={quest.id}"
    assert "Reopen" in dm.get(f"/campaign?open={quest.id}").text
    dm.post(f"/campaign/{widow.id}/quest", data={"open": "0"})  # not a quest: nothing changes
    db.refresh(widow)
    assert widow.quest_open is None
