"""Inventory in play (app/inventory.py, app/resources.py): equip, attune, counts and coins, through the bridge."""

import pytest
from sqlalchemy import select

from app import characters
from app.models import BridgeIntent, Campaign
from tests.table_setup import char


@pytest.fixture(autouse=True)
def test_campaign(db, sheet):
    """Live state comes with Sync with D&D Beyond (app/vtt.py), switched on for the campaign."""
    db.get(Campaign, char(db, "Cole").campaign_id).vtt_pieces = ["sync"]
    db.flush()


def item(cole, **want):
    inv = characters.character_summary(cole)["inventory"]
    return next(i for i in inv if i["key"].startswith("item:") and all(i.get(k) == v for k, v in want.items()))


def iid(it):
    return it["key"].split(":", 1)[1]


def test_equip_goes_to_d_and_d_beyond(player, db, sheet):
    cole = char(db, "Cole")
    it = item(cole, equipped=True)
    r = player.post(f"/characters/{cole.id}/items/{iid(it)}/equip", data={"on": ""})
    assert r.status_code == 204 and "bridgeDeliver" in r.headers["HX-Trigger"]
    change = db.scalar(select(BridgeIntent))
    assert change.kind == "set" and change.data == {"field": f"equipped:{iid(it)}", "value": False}


def test_coins_spend_gain_and_undo(player, db, sheet):
    cole = char(db, "Cole")
    sheet["currencies"] = {"gp": 50}
    characters.refresh(db, cole)
    assert "50 gp" in player.get(f"/characters/{cole.id}/coins").text
    r = player.post(f"/characters/{cole.id}/coins", data={"to": "spend", "coin": "gp", "amount": "20"}).json()
    assert r["text"] == "Spent 20 gp" and db.scalar(select(BridgeIntent)).data["delta"] == -20
    assert player.post(r["undoUrl"], data=r["undo"]).json()["text"] == "Gained 20 gp"


def test_you_cant_spend_what_you_havent_got(player, db, sheet):
    cole = char(db, "Cole")
    sheet["currencies"] = {"gp": 5}
    characters.refresh(db, cole)
    r = player.post(f"/characters/{cole.id}/coins", data={"to": "spend", "coin": "gp", "amount": "6"})
    assert r.status_code == 409 and "doesn't have 6 gp" in r.json()["detail"]
    assert player.post(f"/characters/{cole.id}/coins", data={"to": "spend", "coin": "xx", "amount": "1"}).status_code == 409


def test_an_items_count_goes_down_as_its_used(player, db, sheet):
    cole = char(db, "Cole")
    inv = next(i for i in sheet["inventory"] if (i.get("quantity") or 0) > 1)
    r = player.post(f"/characters/{cole.id}/count?field=item:{inv['id']}", data={"to": "use"})
    assert r.status_code == 200, r.text
    change = db.scalar(select(BridgeIntent))
    assert change.kind == "item" and change.data["delta"] == -1


def test_only_the_player_and_only_where_sync_is_on(player, dm, db, sheet):
    cole = char(db, "Cole")
    it = item(cole, equipped=True)
    assert dm.post(f"/characters/{cole.id}/items/{iid(it)}/equip", data={"on": "1"}).status_code == 404
    db.get(Campaign, cole.campaign_id).vtt_pieces = []
    db.flush()
    assert player.post(f"/characters/{cole.id}/items/{iid(it)}/equip", data={"on": "1"}).status_code == 404
    assert player.get(f"/characters/{cole.id}/coins").status_code == 404


def test_move_an_item_to_another_bag_or_carried(player, db, sheet):
    """Brett, Nov 3 (parity with D&D Beyond): an item's panel has Move to, listing the character's bags and Carried; a
    bag itself isn't moved, and only into a bag the character has."""
    cole = char(db, "Cole")
    bag = next(i for i in sheet["inventory"] if (i.get("definition") or {}).get("isContainer"))
    thing = next(i for i in sheet["inventory"] if not (i.get("definition") or {}).get("isContainer") and i["containerEntityId"] == sheet["id"])
    panel = player.get(f"/characters/{cole.id}/detail", params={"ref": f"item:{thing['id']}"}).text
    assert f'hx-post="/characters/{cole.id}/items/{thing["id"]}/move"' in panel and f'<option value="{bag["id"]}">' in panel
    r = player.post(f"/characters/{cole.id}/items/{thing['id']}/move", data={"to": str(bag["id"])})
    assert r.status_code == 204, r.text
    assert db.scalar(select(BridgeIntent)).data == {"field": f"container:{thing['id']}", "value": bag["id"]}
    assert player.post(f"/characters/{cole.id}/items/{thing['id']}/move", data={"to": "me"}).status_code == 204
    assert player.post(f"/characters/{cole.id}/items/{thing['id']}/move", data={"to": str(thing["id"])}).status_code == 404
    assert player.post(f"/characters/{cole.id}/items/{bag['id']}/move", data={"to": "me"}).status_code == 404
