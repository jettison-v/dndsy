"""The DM as a backup (app/ddb_bridge.py `carried`; DM Backup Option A, Brett 2026-11-02, docs/mockups/dm-backup/): when
a character's own sheet is closed, its campaign's DM's browser with any D&D Beyond page open makes its changes. D&D
Beyond is never called: the fake sheet stands in (tests/conftest.py `sheet`)."""

from datetime import UTC, datetime, timedelta

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
    """Cole's sheet closed, Cole in the campaign's D&D Beyond game, the backup on (Sync with D&D Beyond) and
    dm@example.com its DM. Everyone else's sheet is closed too."""
    cole = char(db, "Cole")
    campaign = db.get(Campaign, cole.campaign_id)
    campaign.vtt_pieces, campaign.ddb_campaign_id = ["sync"], GAME
    set_role(db, "dm@example.com", "dm", "Dee", campaign)
    for ch in db.scalars(select(Character)):
        ch.sheet_heard_at, ch.ddb_campaign_id = None, GAME
    sheet["campaign"] = {"id": int(GAME), "name": "VTT test"}  # (as a read of Cole's sheet says too)
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
    campaign.vtt_pieces = []  # a campaign without Sync with D&D Beyond
    db.flush()
    assert ddb_bridge.how(cole) is None and carry(dm)["every"] == 0


def test_the_last_dnd_beyond_page_closing_ends_it_unless_another_browser_carries(dm, db, table):
    """Its mark runs out within CARRY_GRACE, not at once: a second browser of the DM's still carrying marks it again
    first, so the table's pills don't flick to red and back (review, 2026-11-02)."""
    cole = table
    campaign = db.get(Campaign, cole.campaign_id)
    carry(dm)
    assert ddb_bridge.how(cole) == "dm"
    carry(dm, pages=0)  # one browser's last page closed
    assert ddb_bridge.how(cole) == "dm"
    carry(dm)  # the other browser still has one open: marked again, from now
    assert datetime.now(UTC) - campaign.backup_heard_at < ddb_bridge.CARRY_MARK

    carry(dm, pages=0)  # its last one closed too
    campaign.backup_heard_at -= ddb_bridge.CARRY_GRACE + timedelta(seconds=1)  # (CARRY_GRACE later)
    db.flush()
    assert ddb_bridge.how(cole) is None


def test_the_dms_open_copy_of_a_players_sheet_isnt_its_own(player, dm, db, table, sheet):
    """Review, 2026-11-02: a DM often keeps the party's sheets open. Their copy is a D&D Beyond page in the DM's browser,
    so the DM carries its changes, and it never says the player's own sheet is open or closed."""
    cole = table
    carry(dm)
    assert dm.post("/bridge/heard/75423618?pull=1").status_code == 200  # the DM's copy, pulled every 30 seconds
    assert ddb_bridge.how(cole) == "dm" and cole.sheet_heard_at is None
    assert player.post(f"/bridge/hp/{cole.id}", data={"amount": -1}).status_code == 200
    batch = dm.post("/bridge/outbox/75423618").json()["batch"]
    assert batch and batch["ddb"] == "75423618"
    assert 'class="live-pill via"' in player.get(f"/characters/{cole.id}").text  # not green: their own sheet is closed

    cole.sheet_heard_at = datetime.now(UTC)  # the player opens their own sheet
    db.flush()
    dm.post("/bridge/closed/75423618")  # the DM closes their copy
    assert ddb_bridge.own_sheet(cole)
    player.post("/bridge/closed/75423618")  # the player closes theirs
    assert not ddb_bridge.own_sheet(cole)


def test_a_campaign_not_linked_to_dnd_beyond_carries_no_one(player, dm, db, table):
    """Only the DM of that D&D Beyond campaign may change its characters there, so a campaign that doesn't say which is
    its own can't be carried (review, 2026-11-02), and the DM's Live window says how to link it."""
    cole = table
    db.get(Campaign, cole.campaign_id).ddb_campaign_id = None
    db.flush()
    carry(dm)
    assert ddb_bridge.how(cole) is None
    other = next(c for c in db.scalars(select(Character)) if c.id != cole.id and c.ddb_id)
    other.sheet_heard_at = datetime.now(UTC)  # (the table is playing)
    db.flush()
    assert "isn't linked to its D&amp;D Beyond campaign" in dm.get("/live").text


def test_the_carry_reads_a_closed_sheet_at_most_once_a_minute(player, dm, db, table, monkeypatch):
    """A change that gave up quietly is caught up by reading the sheet; every DM page ticking doesn't read it each time."""
    cole = table
    carry(dm)
    player.post(f"/bridge/hp/{cole.id}", data={"amount": -1})
    intent = db.scalar(select(BridgeIntent))
    intent.state, intent.data = "not_yet", {**intent.data, "quiet": True}
    db.flush()
    reads = []
    monkeypatch.setattr(ddb_bridge, "heard", lambda db, ch, saved=True: reads.append(ch.id))
    monkeypatch.setattr(ddb_bridge, "_carry_read", {})
    carry(dm)
    carry(dm)
    assert reads == [cole.id]


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
