"""The Campaign page (roadmap step 11; Brett 2026-10-22): World is the Reader (names down the left, one entry on
the page, ?open=<id> its address, the last session marked), Quests is the board, Relationships has the family trees
and anyone's connections."""

from sqlalchemy import select

from app import relations
from app.extraction import store_result
from app.importer import import_bundle
from app.models import Entity, ExtractionRun, Fact, GameSession
from app.review import publish
from tests.roles import set_role
from tests.test_entities import BUNDLE, HX, admin, lillippi, player, published_events  # noqa: F401
from tests.test_suggestions import client_for

QUESTS = {"campaign": {"slug": "main", "name": "Main"}, "entities": [
    {"kind": "quest", "name": "Reach the library", "summary": "Climb the tower.", "quest_open": True},
    {"kind": "quest", "name": "Clear the road", "quest_open": False},
]}


def entry(db, name):
    return db.scalar(select(Entity).where(Entity.name == name))


def quest_moment(db, number, text):
    """A published key moment in session `number` that mentions the library quest and Lillippi."""
    s = db.scalar(select(GameSession).where(GameSession.number == number))
    run = ExtractionRun(session_id=s.id, source="notes", status="done")
    db.add(run)
    db.flush()
    store_result(db, s, run, {"title": "", "recap": "Recap.", "events": [{"kind": "event", "text": text, "entities": ["Lillippi", "Reach the library"]}],
                              "entities": [], "glossary": [], "to_check": [], "relationships": []})
    db.flush()
    db.refresh(s)
    publish(db, s)
    db.flush()


def test_world_is_the_reader_without_quests(player, db):  # noqa: F811
    import_bundle(db, BUNDLE)
    import_bundle(db, QUESTS)
    published_events(db)
    page = player.get("/c/main/campaign").text
    assert 'data-tab="t-world">World</button>' in page and 'data-tab="t-quests">Quests <span class="count">1</span>' in page
    # Filters (2026-10-23): a chip per kind, each name tagged with its kind; Hidden only for the DM and editors
    assert 'data-ls-group="kind" data-ls-value="People"' in page and 'data-ls-group="kind" data-ls-value="Places"' in page
    assert '"kind": "People"' in page and 'data-ls-value="Hidden"' not in page
    reader = page.index('class="reader"')
    names = page[reader:page.index('id="reader-article"')]
    assert "Lillippi Lemon" in names and "Saltmarsh" in names and "Reach the library" not in names  # quests have their own tab
    # Lillippi is in the last session's key moments: marked, and in the Last session view; Saltmarsh isn't
    assert f'data-rd-id="{lillippi(db).id}" data-views="recent all"' in names
    assert f'data-rd-id="{entry(db, "Saltmarsh").id}" data-views="all"' in names
    # Nothing asked for: the Reader opens on something from the last session, with its key moments as a timeline
    assert f'data-reader-id="{lillippi(db).id}"' in page and 'class="moment-line"' in page and "Last seen Session 2" in page


def test_the_quest_board(player, db):  # noqa: F811
    import_bundle(db, BUNDLE)
    import_bundle(db, QUESTS)
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": n, "played_on": f"2026-02-0{n}"} for n in range(3, 8)]})
    quest, lil = entry(db, "Reach the library"), lillippi(db)
    relations.add(db, lil, "gave", quest)
    for n, text in ((1, "Lillippi asked for help."), (2, "The party found the tower."), (3, "The door was locked."), (4, "A key turned up.")):
        quest_moment(db, n, text)
    page = player.get("/c/main/campaign?tab=quests").text
    board = page[page.index('id="t-quests"'):page.index('id="t-relationships"')]
    assert '<div id="t-world" hidden>' in page and 'id="t-quests" class="quest-log">' in page  # ?tab= picks the tab
    card = board[board.index(f'id="quest-{quest.id}"'):]
    assert f'Given by <a class="ent" href="/c/main/campaign?open={lil.id}">Lillippi Lemon</a>' in card and "since Session 1" in card
    # Progress, newest first: every key moment, the latest marked as where the quest stands now
    assert "Climb the tower." in card and card.index("A key turned up.") < card.index("Lillippi asked for help.") and '<li class="now">' in card
    assert '<span class="note">Session 4 · 4 updates · from Lillippi Lemon</span>' in board  # the quest log's list
    assert f'<a class="chip-link" href="/c/main/campaign?open={lil.id}">Lillippi Lemon</a>' in card  # who and where
    assert "Clear the road" in board and 'data-ql-view="done" aria-pressed="false">Done <span class="ls-n">1</span>' in board  # done quests under Done
    # Sessions pass without it: after three, it says so (a fact, not advice)
    def quiet_session(n):
        s = db.scalar(select(GameSession).where(GameSession.number == n))
        run = ExtractionRun(session_id=s.id, source="notes", status="done")
        db.add(run)
        db.flush()
        store_result(db, s, run, {"title": "", "recap": "Recap.", "events": [], "entities": [], "glossary": [], "to_check": [], "relationships": []})
        db.flush()
        db.refresh(s)
        publish(db, s)
        db.flush()

    quiet_session(5)
    quiet_session(6)
    assert "No key moments since" not in player.get("/c/main/campaign?tab=quests").text
    quiet_session(7)
    page = player.get(f"/c/main/campaign?open={quest.id}").text
    assert "No key moments since Session 4" in page
    # The Reader says which quests an entry is part of, linking to the board
    assert f'href="/c/main/campaign?tab=quests&amp;open={quest.id}" data-goto-quest="{quest.id}"' in player.get(f"/c/main/campaign?open={lil.id}").text
    # A quest's address opens the Quests tab on its journal, picked in the quest log
    assert f'id="quest-{quest.id}" data-ql-journal="{quest.id}">' in page and '<div id="t-world" hidden>' in page
    assert f'class="ql-item open sel" data-ql-id="{quest.id}"' in page


def test_relationships_and_connections(player, db):  # noqa: F811
    import_bundle(db, BUNDLE)
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": [{"kind": "npc", "name": "Mo"}, {"kind": "faction", "name": "Harpers"}]})
    lil, mo, harpers = lillippi(db), entry(db, "Mo"), entry(db, "Harpers")
    relations.add(db, mo, "parent_of", lil)
    relations.add(db, lil, "member_of", harpers)
    page = player.get("/c/main/campaign?tab=relationships").text
    assert "Mo&#39;s family" in page and "Factions and their members" in page
    # Anyone's connections: the person in the middle, family above or below, factions to the side
    cx = player.get(f"/campaign/{lil.id}/connections").text
    assert 'class="cx-node cx-hub"' in cx and "Child of" in cx and "Member of" in cx
    assert f'hx-get="/c/main/campaign/{mo.id}/connections"' in cx  # a name moves it to the middle
    # The Reader draws them too, its names opening that entry
    reader = player.get(f"/c/main/campaign?open={lil.id}").text
    assert '<div class="cx-diagram"' in reader and 'class="cx-node npc"' in reader and f'href="/c/main/campaign?open={mo.id}" title="Child of Mo"' in reader


def test_an_entry_has_its_own_address_and_swaps_in(player, db):  # noqa: F811
    import_bundle(db, BUNDLE)
    salt = entry(db, "Saltmarsh")
    page = player.get(f"/c/main/campaign?open={salt.id}").text
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
    assert "The Grey Widow" in dm.get("/c/main/campaign").text and "The Grey Widow" not in player.get("/c/main/campaign").text
    assert player.get(f"/campaign/{widow.id}/read").status_code == 404
    assert "+ New quest" in dm.get("/c/main/campaign").text and "+ New quest" not in player.get("/c/main/campaign").text
    assert "Mark done" in dm.get(f"/c/main/campaign?open={quest.id}").text and "Mark done" not in player.get(f"/c/main/campaign?open={quest.id}").text
    assert player.post(f"/campaign/{quest.id}/quest", data={"open": "0"}).status_code == 403
    r = dm.post(f"/campaign/{quest.id}/quest", data={"open": "0"}, follow_redirects=False)
    db.refresh(quest)
    assert quest.quest_open is False and r.headers["location"] == f"/c/main/campaign?open={quest.id}"
    done = dm.get(f"/c/main/campaign?open={quest.id}").text  # now under Done, which the quest log shows
    assert f'class="ql-item done sel" data-ql-id="{quest.id}"' in done and 'data-ql-view="done" aria-pressed="true"' in done and "Reopen" in done
    dm.post(f"/campaign/{widow.id}/quest", data={"open": "0"})  # not a quest: nothing changes
    db.refresh(widow)
    assert widow.quest_open is None
