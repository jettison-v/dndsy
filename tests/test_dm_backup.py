"""The DM as a backup (app/ddb_bridge.py `carried`; DM Backup Option A, Brett 2026-11-02, docs/mockups/dm-backup/): when
a character's own sheet is closed, its campaign's DM's browser with any D&D Beyond page open makes its changes. D&D
Beyond is never called: the fake sheet stands in (tests/conftest.py `sheet`)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import ddb_bridge
from app.models import BridgeIntent, BridgeLog, Campaign, Character
from tests.roles import set_role
from tests.table_setup import char
from tests.test_ddb_bridge import make

GAME = "8224496"  # the campaign's D&D Beyond game


@pytest.fixture
def table(db, sheet):
    """Cole's sheet closed, Cole in the campaign's D&D Beyond game, the backup on (a test campaign has every piece) and
    dm@example.com its DM. Everyone else's sheet is closed too."""
    cole = char(db, "Cole")
    campaign = db.get(Campaign, cole.campaign_id)
    campaign.is_test, campaign.ddb_campaign_id = True, GAME
    set_role(db, "dm@example.com", "dm", "Dee", campaign)
    for ch in db.scalars(select(Character)):
        ch.sheet_heard_at, ch.ddb_campaign_id = None, GAME
    db.flush()
    return cole


def carry(client, pages=1):
    return client.post("/bridge/carry", json={"pages": pages}).json()


def test_a_closed_sheets_change_is_made_by_the_dms_browser(player, dm, db, table, sheet):
    """Option A: on its own, for every change, and askdnd's log says the DM's browser made it (D&D Beyond doesn't)."""
    cole = table
    assert ddb_bridge.how(cole) is None
    assert player.post(f"/bridge/hp/{cole.id}", data={"amount": -1}).status_code == 409  # no one can reach it yet

    assert carry(dm) == {"sheets": [], "every": ddb_bridge.CARRY_EVERY}  # the DM opened a D&D Beyond page
    assert ddb_bridge.how(cole) == "dm"
    assert player.post(f"/bridge/hp/{cole.id}", data={"amount": -1}).status_code == 200
    assert carry(dm)["sheets"] == ["75423618"]  # a change waits for the DM's browser

    batch = dm.post("/bridge/outbox/75423618").json()["batch"]
    assert batch["ddb"] == "75423618" and all(op["body"]["characterId"] == 75423618 for op in batch["ops"])
    assert cole.sheet_heard_at is None  # (the DM's browser isn't the sheet: it never says the sheet is open)
    make(sheet, batch)
    assert dm.post(f"/bridge/delivered/{batch['id']}", json={"ok": True}).status_code == 200
    assert db.scalar(select(BridgeIntent.state)) == "live"
    assert db.scalar(select(BridgeLog.text).order_by(BridgeLog.id.desc())).endswith(ddb_bridge.THROUGH_DM)
    assert [r["name"] for r in ddb_bridge.made_through(db, db.get(Campaign, cole.campaign_id))] == ["Cole"]
    assert carry(dm)["sheets"] == []


def test_the_players_own_sheet_always_goes_first(player, dm, db, table):
    cole = table
    carry(dm)
    player.post(f"/bridge/hp/{cole.id}", data={"amount": -1})
    cole.sheet_heard_at = datetime.now(UTC)  # the player opened their sheet
    db.flush()
    assert ddb_bridge.how(cole) == "sheet"
    assert dm.post("/bridge/outbox/75423618").json() == {"batch": None}
    assert carry(dm)["sheets"] == []


def test_only_the_dm_carries_only_where_its_on_and_only_in_its_game(player, dm, db, table):
    """The DM's rights on D&D Beyond reach only the characters in that D&D Beyond campaign, and a player's browser
    carries nothing."""
    cole = table
    assert carry(player) == {"sheets": [], "every": 0}
    assert ddb_bridge.how(cole) is None
    carry(dm)
    cole.ddb_campaign_id = "999"  # in another D&D Beyond game: its DM there isn't this one
    db.flush()
    assert ddb_bridge.how(cole) is None
    cole.ddb_campaign_id = GAME
    campaign = db.get(Campaign, cole.campaign_id)
    campaign.is_test, campaign.vtt_pieces = False, ["ddb_bridge"]  # a campaign that isn't a test one, without the piece
    db.flush()
    assert ddb_bridge.how(cole) is None and carry(dm)["every"] == 0


def test_the_last_dnd_beyond_page_closing_ends_it(dm, db, table):
    cole = table
    carry(dm)
    assert ddb_bridge.how(cole) == "dm"
    carry(dm, pages=0)
    assert ddb_bridge.how(cole) is None


def test_a_change_the_dm_carries_doesnt_give_up(player, dm, db, table, monkeypatch):
    """A change waits for the wait timer when its sheet is quiet (`_give_up`); the DM's browser can still make it."""
    cole = table
    carry(dm)
    player.post(f"/bridge/hp/{cole.id}", data={"amount": -1})
    monkeypatch.setattr(ddb_bridge, "timers", lambda db: {"idle": 1800, "wait": -1})
    ddb_bridge._give_up(db)
    assert db.scalar(select(BridgeIntent.state)) == "waiting"


def test_the_live_pill_is_yellow_through_the_dm_red_while_playing_grey_otherwise(player, dm, db, table):
    """Brett, 2026-11-02: green connected, yellow through the DM (still asking for the sheet), red can't while the
    table plays, grey when no one is connected."""
    cole = table
    page = player.get(f"/characters/{cole.id}").text
    assert 'class="live-pill"' in page and "Open your sheet to connect" in page  # grey: no one's connected

    other = next(c for c in db.scalars(select(Character)) if c.id != cole.id and c.ddb_id)
    other.sheet_heard_at = datetime.now(UTC)  # someone at the table is
    db.flush()
    assert 'class="live-pill bad"' in player.get(f"/characters/{cole.id}").text

    carry(dm)
    page = player.get(f"/characters/{cole.id}").text
    assert 'class="live-pill via"' in page and "Through the DM · open your sheet" in page
    window = player.get(f"/live?c={cole.id}").text
    assert "the DM's D&amp;D Beyond is making your changes" in window and "Open sheet ↗" in window
    assert "Through you · their sheet is closed" in dm.get("/live").text

    cole.sheet_heard_at = datetime.now(UTC)
    db.flush()
    assert 'class="live-pill step"' in player.get(f"/characters/{cole.id}").text
