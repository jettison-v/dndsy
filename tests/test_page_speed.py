"""Pages stay quick as the campaign grows (Performance: the whole tool, Brett's Roadmap item, Nov 20).

Two rules, over every page in the app (tests/test_reading.py's list, so a new page is covered the day it's added):

- **No page loads a whole D&D Beyond sheet.** A sheet is about half a megabyte, and on askdnd.ai every one loaded
  crosses Railway's network: Nov 20, a party page took 2 s loading twelve. A page reads the summary, or a path into the
  sheet (`CharacterSnapshot.raw["campaign"]["name"]`); only sending a change to D&D Beyond reads the whole of it.
- **A page's reads don't grow with the campaign.** Each read costs about 2 ms more on askdnd.ai than here: History read
  every change's row on its own (400 reads), the Campaign page each quest's moments, givers and facts on its own.
  `scripts/page_speed.py` times every page on the local copy of askdnd.ai's data."""

import re

import pytest
from sqlalchemy import event

from app import relations
from app.models import Entity, EntityKind, EventKind, GameSession, Recap, Status, StoryEvent
from tests.table_setup import address, sign_in
from tests.test_reading import reading_routes, table

pytestmark = pytest.mark.usefixtures("no_network")
PEOPLE = ("admin@example.com", "dm@example.com", "player@example.com")
WHOLE = r"(?=,|\s|$)(?!\s*->)"  # (the column itself, not a path into it)
GROWTH = 2  # reads a page may add for one more session with ten quests, ten key moments and twenty changes


def _reads(db, client, path: str) -> tuple[int, int]:
    """(reads, whole sheets) for one page."""
    seen = {"n": 0, "sheets": 0}

    def count(conn, cursor, statement, *_):
        seen["n"] += 1
        head = re.split(r"\sFROM\s", statement, maxsplit=1)[0]
        seen["sheets"] += len(re.findall(r"character_snapshots\.raw" + WHOLE, head))

    engine = db.get_bind().engine
    db.flush()
    db.expunge_all()  # (every page starts cold, as a request on askdnd.ai does: the test's one session keeps rows otherwise)
    event.listen(engine, "before_cursor_execute", count)
    try:
        client.get(path, follow_redirects=False)
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return seen["n"], seen["sheets"]


def _every_page(db, monkeypatch, ids) -> dict[tuple[str, str], tuple[int, int]]:
    out = {}
    for who in PEOPLE:
        c = sign_in(monkeypatch, db, who)
        for path, op in reading_routes():
            out[(who, path)] = _reads(db, c, address(path, op, ids))
    return out


def _grow(db, campaign_id: int, batch: int, n: int = 10) -> None:
    """One more played session, and in it ten more quests, each given by someone and named in a published key moment,
    and two changes to each (rows in History)."""
    s = GameSession(campaign_id=campaign_id, number=90 + batch, title=f"A long night {batch}", source="notes")
    db.add(s)
    db.flush()
    db.add(Recap(session_id=s.id, version=1, body="It went on.", author="ai", status=Status.PUBLISHED))
    giver = Entity(campaign_id=campaign_id, kind=EntityKind.NPC, name=f"Quest Giver {batch}", summary="Gives quests.", status=Status.PUBLISHED)
    db.add(giver)
    quests = [Entity(campaign_id=campaign_id, kind=EntityKind.QUEST, name=f"Errand {batch}-{i}", summary="An errand.",
                     status=Status.PUBLISHED, quest_open=True) for i in range(n)]
    db.add_all(quests)
    db.flush()
    for i, q in enumerate(quests):
        relations.add(db, giver, "gave", q)
        ev = StoryEvent(session_id=s.id, position=i, kind=EventKind.EVENT, text=f"The party took errand {i}.", status=Status.PUBLISHED)
        ev.entities.append(q)
        db.add(ev)
    db.flush()
    for q in quests:
        q.summary = "An errand, half done."
        db.flush()
        q.summary = "An errand, done."
        db.flush()


def test_a_standing_rule_no_page_loads_a_whole_sheet(db, table, monkeypatch):
    """A standing rule (Brett, Nov 20, Performance: the whole tool): a D&D Beyond sheet is half a megabyte, and every page
    that loaded it crossed Railway's network with it."""
    loads = {k: v[1] for k, v in _every_page(db, monkeypatch, table).items() if v[1]}
    assert not loads, f"pages that load a whole sheet (read the summary or a path into it): {loads}"


def test_no_pages_reads_grow_with_the_campaign(db, table, monkeypatch):
    """Grown once, then again by as much: a page whose reads rise between the two reads per session, quest, key moment
    or change (a fixed few more once there's something to show is fine: the first growth absorbs it)."""
    campaign_id = table_campaign(db, table)
    _grow(db, campaign_id, 1)
    once = _every_page(db, monkeypatch, table)
    _grow(db, campaign_id, 2)
    twice = _every_page(db, monkeypatch, table)
    grew = {f"{who.split('@')[0]} {path}": (once[(who, path)][0], n) for (who, path), (n, _) in twice.items()
            if n - once[(who, path)][0] > GROWTH}
    assert not grew, f"pages whose reads grow with the campaign (one more session of ten quests: before, after): {grew}"


def table_campaign(db, ids) -> int:
    from app.models import Character

    return db.get(Character, ids["character_id"]).campaign_id
