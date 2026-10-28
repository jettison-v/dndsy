"""The live table connection (VTT 0.3, app/realtime.py): pages at a campaign's table hear within a second that
something changed (a roll, a character), never what it was, and only after it's saved."""

import pytest
from starlette.websockets import WebSocketDisconnect

from app import characters, realtime
from app import table_rolls as tr
from tests.table_setup import char
from tests.test_table_rolls import post, table  # noqa: F401

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)


def test_a_roll_reaches_every_page_at_the_table_without_its_number(table, db, monkeypatch):  # noqa: F811
    monkeypatch.setattr(tr, "die", lambda sides: 11)
    cole, sent, publish = char(db, "Cole"), [], realtime.publish
    monkeypatch.setattr(realtime, "publish", lambda *a, **k: (sent.append(a), publish(*a, **k)))
    with table["other"].websocket_connect(f"/live/connect?c={cole.campaign_id}") as ws:
        assert realtime.connected(cole.campaign_id) == 1
        post(table["player"], character=cole.id, kind="check", label="Stealth check", mod="6", to="dm")
        assert sent == [(cole.campaign_id, "rolls")]  # so the page has it waiting (receive_json would wait forever)
        assert ws.receive_json() == {"type": "rolls"}  # what changed, never the roll: the log decides who sees it
        ws.send_text("ping")  # the page's keep-alive is fine
    assert realtime.connected(cole.campaign_id) == 0


def test_only_your_own_campaigns_and_only_signed_in(table, db):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.main import app

    cole = char(db, "Cole")
    for client, campaign_id in ((TestClient(app), cole.campaign_id), (table["player"], cole.campaign_id + 999)):
        with client.websocket_connect(f"/live/connect?c={campaign_id}") as ws:
            with pytest.raises(WebSocketDisconnect) as refused:
                ws.receive_text()
        assert refused.value.code == 4403  # the code the page knows means "stop retrying"
    assert realtime.connected(cole.campaign_id) == 0


def test_announced_after_commit_never_after_rollback(db, monkeypatch):
    from sqlalchemy import text

    sent = []
    monkeypatch.setattr(realtime, "publish", lambda campaign_id, kind, **data: sent.append((campaign_id, kind, data)))
    realtime.announce(db, 1, "rolls")
    realtime.announce(db, 1, "rolls")
    assert sent == []  # not before it's saved
    db.commit()
    assert sent == [(1, "rolls", {})]  # once per change
    db.execute(text("select 1"))  # a change under way
    realtime.announce(db, 1, "rolls")
    db.rollback()
    db.commit()
    assert sent == [(1, "rolls", {})]


def test_a_character_is_announced_only_when_dnd_beyond_changed_it(db, monkeypatch, no_network):
    from app.importer import import_bundle
    from tests.table_setup import BUNDLE

    import_bundle(db, BUNDLE)
    sent = []
    monkeypatch.setattr(realtime, "publish", lambda campaign_id, kind, **data: sent.append((campaign_id, kind, data)))
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    db.commit()
    assert sent == [(cole.campaign_id, "character", {"id": cole.id})]
    characters.refresh(db, cole)  # the same sheet again
    db.commit()
    assert len(sent) == 1


def test_whatever_the_table_sees_of_a_character_announces_itself_however_its_made(db, monkeypatch, no_network):
    """A condition, Concentration or Wild Shape set in askdnd reaches every page like a read of D&D Beyond does
    (realtime.TABLE_SEES); a player's own pin or note doesn't go to the table at all."""
    from app import picks
    from app.importer import import_bundle
    from tests.table_setup import BUNDLE

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    db.commit()
    sent = []
    monkeypatch.setattr(realtime, "publish", lambda campaign_id, kind, **data: sent.append((campaign_id, kind, data)))
    cole.conditions = [{"name": "Invisible", "source": "Ring of Invisibility"}]
    db.commit()
    assert sent == [(cole.campaign_id, "character", {"id": cole.id})]
    cole.conditions = [{"name": "Invisible", "source": "Ring of Invisibility"}]  # the same again: nothing new
    db.commit()
    picks.toggle(db, cole, "star", "spell:Heat Metal", "Heat Metal")
    db.commit()
    assert len(sent) == 1


def test_other_sites_pages_are_refused(table, db):  # noqa: F811
    cole = char(db, "Cole")
    with table["other"].websocket_connect(f"/live/connect?c={cole.campaign_id}", headers={"origin": "https://elsewhere.example"}) as ws:
        with pytest.raises(WebSocketDisconnect) as refused:
            ws.receive_text()
    assert refused.value.code == realtime.REFUSED
    with table["other"].websocket_connect(f"/live/connect?c={cole.campaign_id}", headers={"origin": "http://testserver"}):
        assert realtime.connected(cole.campaign_id) == 1  # askdnd's own page


def test_someone_removed_from_the_campaign_is_cut_off(table, db, monkeypatch):  # noqa: F811
    cole = char(db, "Cole")
    monkeypatch.setattr(realtime, "RECHECK_SECONDS", 0.05)
    with table["other"].websocket_connect(f"/live/connect?c={cole.campaign_id}") as ws:
        monkeypatch.setattr(realtime, "_allowed", lambda email, campaign_id: False)  # removed meanwhile
        with pytest.raises(WebSocketDisconnect) as cut:
            ws.receive_text()
    assert cut.value.code == realtime.REFUSED and realtime.connected(cole.campaign_id) == 0


def test_a_slow_page_holds_each_message_once():
    async def run():
        page = realtime._Page()
        for msg in ('{"type": "rolls"}', '{"type": "character", "id": 7}', '{"type": "rolls"}'):
            page.offer(msg)
        assert page.wake.is_set()
        return page.take(), page.wake.is_set()

    import asyncio

    assert asyncio.run(run()) == (['{"type": "rolls"}', '{"type": "character", "id": 7}'], False)


def test_every_copy_of_the_app_hears_a_change_through_postgres(db_engine, monkeypatch):
    """Two copies (or a deploy's old and new) each LISTEN; a change published on one reaches pages on both."""
    import asyncio
    import threading
    import time

    from tests.conftest import TEST_DATABASE_URL

    got, loop = [], asyncio.new_event_loop()
    monkeypatch.setattr(realtime, "deliver", lambda campaign_id, msg: got.append((campaign_id, msg)))
    monkeypatch.setattr("app.db.engine", db_engine)
    task = loop.create_task(realtime.listen(TEST_DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")))
    def run():
        try:
            loop.run_until_complete(task)
        except asyncio.CancelledError:
            pass

    thread = threading.Thread(target=run, daemon=True)
    try:
        thread.start()
        end = time.monotonic() + 5
        while not realtime._bus["up"] and time.monotonic() < end:
            time.sleep(0.02)
        assert realtime._bus["up"]
        realtime.publish(5, "character", id=9)
        while not got and time.monotonic() < end:
            time.sleep(0.02)
        assert got == [(5, '{"type": "character", "id": 9}')]
    finally:
        loop.call_soon_threadsafe(task.cancel)
        thread.join(5)
    assert not realtime._bus["up"]  # stopped: a copy delivers to its own pages directly again
