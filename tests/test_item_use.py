"""Using an item in play (app/item_use.py; Brett, 2026-10-30, docs/mockups/potions-and-charges.html): an Items section in
each column that follows pinning, a window like a roll, and what one use changes on D&D Beyond through the bridge."""

from sqlalchemy import select

from app import character_views as views
from app import characters, ddb_bridge, picks
from app import conditions as cond
from app.models import BridgeIntent, Character, TableRoll
from tests.table_setup import char


def item(name="Trinket", kind="Wondrous item", charges=None, count=1, text=""):
    return {"name": name, "base_name": name, "type": kind, "charges": charges, "count": count, "quantity": count or 1, "summary": "", "text": text}


def charges(left, most, reset="Used up"):
    return {"left": left, "max": most, "used": most - left, "reset": reset, "reset_note": "", "reset_phrase": "gone once used"}


def test_what_an_item_costs_comes_from_the_rules_or_its_own_text():
    """Every potion is a Bonus Action (2024 DMG, Using a Potion); an item that doesn't say isn't guessed."""
    assert cond.item_cost(item("Potion of Growth", "Potion")) == ("Bonus action", "Bonus Action")
    assert cond.item_cost(item(text="As a Magic action, you can do something.")) == ("Action", "Magic action")
    assert cond.item_cost(item(text="You can take a Utilize action to break it.")) == ("Action", "Utilize action")
    assert cond.item_cost(item(text="As a bonus action, you can do something.")) == ("Bonus action", "Bonus Action")
    assert cond.item_cost(item("Scroll of Daylight", "Scroll")) == ("Action", "Action")
    assert cond.item_cost(item()) == ("Action", "")
    assert cond.item_cost(item(text="A creature can use its action to spend a charge.")) == ("Action", "Action")  # older wording
    assert cond.item_cost(item(text="You can use an action to touch it to the ground.")) == ("Action", "Action")
    assert cond.item_cost(item(text="Each has a spell you can cast from it as a bonus action.")) == ("Bonus action", "Bonus Action")
    assert cond.item_cost(item(text="When you would drop to 0, you drop to 1 instead.")) == ("Action", "")  # it doesn't say: not guessed


def test_item_costs_are_for_every_table_never_one_partys_copies():
    """A standing rule (Brett, 2026-10-30: "I don't want the UI to change in a way that isn't universal"): an item's cost
    comes from the rules or its own words, so no named item carries a cost of its own."""
    import json

    from app.conditions import DATA

    assert not [k for k, v in json.loads(DATA.read_text()).items() if isinstance(v, dict) and "cost" in v]


def test_counting_a_potion_the_two_ways_d_and_d_beyond_keeps_it():
    pip = charges(1, 1)
    assert cond.item_left(item(charges=pip, count=2)) == 2 and cond.item_spends(item(charges=pip, count=2)) == "item"
    assert cond.item_left(item(charges=charges(0, 1), count=1)) == 0
    assert cond.item_spends(item(charges=pip, count=1)) == "charges"  # the last: its mark, as D&D Beyond does
    assert cond.item_left(item(count=2)) == 2 and cond.item_spends(item(count=1)) == "item"
    assert cond.item_left(item(count=0)) == 0
    coin = item(charges=charges(2, 3))
    assert cond.item_left(coin) == 2 and cond.item_spends(coin) == "charges"
    hat = item(charges=charges(0, 1, "LongRest"))
    assert cond.item_left(hat) == 0 and cond.item_spends(hat) == "charges"


def test_charges_coming_back_are_not_healing():
    o = views.rollable({"name": "Hammer", "kind": "item", "use": {"verb": "Use"}, "meta": "It regains 1d4 + 1 expended charges daily at dawn.",
                        "text": "It regains 1d4 + 1 expended charges daily at dawn."})
    assert not o["heal"] and not o["dice"]


def potion(sheet) -> int:
    return next(i["id"] for i in sheet["inventory"] if i["definition"]["name"] == "Potion of Healing")


def row(sheet, item_id):
    return next(i for i in sheet["inventory"] if i["id"] == item_id)


def intents(db, cole):
    return [(i.kind, i.data) for i in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == cole.id).order_by(BridgeIntent.id))]


def made(db, cole):
    rows = db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == cole.id).order_by(BridgeIntent.id))
    return ddb_bridge.plan([{"kind": it.kind, "data": it.data} for it in rows], ddb_bridge.numbers(cole))[0]


def hurt(db, sheet, removed=20, count=2):
    """Cole with some damage and a stack of potions."""
    sheet["removedHitPoints"] = removed
    pid = potion(sheet)
    row(sheet, pid)["quantity"] = count
    row(sheet, pid)["limitedUse"] = None
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    db.commit()
    return cole, pid


def test_items_follow_pinning_and_the_rest_are_in_the_side_panel(player, db, sheet):
    """Brett, 2026-10-30: their own section, under the rules of pinning, so the list doesn't grow too long."""
    cole, pid = hurt(db, sheet)
    bonus = lambda page: page.split('data-econ-col="bonus"')[1].split('data-econ-col="reaction"')[0]  # noqa: E731
    page = bonus(player.get(f"/characters/{cole.id}/battle").text)
    assert "Items" in page and "All items (2)" in page and "data-use-url" not in page  # (with the ring's Become visible)
    picks.toggle(db, cole, "star", f"item:{pid}", "Potion of Healing")
    db.commit()
    page = bonus(player.get(f"/characters/{cole.id}/battle").text)
    assert f'data-use-url="/characters/{cole.id}/use/{pid}"' in page and ">Drink<" in page and "×2" in page
    panel = player.get(f"/characters/{cole.id}/all/bonus?items=1").text
    assert "Potion of Healing" in panel and "data-use-url" in panel


def test_drink_rolls_for_the_table_spends_the_potion_and_heals_you(player, db, sheet):
    cole, pid = hurt(db, sheet)
    assert ">Drink<" in player.get(f"/characters/{cole.id}/use/{pid}").text
    r = player.post(f"/characters/{cole.id}/use/{pid}")
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["roll"]["label"] == "Potion of Healing" and j["undo"]["spent"] == "item" and "Drank Potion of Healing" in j["text"]
    end = made(db, cole)
    assert end[f"item:{pid}"] == 1 and end["hp"]["removedHitPoints"] == 20 - j["undo"]["heal"]
    root = db.get(TableRoll, j["undo"]["roll"])
    assert root.visibility == "table" and root.kind == "heal"
    assert [k.kind for k in db.scalars(select(TableRoll).where(TableRoll.parent_id == root.id))] == ["applied"]

    r = player.post(j["undoUrl"], data=j["undo"])
    assert r.status_code == 200
    assert not made(db, cole)  # a change and its undo: nothing left to make
    assert db.scalars(select(TableRoll).where(TableRoll.parent_id == root.id)).one().label.startswith("Undone")


def test_taking_a_heal_back_leaves_temporary_hit_points_alone(player, db, sheet):
    sheet["temporaryHitPoints"] = 5
    cole, pid = hurt(db, sheet)
    j = player.post(f"/characters/{cole.id}/use/{pid}").json()
    player.post(j["undoUrl"], data=j["undo"])
    assert not made(db, cole)


def test_give_spends_yours_and_leaves_apply_to_on_the_roll(player, db, sheet):
    cole, pid = hurt(db, sheet)
    r = player.post(f"/characters/{cole.id}/use/{pid}", data={"to": "Trah"}).json()
    assert r["roll"]["label"] == "Potion of Healing for Trah" and "for Trah to apply" in r["text"]
    end = made(db, cole)
    assert end[f"item:{pid}"] == 1 and "hp" not in end  # Cole's hit points don't move
    assert not db.scalars(select(TableRoll).where(TableRoll.kind == "applied")).all()


def test_drinking_at_0_ends_unconscious_and_has_no_undo(player, db, sheet):
    from app import death_saves

    sheet["conditions"] = [{"id": 15, "level": None}]
    cole, pid = hurt(db, sheet, removed=51)
    j = player.post(f"/characters/{cole.id}/use/{pid}").json()
    assert j["undo"] is None and "back up from 0" in j["text"]
    assert made(db, cole)[death_saves.UNCONSCIOUS] is False


def test_the_last_of_a_stack_with_a_mark_takes_the_mark_and_charges_count_down(player, db, sheet):
    cole, pid = hurt(db, sheet, count=1)
    row(sheet, pid)["limitedUse"] = {"maxUses": 1, "resetType": "Consumable", "numberUsed": 0, "resetTypeDescription": ""}
    characters.refresh(db, cole)
    db.commit()
    assert player.post(f"/characters/{cole.id}/use/{pid}").status_code == 200
    assert made(db, cole)[f"charges:{pid}"] == 1
    assert intents(db, cole)[0][0] == "use"
    r = player.post(f"/characters/{cole.id}/use/{pid}")
    assert r.status_code == 404  # used, on its way: off Battle


def test_an_effect_starts_when_its_used_and_undo_ends_it(player, db, sheet):
    cole, pid = hurt(db, sheet)
    row(sheet, pid)["definition"] = {**row(sheet, pid)["definition"], "name": "Potion of Water Breathing", "description": "<p>You can breathe underwater.</p>"}
    characters.refresh(db, cole)
    db.commit()
    j = player.post(f"/characters/{cole.id}/use/{pid}").json()
    assert "Water Breathing" in j["text"] and "roll" not in j
    assert [c["name"] for c in db.get(Character, cole.id).conditions] == ["Water Breathing"]
    player.post(j["undoUrl"], data=j["undo"])
    db.expire_all()
    assert not db.get(Character, cole.id).conditions


def test_only_while_the_sheet_can_be_reached(player, db, sheet):
    cole, pid = hurt(db, sheet)
    cole.sheet_heard_at = None
    db.commit()
    assert "can't be reached" in player.get(f"/characters/{cole.id}/use/{pid}").text
    assert player.post(f"/characters/{cole.id}/use/{pid}").status_code == 409
    assert not intents(db, cole)


def test_only_the_characters_player_uses_it(dm, db, sheet):
    cole, pid = hurt(db, sheet)
    assert dm.post(f"/characters/{cole.id}/use/{pid}").status_code == 404
    assert not intents(db, cole)
