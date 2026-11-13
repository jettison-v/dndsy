"""The Campaign page (roadmap step 11; Brett 2026-10-22): World is the Reader (names down the left, one entry on
the page, ?open=<id> its address, the last session marked), Quests is the quest log, Relationships has the family trees
and anyone's connections."""

from sqlalchemy import select

from app import relations
from app.extraction import store_result
from app.importer import import_bundle
from app.models import Entity, ExtractionRun, Fact, GameSession, Status
from app.review import publish
from tests.roles import set_role
from tests.test_entities import BUNDLE, HX, admin, lillippi, player, published_events
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


def test_world_is_the_reader_without_quests(player, db):
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
    # Feedback 33 (Nov 6): the view says which session it means, the newest with a published recap
    assert 'Last session: <b>Session 2' in names and "the newest with a published recap" in names
    # Nothing asked for: the Reader opens on something from the last session, with its key moments as a timeline
    assert f'data-reader-id="{lillippi(db).id}"' in page and 'class="moment-line"' in page and "<dt>Last seen</dt><dd>Session 2" in page
    # Layout A (Brett, Nov 5): a person's picture is a portrait beside the name; the panel counts the key moments
    assert 'class="reader-article ep" data-shape="portrait"' in page and "<dt>Key moments</dt>" in page


def test_the_quest_board(player, db):
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


def test_player_characters_are_people_in_world(player, db):
    """Characters have relationships too, so World lists them under People and opens them there (Brett, 2026-10-23)."""
    from app.models import CampaignCharacter

    import_bundle(db, {**BUNDLE, "entities": BUNDLE["entities"] + [{"kind": "pc", "name": "Cole", "character": {"player_name": "Pat"}}]})
    cole = entry(db, "Cole")
    page = player.get(f"/c/main/campaign?open={cole.id}").text
    assert f'data-rd-id="{cole.id}"' in page and '"kind": "People"' in page[page.index(f'data-rd-id="{cole.id}"'):][:2000]
    assert f'data-reader-id="{cole.id}"' in page and "Player character" in page  # its World entry, not the side panel
    sheet = db.scalar(select(CampaignCharacter.character_id).where(CampaignCharacter.entity_id == cole.id))
    assert f'<dt>Its sheet</dt><dd><a href="/characters/{sheet}" data-no-peek>Open ↗</a>' in page
    assert 'data-noun="entry" data-nouns="entries"' in page  # "43 entries shown", not names


def test_relationships_and_connections(player, db, monkeypatch):
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
    # A picture beside the name, which still shows (feedback 34, Nov 7)
    from app import campaign_views
    monkeypatch.setattr(campaign_views.pictures, "urls", lambda db, ids: {mo.id: {"thumb": "/mo.webp"}} if mo.id in ids else {})
    cx = player.get(f"/campaign/{lil.id}/connections").text
    node = cx.split('class="cx-node npc has-pic"', 1)[1].split("</a>", 1)[0]
    assert 'class="cx-pic" src="/mo.webp"' in node and "<b>Mo</b>" in node
    # The Reader lists them, its names opening that entry, and opens the diagram from a link (layout A, Brett Nov 5)
    reader = player.get(f"/c/main/campaign?open={lil.id}").text
    assert f'Child of</span> <a class="ent" href="/c/main/campaign?open={mo.id}"' in reader
    assert f'data-modal-url="/c/main/campaign/{lil.id}/connections">See the connections map' in reader and 'class="cx-diagram"' not in reader


def test_an_entry_has_its_own_address_and_swaps_in(player, db):
    import_bundle(db, BUNDLE)
    salt = entry(db, "Saltmarsh")
    page = player.get(f"/c/main/campaign?open={salt.id}").text
    assert f'data-reader-id="{salt.id}"' in page and f'class="rd-item sel" data-ls-row data-rd-id="{salt.id}"' in page
    part = player.get(f"/campaign/{salt.id}/read").text
    assert '<article class="reader-article ep" data-shape="banner" id="reader-article"' in part  # a place: a wide banner
    assert "Fishing town." in part and "peek-close" not in part
    # Adding what the party learned from the Reader answers with the Reader
    r = player.post(f"/campaign/{salt.id}/facts?in=reader", data={"text": "Smells of fish."}, headers=HX)
    assert '<article class="reader-article ep' in r.text and "Smells of fish." in r.text
    assert db.scalar(select(Fact).where(Fact.entity_id == salt.id)).status == "pending"
    # The side panel elsewhere offers the Reader
    assert f'href="/c/main/campaign?open={salt.id}">Open in Campaign' in player.get(f"/campaign/{salt.id}/peek").text


def test_hidden_entries_and_quest_status_are_for_the_dm(monkeypatch, db):
    """A standing rule: an entry the DM keeps hidden shows only to the DM, and only the DM adds quests or marks them
    done."""
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


def _alias_queries(db, client, path):
    """How many SQL statements opening `path` takes to read entries' other names (entity_aliases)."""
    from sqlalchemy import event

    n = [0]

    def count(conn, cursor, statement, *_):
        n[0] += "FROM entity_aliases" in statement

    db.expire_all()  # the page shares the test's session: start from nothing loaded, as a real request does
    conn = db.connection()
    event.listen(conn, "before_cursor_execute", count)
    try:
        assert client.get(path).status_code == 200
    finally:
        event.remove(conn, "before_cursor_execute", count)
    return n[0]


def test_more_entries_dont_mean_more_queries(player, db):
    """The Campaign page loads its entries' other names together (Nov 2: one query per entry, 47 on beta's copy and
    growing every session). Ten more entries, each with another name (what the search box matches), take no more
    queries for them. (Only those are counted: the page's other queries vary by one as caches refill, Nov 2.)"""
    import_bundle(db, BUNDLE)
    import_bundle(db, QUESTS)
    published_events(db)
    before = _alias_queries(db, player, "/c/main/campaign")
    more = [{"kind": "npc", "name": f"Enemy {i}", "summary": "Someone.", "aliases": [f"The {i}th"]} for i in range(10)]
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": more})
    for e in db.scalars(select(Entity).where(Entity.name.like("Enemy %"))):
        e.status = Status.PUBLISHED
    db.flush()
    page = player.get("/c/main/campaign").text
    assert "enemy 9 the 9th" in page  # the name and its other name, in what the search box matches
    assert _alias_queries(db, player, "/c/main/campaign") == before


def test_an_entry_without_a_picture_asks_whoever_can_add_one(admin, player, db, monkeypatch):
    """World Entries by Kind (Brett, Nov 5): the DM's side sees the picture's place, in its kind's shape, with Draw one
    (when Describe it can draw) and Upload; a player sees no empty box, only a badge with the initials."""
    from app import drawing

    import_bundle(db, BUNDLE)
    lil, salt = lillippi(db), entry(db, "Saltmarsh")
    monkeypatch.setattr(drawing, "why_not", lambda db, campaign: "")
    page = admin.get(f"/c/main/campaign?open={lil.id}").text
    assert 'class="ep-slot ep-side"' in page and "No picture yet" in page
    assert f'data-modal-url="/pictures?for=entity:{lil.id}&amp;tab=draw">✦ Draw one' in page
    assert f'data-modal-url="/pictures?for=entity:{lil.id}">Upload' in page
    assert 'class="ep-slot ep-banner"' in admin.get(f"/campaign/{salt.id}/read").text  # a place: a wide banner
    # Draw one opens the window on Describe it, the entry's own words filled in
    window = admin.get(f"/pictures?for=entity:{lil.id}&tab=draw").text
    assert 'aria-selected="true" data-tab="pw-draw"' in window and '<div id="pw-up" hidden>' in window and "Lillippi" in window
    # Describe it can't draw (no key, or the month's limit): Upload alone
    monkeypatch.setattr(drawing, "why_not", lambda db, campaign: "No key")
    assert "Draw one" not in admin.get(f"/campaign/{lil.id}/read").text
    # A player: no empty place, a badge with the initials
    mine = player.get(f"/c/main/campaign?open={lil.id}").text
    assert "ep-slot" not in mine and "No picture yet" not in mine and 'class="ep-initials" data-kind="npc"' in mine


def test_story_text_sits_on_a_faint_scroll(player, db):
    """Brett, Nov 5 (board 5: Umber, Inter, Faint): a session's recap on the scroll with its rods; an entry's story the
    parchment alone."""
    import_bundle(db, BUNDLE)
    published_events(db)
    home = player.get("/c/main/").text
    assert '<div class="scroll">' in home and '<div class="tale-text">' in home and 'class="tale-end"' in home
    sessions = player.get("/c/main/?tab=sessions").text  # All sessions: each a rolled scroll, the newest open
    assert '<details class="tale-roll"' in sessions and 'class="tale-roll-text"' in sessions
    assert '<div class="story">' in player.get(f"/campaign/{entry(db, 'Saltmarsh').id}/read").text


def test_all_sessions_reads_from_the_start_and_shows_a_few_key_moments(player, db, monkeypatch):
    """Brett, Nov 5: All sessions shows a session's first few key moments and Show all for the rest, and every recap
    can be read in order, the first session first, all of them open."""
    from app import story as story_mod

    import_bundle(db, BUNDLE)
    published_events(db)
    newest = player.get("/c/main/?tab=sessions").text
    start = player.get("/c/main/?tab=sessions&order=start").text
    assert 'aria-current="true">Newest first' in newest and 'aria-current="true">From the start' in start
    ids = lambda page: list(__import__("re").findall(r'<details class="tale-roll" id="s(\d+)"', page))
    assert ids(start) == list(reversed(ids(newest))) and len(ids(start)) >= 2
    assert all(f'id="s{i}" open' in start for i in ids(start))  # every scroll open
    # A session's key moments past the first three sit behind Show all
    real = story_mod.published_story

    from types import SimpleNamespace

    def like(e, n, major=None):  # (a copy of a moment, its own)
        return SimpleNamespace(kind=e.kind, text=f"{e.text} ({n})", entities=e.entities, major=major)

    def many(db, majors=()):
        out = real(db)
        for item in out.get("items") or []:
            evs = item.get("events") or []
            item["events"] = [like(e, n, major=(n, i) in majors) for n in range(5) for i, e in enumerate(evs)] or evs
        if out.get("latest"):
            out["latest"]["events"] = (out["items"] or [{}])[-1].get("events") or out["latest"]["events"]
        return out
    monkeypatch.setattr(story_mod, "published_story", many)
    most = max(len(i.get("events") or []) for i in many(db)["items"])
    assert most > 4  # (the test's sessions, each moment five times)
    page = player.get("/c/main/?tab=sessions").text
    assert f'<details class="tale-more"><summary>Show the other {most - 3} key moments</summary>' in page
    # Feedback 40 (Brett, Nov 7): too many to scroll. The major ones show (here two), the rest behind the fold
    monkeypatch.setattr(story_mod, "published_story", lambda db: many(db, majors={(1, 0), (3, 0)}))
    page = player.get("/c/main/?tab=sessions").text
    shown = page.split('<ol class="moment-line tale-moments">', 1)[1].split("</ol>", 1)[0]
    assert shown.count('class="ev ') == 2 and "(1)" in shown and "(3)" in shown
    assert f"Show the other {most - 2} key moments" in page
