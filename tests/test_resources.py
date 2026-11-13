"""Counting in play (app/resources.py): class resources and slots, through the bridge."""

import pytest
from sqlalchemy import select

from app import characters, ddb_bridge, resources
from app.models import BridgeIntent, Campaign
from tests.table_setup import char


@pytest.fixture(autouse=True)
def test_campaign(db, sheet):
    """Live state comes with Sync with D&D Beyond (app/vtt.py), switched on for the campaign."""
    db.get(Campaign, char(db, "Cole").campaign_id).vtt_pieces = ["sync"]
    db.flush()


def action(sheet, name):
    return next(a for a in sheet["actions"] if a["name"] == name)


def field(cole, name):
    return f"uses:{action(characters.character_summary(cole), name)['id']}"


def test_what_each_count_says():
    sheet = {"actions": [{"id": 7, "name": "Focus Points", "uses": {"left": 1, "max": 2, "reset_phrase": "back after a Short Rest"}}],
             "spell_slots": {"slots": [{"level": 1, "max": 4, "used": 1}], "pact": {"level": 3, "max": 2, "used": 2}}}
    assert resources.count(sheet, "uses:7") == {"name": "Focus Points", "left": 1, "max": 2, "back": "back after a Short Rest"}
    assert resources.count(sheet, "slot:1")["left"] == 3
    assert resources.count(sheet, "pact:3")["left"] == 0
    assert resources.count(sheet, "uses:8") is None and resources.count(sheet, "slot:2") is None and resources.count(sheet, "hp") is None


def test_use_one_goes_to_d_and_d_beyond_and_shows_at_once_and_undo_gives_it_back(player, db, sheet):
    cole = char(db, "Cole")
    f = field(cole, "Focus Points")
    assert "2 of 2 left" in player.get(f"/characters/{cole.id}/count?field={f}").text
    r = player.post(f"/characters/{cole.id}/count?field={f}", data={"to": "use"}).json()
    assert r["text"] == "Focus Points: 1 of 2 left" and r["deliver"]
    it = db.scalar(select(BridgeIntent))
    assert it.kind == "use" and it.data["field"] == f and it.data["delta"] == 1 and it.data["max"] == 2
    shown = ddb_bridge.as_shown(db, cole, characters.character_summary(cole))
    assert action(shown, "Focus Points")["uses"]["left"] == 1
    assert player.post(r["undoUrl"], data=r["undo"]).json()["text"] == "Focus Points: 2 of 2 left"


def test_a_slot_can_be_spent_by_hand(player, db, sheet):
    cole = char(db, "Cole")
    r = player.post(f"/characters/{cole.id}/count?field=slot:1", data={"to": "use"})
    assert r.status_code == 200 and db.scalar(select(BridgeIntent)).data["field"] == "slot:1"


def test_nothing_to_give_back_or_nothing_left_is_refused(player, db, sheet):
    cole = char(db, "Cole")
    assert player.post(f"/characters/{cole.id}/count?field=slot:1", data={"to": "back"}).status_code == 409
    assert db.scalar(select(BridgeIntent)) is None


def test_a_closed_sheet_says_how_and_only_the_player_counts(player, dm, db, sheet):
    cole = char(db, "Cole")
    f = field(cole, "Wild Shape")
    assert dm.post(f"/characters/{cole.id}/count?field={f}", data={"to": "use"}).status_code == 404
    cole.sheet_heard_at = None
    db.flush()
    assert "can't be reached" in player.get(f"/characters/{cole.id}/count?field={f}").text
    assert player.post(f"/characters/{cole.id}/count?field={f}", data={"to": "use"}).status_code == 409


def test_battle_has_cast_and_the_resources_open_their_window(player, db, sheet):
    cole = char(db, "Cole")
    page = player.get(f"/characters/{cole.id}/battle").text
    assert f'/characters/{cole.id}/count?field=uses%3A' in page or f'/characters/{cole.id}/count?field=uses:' in page


def test_a_campaign_without_sync_doesnt_see_any_of_it(player, db, sheet):
    """Live state comes only with Sync with D&D Beyond (app/vtt.py): without it, none of it shows."""
    cole = char(db, "Cole")
    db.get(Campaign, cole.campaign_id).vtt_pieces = []
    db.flush()
    page = player.get(f"/characters/{cole.id}/battle").text
    assert "/count?field=" not in page and "/cast?key=" not in page
    assert player.get(f"/characters/{cole.id}/count?field=slot:1").status_code == 404
    assert player.post(f"/characters/{cole.id}/rest?kind=long").status_code == 404



def test_every_count_of_yours_opens_use_one_and_give_one_back(player, dm, db, sheet):
    """Brett, Nov 3: Wild Shape's pips open the same window as spell slots, and so does every count of the player's that
    shows: Sheet's slots and Wild Shape uses, a feature's uses, an item's charges (a Soul Coin's too), the side panel's.
    Someone else's character only shows them."""
    cole = char(db, "Cole")
    ws, coin = field(cole, "Wild Shape"), "charges:992695540"
    battle, page = player.get(f"/characters/{cole.id}/battle").text, player.get(f"/characters/{cole.id}").text
    opens = lambda html, f: f'data-use-url="/characters/{cole.id}/count?field={f.replace(":", "%3A")}"' in html
    assert opens(battle, ws)  # Battle's Wild Shape row
    assert opens(page, "slot%3A1".replace("%3A", ":")) and opens(page, ws) and opens(page, coin)  # Sheet: slots, Wild Shape, an item's charges
    assert page.count(f"count?field={ws.replace(':', '%3A')}") >= 2  # (and Features' Wild Shape row)
    panel = player.get(f"/characters/{cole.id}/detail", params={"ref": "action:Wild Shape"}).text
    assert opens(panel, ws)
    assert player.get(f"/characters/{cole.id}/count?field={coin}").status_code == 200  # (the window itself)
    assert not opens(dm.get(f"/characters/{cole.id}").text, coin)  # (not the DM's: only the player's own)
