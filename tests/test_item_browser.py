"""The item browser (app/item_browser.py): D&D Beyond's 2024 items, Add item for a character's own player (paying from
the purse if they choose) and Give loot for its DM, through the bridge."""

import json
import os

import pytest
from sqlalchemy import select

from app import characters, giving, item_browser
from app.models import BridgeIntent, Campaign
from tests.roles import set_role
from tests.table_setup import char

BAG = 340867412  # Cole's Bag of Holding (the inventory row: its containerEntityId)


ITEMS = json.load(open(os.path.join(os.path.dirname(__file__), "fixtures", "ddb", "items.json")))["data"]
"""Made up, in the shape of D&D Beyond's game-data list: Rope 415 and Torch 437 (PHB, priced), Longsword (the Free Rules),
Potion of Healing and Cloak of Protection (DMG, magic, one picture from D&D Beyond and one from elsewhere), and three
never listed: the 2014 Rope (legacy), a homebrew item and a 2014-only one."""


@pytest.fixture(autouse=True)
def bridge_on(db, sheet, monkeypatch):
    """Live state comes with Sync with D&D Beyond (app/vtt.py), switched on for the campaign; D&D Beyond's list is ITEMS."""
    db.get(Campaign, char(db, "Cole").campaign_id).vtt_pieces = ["sync"]
    db.flush()
    monkeypatch.setattr(giving, "_catalog", {"at": 0.0, "tried": 0.0, "items": []})
    monkeypatch.setattr(giving.ddb, "_get_json", lambda url, timeout: {"data": ITEMS})


def intents(db):
    return [(i.kind, i.data, i.label) for i in db.scalars(select(BridgeIntent).order_by(BridgeIntent.id))]


def test_the_list_is_the_2024_books_with_the_free_rules_and_book_prices_only():
    by = {i["name"]: i for i in giving.catalog()}
    assert sorted(by) == ["Cloak of Protection", "Longsword", "Potion of Healing", "Rope", "Torch"]
    assert by["Rope"]["id"] == 415 and by["Rope"]["cost_cp"] == 100 and by["Torch"]["cost_cp"] == 1
    sword = {"book": "Free Rules (2024)", "kind": "Weapons", "damage": "1d8 Slashing", "properties": ["Versatile (1d10)"], "cost_cp": 1500}
    assert {k: by["Longsword"][k] for k in sword} == sword
    potion, cloak = by["Potion of Healing"], by["Cloak of Protection"]
    assert potion["cost_cp"] is None and potion["rarity"] == "Common" and potion["book"] == "Dungeon Master's Guide (2024)"
    assert potion["picture"] == "https://www.dndbeyond.com/avatars/potion.jpg" and cloak["picture"] == ""  # (only D&D Beyond's own pictures)
    assert cloak["attune"] and by["Rope"]["rarity"] == "Not magic"


def test_coins_are_counted_out_largest_first_and_a_coin_is_broken_for_change():
    assert item_browser.parse_money("2 gp 5 sp") == 250 and item_browser.parse_money("21 sp") == 210
    assert item_browser.parse_money("2.5 GP") == 250 and item_browser.parse_money("3") == 300 and item_browser.parse_money("") == 0
    assert item_browser.parse_money("a goat") is None and item_browser.parse_money("2 gp and a goat") is None
    assert item_browser.pay_from({"gp": 654, "sp": 68, "cp": 92}, 250) == {"cp": 92, "sp": 63, "ep": 0, "gp": 652, "pp": 0}
    assert item_browser.pay_from({"gp": 1}, 10) == {"cp": 0, "sp": 9, "ep": 0, "gp": 0, "pp": 0}
    assert item_browser.pay_from({"gp": 5, "cp": 3}, 25) == {"cp": 8, "sp": 7, "ep": 0, "gp": 4, "pp": 0}
    assert item_browser.pay_from({"pp": 1}, 150) == {"cp": 0, "sp": 5, "ep": 0, "gp": 8, "pp": 0}
    assert item_browser.pay_from({"gp": 1}, 101) is None
    assert item_browser.money(1500) == "15 gp" and item_browser.money(251) == "2 gp 5 sp 1 cp"


def test_a_player_adds_items_into_a_bag_and_pays_what_they_typed(player, db):
    cole = char(db, "Cole")
    w = player.get(f"/characters/{cole.id}/items/browse").text
    assert ">Add item</h2>" in w and 'data-label="Longsword"' in w and "15 gp" in w and 'data-label="Sword of Made-Up Things"' not in w
    assert f'<option value="{BAG}">Bag of Holding</option>' in w and "data-ib-paying" in w and "654" in w  # (bags, the purse)
    assert "you have 1" in w  # (his Rope)
    r = player.post(f"/characters/{cole.id}/items/add", json={"items": [{"id": 415, "n": 2}, {"id": 8960641, "n": 1}], "into": str(BAG), "pay": "2 gp 5 sp"})
    assert r.json()["text"] == "Cole got Rope ×2, Potion of Healing into Bag of Holding, paid 2 gp 5 sp: on its way to D&D Beyond"
    rope, potion, sp, gp = intents(db)
    assert rope == ("add_item", {"definition": 415, "entityTypeId": 1439493548, "quantity": 2, "name": "Rope", "container": BAG}, "Cole got Rope ×2")
    assert potion[1]["definition"] == 8960641 and potion[1]["container"] == BAG
    assert (gp[1]["field"], gp[1]["delta"], sp[1]["field"], sp[1]["delta"]) == ("coin:gp", -2, "coin:sp", -5) and gp[2] == "Cole paid 2 gp 5 sp"


def test_carried_and_unpaid_is_just_the_items(player, db):
    cole = char(db, "Cole")
    r = player.post(f"/characters/{cole.id}/items/add", json={"items": [{"id": 437, "n": 10}]})
    assert r.json()["text"] == "Cole got Torch ×10: on its way to D&D Beyond"
    (kind, data, _), = intents(db)
    assert kind == "add_item" and "container" not in data  # (D&D Beyond's own default: carried)


@pytest.mark.parametrize(("body", "said"), [
    ({"items": [{"id": 415, "n": 1}], "pay": "700 gp"}, "Cole doesn't have 700 gp."),
    ({"items": [{"id": 415, "n": 1}], "pay": "a goat"}, "Write what you pay as coins"),
    ({"items": [{"id": 9004, "n": 1}]}, "Pick items from the list"),  # (a homebrew item isn't in it)
    ({"items": [{"id": 415, "n": 0}]}, "Pick items from the list"),
    ({"items": [{"id": 415, "n": 1}], "into": "758020983"}, "That bag isn't one of yours."),  # (his Torch)
    ({"items": []}, "Add something first"),
    ({"items": "Rope"}, "isn't an item"),
])
def test_what_isnt_added(player, db, body, said):
    r = player.post(f"/characters/{char(db, 'Cole').id}/items/add", json=body)
    assert r.status_code == 409 and said in r.json()["detail"] and not intents(db)


def test_the_dm_gives_loot_with_coins_and_never_pays(dm, db):
    cole = char(db, "Cole")
    set_role(db, "dm@example.com", "dm")
    w = dm.get(f"/characters/{cole.id}/items/browse").text
    assert ">Give loot to Cole</h2>" in w and "data-ib-amount" in w and "data-ib-paying" not in w
    r = dm.post(f"/characters/{cole.id}/items/add", json={"items": [{"id": 8960641, "n": 2}], "pay": "50 gp", "amount": "50", "coin": "gp"})
    assert r.json()["text"] == "Potion of Healing ×2 and 50 gp to Cole: on its way to D&D Beyond"
    item, coins = intents(db)
    assert item[2] == "Cole got Potion of Healing ×2 from the DM" and (coins[1]["field"], coins[1]["delta"]) == ("coin:gp", 50)
    assert "Give loot" in dm.get(f"/characters/{cole.id}").text
    assert "Give loot" in dm.get(f"/characters/{cole.id}/brief").text  # Party's window too (feedback 6)


def test_an_item_shows_what_it_is_and_a_magic_one_has_no_price(player, dm, db):
    cole = char(db, "Cole")
    potion = player.get(f"/characters/{cole.id}/items/browse/8960641").text
    assert "Ask the DM" in potion and 'src="https://www.dndbeyond.com/avatars/potion.jpg"' in potion and "as the book says" in potion
    assert "Dungeon Master&#39;s Guide (2024)" in potion
    assert "15 gp" in player.get(f"/characters/{cole.id}/items/browse/9001").text
    assert "<img" not in player.get(f"/characters/{cole.id}/items/browse/9002").text
    set_role(db, "dm@example.com", "dm")
    assert "<dt>Cost</dt>" not in dm.get(f"/characters/{cole.id}/items/browse/8960641").text  # (loot costs nothing)
    assert player.get(f"/characters/{cole.id}/items/browse/9004").status_code == 404


def test_only_a_characters_player_and_dm_open_it(player, db):
    """Another player's character is theirs: no browser for it."""
    trah = char(db, "Trah")
    characters.refresh(db, trah)
    assert player.get(f"/characters/{trah.id}/items/browse").status_code == 404
    assert player.post(f"/characters/{trah.id}/items/add", json={"items": [{"id": 415, "n": 1}]}).status_code == 404 and not intents(db)
    assert "+ Add item" in player.get(f"/characters/{char(db, 'Cole').id}").text


def test_without_the_bridge_there_is_no_browser(player, db):
    cole = char(db, "Cole")
    db.get(Campaign, cole.campaign_id).vtt_pieces = []
    db.flush()
    assert player.get(f"/characters/{cole.id}/items/browse").status_code == 404
    assert "+ Add item" not in player.get(f"/characters/{cole.id}").text
