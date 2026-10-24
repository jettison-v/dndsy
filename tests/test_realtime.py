"""The live table connection (VTT 0.3, app/realtime.py): pages at a campaign's table hear within a second that
something changed (a roll, a character), never what it was, and only after it's saved."""

import pytest

from app import characters, realtime
from app import table_rolls as tr
from tests.test_characters import char, no_network  # noqa: F401
from tests.test_table_rolls import post, table  # noqa: F401


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
    with pytest.raises(Exception):
        with TestClient(app).websocket_connect(f"/live/connect?c={cole.campaign_id}"):
            pass
    with pytest.raises(Exception):
        with table["player"].websocket_connect(f"/live/connect?c={cole.campaign_id + 999}"):
            pass


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


def test_a_character_is_announced_only_when_dnd_beyond_changed_it(db, monkeypatch, no_network):  # noqa: F811
    from app.importer import import_bundle
    from tests.test_characters import BUNDLE

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
