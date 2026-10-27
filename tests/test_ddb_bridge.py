"""The D&D Beyond bridge, a local proof (app/ddb_bridge.py): askdnd counts a change only once D&D Beyond has it.
D&D Beyond is never called: a fake sheet stands in, and each test changes it the way the extension or the player would."""

import copy

import pytest

from app import characters, config, ddb_bridge
from app.importer import import_bundle
from tests.table_setup import BUNDLE, COLE, char, owned_by

POTION = 758022089  # Cole's Potion of Healing on D&D Beyond (×2 in the fixture)


@pytest.fixture
def sheet(monkeypatch, db):
    """Cole's D&D Beyond sheet as a dict the test edits; askdnd reads it whenever it refreshes."""
    data = copy.deepcopy(COLE)
    data["removedHitPoints"] = 14  # 37 of 51
    monkeypatch.setattr(characters.refresh, "__defaults__", (lambda _id: copy.deepcopy(data),))
    for store in (ddb_bridge._changes, ddb_bridge._logs, ddb_bridge._seen, ddb_bridge._refreshed):
        store.clear()
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    characters.refresh(db, cole)
    return data


def _potions(data):
    return next(i for i in data["inventory"] if i["id"] == POTION)


def test_a_drink_waits_for_d_and_d_beyond_and_counts_once_it_has_it(player, db, sheet):
    """A standing rule (Brett, 2026-10-27: no partial sync, it must be correct in both places or the difference shown):
    askdnd shows a change as made only after reading it back from D&D Beyond."""
    cole = char(db, "Cole")
    ch = ddb_bridge.drink(db, cole, POTION, roll=lambda sides: 3)  # 2d4 + 2 = 8
    assert ch["ops"] == [
        {"path": "/character/v5/inventory/item/quantity", "body": {"characterId": 75423618, "id": POTION, "quantity": 1}},
        {"path": "/character/v5/life/hp/damage-taken", "body": {"characterId": 75423618, "removedHitPoints": 6, "temporaryHitPoints": 0}}]
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["hp"]["current"] == 37 and st["items"][0]["quantity"] == 2  # nothing changes in askdnd yet
    assert [c["state"] for c in st["changes"]] == ["waiting"]

    _potions(sheet)["quantity"], sheet["removedHitPoints"] = 1, 6  # what the extension's two requests do on D&D Beyond
    st = player.post(f"/bridge/result/{ch['id']}", json={"ok": True}).json()
    assert st["hp"]["current"] == 45 and st["items"][0]["quantity"] == 1 and st["changes"] == []
    assert st["log"][0]["state"] == "live" and "drank a Potion of Healing: hit points 37 → 45" in st["log"][0]["text"]


def test_a_change_that_cant_be_made_says_so_and_changes_nothing(player, db, sheet):
    cole = char(db, "Cole")
    ch = ddb_bridge.drink(db, cole, POTION, roll=lambda sides: 1)
    st = player.post(f"/bridge/result/{ch['id']}", json={"ok": False, "error": "Open the character's D&D Beyond sheet in this browser."}).json()
    assert st["hp"]["current"] == 37 and st["items"][0]["quantity"] == 2
    assert st["changes"][0]["state"] == "not_yet" and "Open the character's" in st["changes"][0]["error"]
    assert player.post(f"/bridge/dismiss/{ch['id']}").json()["changes"] == []  # Undo: nothing to put back


def test_unconfirmed_changes_stop_waiting(player, db, sheet, monkeypatch):
    cole = char(db, "Cole")
    ddb_bridge.drink(db, cole, POTION)
    monkeypatch.setattr(ddb_bridge, "WAIT_SECONDS", -1)
    assert player.get(f"/bridge/state/{cole.id}").json()["changes"][0]["state"] == "not_yet"


def test_a_change_made_on_d_and_d_beyond_itself_shows_as_seen(player, db, sheet):
    cole = char(db, "Cole")
    player.get(f"/bridge/state/{cole.id}")  # askdnd has seen 37
    sheet["removedHitPoints"] = 20
    st = player.post(f"/bridge/changed/{cole.id}").json()
    assert st["hp"]["current"] == 31 and st["log"][0]["state"] == "seen" and "hit points 37 → 31" in st["log"][0]["text"]


def test_only_the_player_drinks_and_never_in_production(player, dm, db, sheet, monkeypatch):
    cole = char(db, "Cole")
    assert dm.post(f"/bridge/drink/{cole.id}/{POTION}").status_code == 403
    assert player.post(f"/bridge/drink/{cole.id}/12345").status_code == 400  # not a potion Cole has
    assert player.get("/bridge/by-ddb/75423618").json()["character"]["id"] == cole.id
    assert "with D&amp;D Beyond" in player.get(f"/characters/{cole.id}/bridge").text
    monkeypatch.setattr(config, "IS_PRODUCTION", True)
    assert player.get(f"/bridge/state/{cole.id}").status_code == 404
    assert player.get(f"/characters/{cole.id}/bridge").status_code == 404
