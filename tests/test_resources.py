"""Counting in play (app/resources.py): class resources and slots, through the bridge."""

from sqlalchemy import select

from app import characters, ddb_bridge, resources
from app.models import BridgeIntent
from tests.table_setup import char


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
