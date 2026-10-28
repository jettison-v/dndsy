"""Game Mode, one switch for the whole table (app/game_mode.py; decided 2026-10-28, docs/mockups/game-mode-and-bridge.html):
anyone at the table starts or ends it, every page draws it, it tells every open page, and it lasts the game timer."""

from datetime import UTC, datetime, timedelta

import pytest

from app import realtime
from app.importer import import_bundle
from app.models import Campaign
from tests.roles import set_role
from tests.table_setup import BUNDLE, char


def _campaign(db) -> Campaign:
    return db.get(Campaign, char(db, "Cole").campaign_id)


def test_anyone_at_the_table_starts_it_for_everyone_and_anyone_ends_it(player, dm, db, monkeypatch):
    import_bundle(db, BUNDLE)
    set_role(db, "player@example.com", "player").name = "Pat"
    set_role(db, "dm@example.com", "dm")
    sent = []
    monkeypatch.setattr(realtime, "publish", lambda campaign_id, kind, **data: sent.append((campaign_id, kind)))
    assert 'class="gm-on"' not in dm.get("/c/main/").text
    panel = player.post("/live/game", data={"on": "1"}).text
    assert "On for the table" in panel and "Started by Pat" in panel and "End for the table" in panel
    assert sent == [(_campaign(db).id, "game")]  # every open page at the table shows its new copy
    page = dm.get("/c/main/").text  # someone else's page is drawn with it
    assert 'class="gm-on"' in page and 'data-game-by="Pat"' in page
    dm.post("/live/game", data={"on": ""})  # anyone ends it
    assert 'class="gm-on"' not in player.get("/c/main/").text and len(sent) == 2


def test_only_someone_at_the_table_can_switch_it(player, db):
    import_bundle(db, BUNDLE)
    assert player.post("/live/game", data={"on": "1"}).status_code == 403  # signed in, but no role in this campaign
    assert _campaign(db).game_until is None


def test_it_lasts_the_game_timer_then_its_off_by_itself(player, db):
    import_bundle(db, BUNDLE)
    set_role(db, "player@example.com", "player")
    player.post("/live/game", data={"on": "1"})
    campaign = _campaign(db)
    assert campaign.game_until - datetime.now(UTC) == pytest.approx(timedelta(hours=6), abs=timedelta(minutes=1))
    assert 'data-game-warn="600"' in player.get("/c/main/").text  # every page warns ten minutes before, with Keep going
    campaign.game_until = datetime.now(UTC) - timedelta(seconds=1)
    db.flush()
    assert 'class="gm-on"' not in player.get("/c/main/").text
