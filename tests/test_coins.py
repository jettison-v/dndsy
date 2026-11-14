"""Coins carried and in bags (app/coins.py, app/inventory.py; feedback 51–53, Nov 7, docs/mockups/coins/: Brett chose A,
Spend · Gain · Move, and making change). Cole carries 654 gp, 68 sp, 92 cp and keeps 7,000 gp in his Bag of Holding."""

import json

import pytest
from sqlalchemy import select

from app import characters, coins, ddb_bridge, ddb_fields
from app.models import BridgeIntent, Campaign
from tests.table_setup import char

BAG = "340867412"  # Cole's Bag of Holding
POUCH = "482093051"  # his Component Pouch (no coins in it)


@pytest.fixture(autouse=True)
def test_campaign(db, sheet):
    """Live state comes with Sync with D&D Beyond (app/vtt.py), switched on for the campaign."""
    db.get(Campaign, char(db, "Cole").campaign_id).vtt_pieces = ["sync"]
    db.flush()


def changes(db):
    return [(i.kind, i.data) for i in db.scalars(select(BridgeIntent).order_by(BridgeIntent.id))]


def post(player, db, **form):
    return player.post(f"/characters/{char(db, 'Cole').id}/coins", data=form)


def test_the_places_are_carried_then_each_bag(db):
    every = coins.places(characters.character_summary(char(db, "Cole")))
    assert [p["name"] for p in every][:2] == ["Carried", "Bag of Holding"] and every[0]["key"] == "me"
    assert every[1]["coins"] == {"cp": 0, "sp": 0, "ep": 0, "gp": 7000, "pp": 0} and every[1]["has"]
    pouch = next(p for p in every if p["name"] == "Component Pouch")
    assert not pouch["has"] and pouch["key"] == POUCH


def test_the_window_asks_where_only_once_a_bag_holds_coins(player, db, sheet):
    cole = char(db, "Cole")
    w = player.get(f"/characters/{cole.id}/coins").text
    assert 'aria-pressed="true">Spend' in w and ">Gain<" in w and ">Move<" in w
    assert 'name="place" value="me" checked' in w and f'name="place" value="{BAG}"' in w  # (both hold coins)
    assert f'value="{POUCH}"' not in w  # (spending: only where there are coins)
    move = player.get(f"/characters/{cole.id}/coins?do=move").text
    assert 'name="from"' in move and f'<option value="{POUCH}"' in move and "Component Pouch (" not in move  # (to: any bag)
    next(i for i in sheet["inventory"] if str(i["id"]) == BAG)["currency"] = None
    characters.refresh(db, cole)
    w = player.get(f"/characters/{cole.id}/coins").text
    assert 'name="place"' not in w and "654 gp, 68 sp, 92 cp" in w  # (carried only: as it always was)


def test_spend_from_carried_and_undo(player, db):
    r = post(player, db, to="spend", coin="gp", amount="20").json()
    assert r["text"] == "Spent 20 gp" and changes(db) == [("coins", {"deltas": {"coin:gp": -20}, "said": "spent 20 gp"})]
    assert json.loads(r["undo"]["deltas"]) == {"coin:gp": 20}
    back = player.post(r["undoUrl"], data=r["undo"]).json()
    assert back["text"] == "Undone" and changes(db)[1] == ("coins", {"deltas": {"coin:gp": 20}, "said": "undone"})


def test_spending_a_coin_you_havent_got_makes_change(player, db):
    """Brett, Nov 7 (making change: yes, like buying): 2 pp from 654 gp pays 20 gp."""
    r = post(player, db, to="spend", coin="pp", amount="2").json()
    assert r["text"] == "Spent 2 pp: paid 20 gp"
    assert changes(db)[0][1]["deltas"] == {"coin:gp": -20}
    post(player, db, to="spend", coin="ep", amount="1")  # 1 ep (5 sp) from 68 sp
    assert changes(db)[1][1]["deltas"] == {"coin:sp": -5}
    r = post(player, db, place=BAG, to="spend", coin="sp", amount="5").json()  # the bag has only gold: a coin broken
    assert changes(db)[2][1]["deltas"] == {f"bagcoin:{BAG}:gp": -1, f"bagcoin:{BAG}:sp": 5}
    assert r["text"] == "Spent 5 sp from Bag of Holding: paid 1 gp, 5 sp back"


def test_not_enough_even_making_change(player, db):
    r = post(player, db, place=BAG, to="spend", coin="pp", amount="701")
    assert r.status_code == 409 and r.json()["detail"] == "Cole doesn't have 701 pp in Bag of Holding, even making change." and not changes(db)


def test_gain_into_a_bag(player, db):
    r = post(player, db, place=POUCH, to="gain", coin="sp", amount="12").json()
    assert r["text"] == "Gained 12 sp into Component Pouch" and changes(db) == [("coins", {"deltas": {f"bagcoin:{POUCH}:sp": 12}, "said": "gained 12 sp into Component Pouch"})]


def test_move_between_places_is_one_change(player, db):
    r = post(player, db, to="move", coin="gp", amount="500", **{"from": BAG, "into": "me"}).json()
    assert r["text"] == "Moved 500 gp from Bag of Holding to carried"
    assert changes(db) == [("coins", {"deltas": {f"bagcoin:{BAG}:gp": -500, "coin:gp": 500}, "said": "moved 500 gp from Bag of Holding to carried"})]


@pytest.mark.parametrize(("form", "said"), [
    ({"to": "move", "coin": "gp", "amount": "8000", "from": BAG, "into": "me"}, "Bag of Holding has 7,000 gp."),
    ({"to": "move", "coin": "gp", "amount": "1", "from": BAG, "into": BAG}, "Pick where the coins come from"),
    ({"to": "move", "coin": "gp", "amount": "1", "from": "999", "into": "me"}, "Pick where the coins come from"),
    ({"to": "spend", "coin": "gp", "amount": "1", "place": "758020983"}, "That bag isn't one of yours."),  # (his Torch)
    ({"to": "spend", "coin": "xx", "amount": "1"}, "Enter how many coins."),
    ({"to": "gain", "coin": "gp", "amount": "0"}, "Enter how many coins."),
    ({"to": "undo", "deltas": json.dumps({"bagcoin:999:gp": 5})}, "That can't be undone here."),
    ({"to": "undo", "deltas": json.dumps({"hp": 5})}, "That can't be undone here."),
    ({"to": "undo", "deltas": "not json"}, "That can't be undone here."),
])
def test_what_isnt_changed(player, db, form, said):
    r = post(player, db, **form)
    assert r.status_code == 409 and said in r.json()["detail"] and not changes(db)


def test_out_of_reach_the_window_says_so_and_offers_nothing(player, db):
    cole = char(db, "Cole")
    cole.sheet_heard_at = None
    db.flush()
    w = player.get(f"/characters/{cole.id}/coins").text
    assert 'class="unreached"' in w and "data-use-go" not in w and "Bag of Holding: 7,000 gp" in w


def test_a_bag_coin_is_written_naming_its_bag(db):
    """Tried on a test sheet, Nov 7: D&D Beyond's coin request with a destination sets that container's own total."""
    raw = ddb_bridge.numbers(char(db, "Cole"))["raw"]
    assert ddb_fields.value(raw, f"bagcoin:{BAG}:gp") == 7000 and ddb_fields.value(raw, f"bagcoin:{POUCH}:gp") == 0
    req = ddb_fields.write(75423618, f"bagcoin:{BAG}:gp", 6500, raw)
    assert req == {"method": "PUT", "path": "/character/v5/inventory/currency/gold",
                   "body": {"characterId": 75423618, "amount": 6500, "destinationEntityId": int(BAG), "destinationEntityTypeId": 1439493548}}
    assert ddb_fields.name(raw, f"bagcoin:{BAG}:gp") == "gold in Bag of Holding"
    ddb_fields.put(raw, f"bagcoin:{POUCH}:sp", 3)  # (a container that never held coins gets them all, at 0)
    assert ddb_fields.value(raw, f"bagcoin:{POUCH}:sp") == 3 and ddb_fields.value(raw, f"bagcoin:{POUCH}:gp") == 0


def test_a_move_is_made_whole_or_not_at_all(player, db, sheet):
    """A move takes coins out of one place only while it puts them into the other (one change, planned together): with
    the bag emptied on D&D Beyond meanwhile, neither side is written."""
    cole = char(db, "Cole")
    post(player, db, to="move", coin="gp", amount="500", **{"from": BAG, "into": "me"})
    n = ddb_bridge.numbers(cole)
    ddb_fields.put(n["raw"], f"bagcoin:{BAG}:gp", 100)
    n["fields"] = ddb_fields.tracked(n["raw"])
    target, _, impossible, _ = ddb_bridge.plan([{"kind": i.kind, "data": i.data} for i in db.scalars(select(BridgeIntent))], n)
    assert not target and impossible and "not enough" in impossible[0][1] and "gold in Bag of Holding 100" in impossible[0][1]


def test_the_purse_marks_a_bag_coin_on_its_way(player, db):
    cole = char(db, "Cole")
    post(player, db, to="move", coin="gp", amount="500", **{"from": BAG, "into": "me"})
    shown = ddb_bridge.as_shown(db, cole, characters.character_summary(cole))
    assert shown["sync"]["coin:gp"] == "on" and shown["currency"]["gp"] == 1154
    assert next(b for b in shown["bag_coins"] if b["id"] == BAG)["coins"] == {"gp": 6500}


def test_buying_pays_from_the_place_chosen(player, db, item_catalog):
    cole = char(db, "Cole")
    w = player.get(f"/characters/{cole.id}/items/browse").text
    assert f'<option value="{BAG}">Bag of Holding (7,000 gp)</option>' in w and 'data-ib-from' in w
    r = player.post(f"/characters/{cole.id}/items/add", json={"items": [{"id": 415, "n": 1}], "pay": "1 sp", "from": BAG})
    assert r.json()["text"] == "Cole got Rope, paid 1 sp from Bag of Holding: on its way to D&D Beyond"
    assert changes(db)[1] == ("coins", {"deltas": {f"bagcoin:{BAG}:gp": -1, f"bagcoin:{BAG}:sp": 9}, "said": "paid 1 sp from Bag of Holding"})
