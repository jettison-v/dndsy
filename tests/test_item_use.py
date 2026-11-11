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
    assert "Items" in page and "All items (2)" in page and "/use/" not in page  # no item pinned yet (Cast shows: Sync is on)
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


def _plan_of(page: str, label: str, cls: str = "") -> str | None:
    """The data-plan of the roll button labelled `label` (with `cls` among its classes) on a page."""
    import re

    for tag in re.findall(r"<button\b[^>]*>", page):
        if f'data-label="{label}"' in tag and (not cls or cls in tag):
            m = re.search(r'data-plan="([^"]*)"', tag)
            return m.group(1) if m else None
    return None


def test_using_an_item_rolls_the_plan_its_button_carries(player, db, sheet, monkeypatch):
    """Brett, Nov 10 ("a Roll engine: changes are universal and mostly made with data"): the Use window has no dice of
    its own. A Soul Coin's Use and roll opens the roll card on the very button its Roll is (the same plan), and a
    potion's Drink rolls the dice its Heal button's plan says, so a change to the item's recipe changes both."""
    import html
    import json

    from app import roll_recipes as rr

    cole, pid = hurt(db, sheet)
    coin = next(i["id"] for i in sheet["inventory"] if i["definition"]["name"] == "Soul Coin")
    w = player.get(f"/characters/{cole.id}/use/{coin}").text
    assert "Use and roll" in w
    o = next(o for o in views.options(characters.character_summary(cole), set()) if o["name"] == "Soul Coin")
    chip = next(r["attrs"] for r in views.option_rolls(o) if r["button"] == "chip")  # (its Roll where the bridge is off)
    assert html.unescape(_plan_of(w, "Soul Coin", "use-roll")) == chip["plan"]

    w = player.get(f"/characters/{cole.id}/use/{pid}").text
    assert ">Drink<" in w and "and roll" not in w and "2d4+2" in w
    real = rr.recipes()
    items = {**real["items"], "Potion of Healing": {**real["items"]["Potion of Healing"], "events": [{"name": "Healing", "on": "heal", "parts": ["4d4+4"]}]}}
    monkeypatch.setattr(rr, "recipes", lambda: {**real, "items": items})
    assert "4d4+4" in player.get(f"/characters/{cole.id}/use/{pid}").text
    j = player.post(f"/characters/{cole.id}/use/{pid}").json()
    assert db.get(TableRoll, j["roll"]["id"]).formula == "4d4+4"
    o = next(o for o in views.options(characters.character_summary(cole), set()) if o["name"] == "Potion of Healing")
    chip = next(r["attrs"] for r in views.option_rolls(o) if r["button"] == "chip")
    assert json.loads(chip["plan"])["rolls"]["effects"][0]["at"]["0"]["parts"] == ["4d4+4"]  # (and its Heal button)


def test_every_usable_item_on_the_partys_sheets_rolls_its_plan():
    """Every item with a Use window on the party's saved sheets: one with a roll in its plan offers it (a potion rolls
    as it's drunk; anything else is Use and roll), and its dice are the plan's at the plan's own level. Using a Hat of
    Wizardry is an Arcana check, Dust of Sneezing and Choking your own Con save, a Hammer of Thunderbolts its own attack
    thrown with Thunderclap's save on a hit, and a Necklace of Prayer Beads asks which bead and plays its spell's plan
    (Brett, Nov 10: what's left to fully complete rolls)."""
    import json
    from pathlib import Path

    from app import ddb
    from app.item_use import _drinks

    seen = {}
    for name in ("big_c", "cole", "no_name", "trah"):
        raw = json.loads((Path(__file__).parent / "fixtures" / "ddb" / f"{name}.json").read_text())["data"]
        s = ddb.parse_character(ddb.sanitize(raw))
        for o in views.options(s, set()):
            if not o.get("use") or not (r := views.item_roll(o, s)):
                continue
            if r["kind"] == "beads":  # (a Necklace of Prayer Beads: each bead's spell its own plan, at the bead's level)
                seen[o["name"]] = {b["name"]: json.loads(b["attrs"]["plan"])["rolls"]["effects"][0]["at"][str(b["level"])]["parts"] if b["attrs"] else None for b in r["beads"]}
                continue
            plan = json.loads(r["attrs"]["plan"])
            if plan.get("rolls"):
                at = plan["rolls"]["effects"][0]["at"][str(plan["rolls"]["base"])]
                assert r["formula"] == "+".join(p.split(" ")[0] for p in at["parts"]), (name, o["name"])
            assert bool(_drinks(o)) == (o["use"]["gives"] and r["kind"] == "heal"), (name, o["name"])
            seen[o["name"]] = (plan["play"], plan.get("bonus"), [x["name"] for x in plan.get("riders") or []])
    # (what using these rolls is the recipe's `use`; the numbers are the sheet's)
    assert seen["Hat of Wizardry"] == ("d20", 7, []) and seen["Dust of Sneezing and Choking"][:2] == ("d20", 2)
    assert seen["Hammer of Thunderbolts (Maul)"][0] == "attack" and "Thunderclap" in seen["Hammer of Thunderbolts (Maul)"][2]
    beads = seen["Necklace of Prayer Beads"]  # (2024 DMG: Cure Wounds at level 2, Shining Smite; the rest roll nothing)
    assert beads["Bead of Curing"][0] == "4d8" and beads["Bead of Smiting"] == ["2d6 radiant"] and beads["Bead of Blessing"] is None


def test_a_necklace_of_prayer_beads_asks_which_bead_and_rolls_its_spell(player, db, sheet):
    """The Necklace's window (Nov 10): which bead (the DM sets them), and a bead whose spell rolls (Curing, Smiting)
    rolls that spell's plan at the bead's level once used; one use is spent whichever bead."""
    import json
    from pathlib import Path

    sheet.clear()
    sheet.update(json.loads((Path(__file__).parent / "fixtures" / "ddb" / "big_c.json").read_text())["data"])
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    db.commit()
    neck = next(i["id"] for i in sheet["inventory"] if i["definition"]["name"] == "Necklace of Prayer Beads")
    w = player.get(f"/characters/{cole.id}/use/{neck}").text
    assert 'name="bead"' in w and w.count("<option") == 6 and "Bead of Curing: Cure Wounds (level 2)" in w
    assert 'data-bead="1"' in w and 'data-bead="3"' in w and 'data-bead="0"' not in w and 'data-cast-level="2"' in w
    assert 'data-verb="Use">Use<' in w  # (the first bead, Blessing, rolls nothing)
    j = player.post(f"/characters/{cole.id}/use/{neck}", data={"bead": "1"}).json()
    assert "Bead of Curing, Cure Wounds" in j["text"] and j["undo"]["spent"]


def test_the_dmgs_magic_items_roll_from_the_rules_book():
    """Brett, Nov 10 ("all of the book"): a magic weapon's extra damage is a pill for attacks with that weapon only
    (Flame Tongue's 2d6 Fire, not the dagger's); a wand casts its spell at its own DC and charges (Wand of Fireballs,
    DC 15, 1 to 3 charges for levels 3 to 5); an item's own save says its DC (Bead of Force, Dex 15)."""
    import json
    from pathlib import Path

    from app import ddb, roll_plan, rules_book
    from app import roll_recipes as rr

    raw = json.loads((Path(__file__).parent / "fixtures" / "ddb" / "big_c.json").read_text())["data"]
    s = ddb.parse_character(ddb.sanitize(raw))
    s["inventory"] = [*s["inventory"], {"key": "item:1", "name": "Flame Tongue Longsword", "base_name": "Longsword", "equipped": True}]
    flame = next(a for a in rules_book.adds(s) if a["name"] == "Flame Tongue")
    assert flame["amount"] == "2d6 fire" and flame["item"] == "Flame Tongue" and flame["pressed"] is False
    assert roll_plan.applies(flame, {"weapon", "item:flame tongue longsword"}) and not roll_plan.applies(flame, {"weapon", "item:dagger"})
    wand = {"name": "Wand of Fireballs", "recipe": rr.item("Wand of Fireballs"), "use": {"gives": False}}
    r = views.item_roll(wand, s)
    plans = [json.loads(b["attrs"]["plan"]) for b in r["beads"]]
    assert r["ask"] == "Which spell" and [b["charges"] for b in r["beads"]] == [1, 2, 3] and [b["level"] for b in r["beads"]] == [3, 4, 5]
    assert all((p["play"], p["save"]["ability"], p["save"]["dc"]) == ("save", "Dex", 15) for p in plans) and plans[2]["rolls"]["effects"][0]["at"]["5"]["parts"][0].startswith("10d6")
    bead = {"name": "Bead of Force", "kind": "item", "recipe": rr.item("Bead of Force"), "use": {"gives": False}, "meta": ""}
    views.rollable(bead)
    assert roll_plan.plan(s, {**bead, "hit": "Dex 15"})["save"] == {"ability": "Dex", "dc": 15, "success": "none"}
