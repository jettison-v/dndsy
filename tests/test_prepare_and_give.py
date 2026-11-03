"""Changing prepared spells (app/preparing.py) and handing items over (app/giving.py), through the bridge."""

import pytest
from sqlalchemy import select

from app import characters, ddb_bridge, ddb_fields, giving
from app.models import BridgeIntent, Campaign
from tests.roles import set_role
from tests.table_setup import char

DRUID = 184968818  # Cole's Druid on his D&D Beyond sheet (the class's row, not the class)


@pytest.fixture(autouse=True)
def test_campaign(db, sheet):
    """Live state comes with Sync with D&D Beyond (app/vtt.py), switched on for the campaign."""
    db.get(Campaign, char(db, "Cole").campaign_id).vtt_pieces = ["sync"]
    db.flush()


def intents(db):
    return list(db.scalars(select(BridgeIntent).order_by(BridgeIntent.id)))


def ops(db, ch):
    return ddb_bridge.outbox(db, ch)["ops"]


# ------------------------------------------------------------------ prepared spells


def test_unpreparing_a_spell_sends_what_d_and_d_beyonds_sheet_sends(player, db, sheet):
    cole = char(db, "Cole")
    w = player.get(f"/characters/{cole.id}/prepare?key=spell:Healing Word")
    assert w.status_code == 200 and "10 of 10 prepared" in w.text and "Unprepare" in w.text
    r = player.post(f"/characters/{cole.id}/prepare?key=spell:Healing Word", data={"to": "unprepare"}).json()
    assert r["text"] == "Cole: Healing Word unprepared"
    op, = ops(db, cole)
    assert (op["method"], op["path"]) == ("PUT", "/character/v5/spell/prepared")
    assert op["body"] == {"characterId": 75423618, "spellId": 2619143, "characterClassId": DRUID, "entityTypeId": 435869154, "id": 21172492, "prepared": False}
    assert (op["from"], op["to"]) == (True, False)


def test_preparing_one_from_the_class_list_names_its_ids_and_says_when_its_over(player, db, sheet):
    """A spell D&D Beyond doesn't have on the sheet yet: its ids come from the class's list askdnd reads."""
    cole = char(db, "Cole")
    aid = next(s for s in sheet["askdnd"]["availableSpells"]["2190878"] if s["definition"]["name"] == "Aid")
    aid.update(id=21170801, entityTypeId=435869154)
    characters.refresh(db, cole)
    w = player.get(f"/characters/{cole.id}/prepare?key=spell:Aid").text
    assert "makes 11, more than the 10 a Druid prepares" in w and "the DM's call" in w  # said, never stopped
    r = player.post(f"/characters/{cole.id}/prepare?key=spell:Aid", data={"to": "prepare"}).json()
    op, = ops(db, cole)
    assert op["body"]["id"] == 21170801 and op["body"]["spellId"] == aid["definition"]["id"] and op["body"]["prepared"] is True
    assert (op["from"], op["to"]) == (False, True)
    assert player.post(r["undoUrl"], data=r["undo"]).status_code == 200  # Undo: askdnd shows it prepared at once, so it can be undone at once
    assert [i.data["value"] for i in intents(db)] == [True, False]


def test_a_cantrip_and_an_always_prepared_spell_have_no_prepare(player, db, sheet):
    cole = char(db, "Cole")
    assert player.get(f"/characters/{cole.id}/prepare?key=spell:Mending").status_code == 404
    panel = player.get(f"/characters/{cole.id}/detail?ref=spell:Healing Word").text
    assert "/prepare?key=spell%3AHealing%20Word" in panel


def test_a_prepared_spell_on_its_way_shows_as_prepared():
    """While it's on its way, the sheet askdnd shows has it (ddb_bridge.as_shown builds on ddb_fields.put)."""
    data = {"classSpells": [{"characterClassId": 7, "spells": []}],
            "askdnd": {"availableSpells": {"1": [{"id": 55, "definition": {"id": 9, "name": "Aid", "level": 2}}]}}}
    f = "prep:7:55"
    assert ddb_fields.value(data, f) is False and ddb_fields.name(data, f) == "Aid"
    ddb_fields.put(data, f, True)
    assert ddb_fields.value(data, f) is True
    ddb_fields.put(data, f, False)
    assert ddb_fields.value(data, f) is False


def test_preparing_is_the_players_and_only_where_sync_is_on(player, dm, db, sheet):
    cole = char(db, "Cole")
    assert dm.get(f"/characters/{cole.id}/prepare?key=spell:Healing Word").status_code == 404
    db.get(Campaign, cole.campaign_id).vtt_pieces = []
    db.flush()
    assert player.get(f"/characters/{cole.id}/prepare?key=spell:Healing Word").status_code == 404


# ------------------------------------------------------------------ giving items


def trah_too(db):
    trah = char(db, "Trah")
    characters.refresh(db, trah)  # (the fixture's D&D Beyond answers with Cole's sheet for anyone)
    return trah


def test_giving_part_of_a_stack_takes_it_off_one_sheet_and_adds_it_to_the_other(player, db, sheet):
    cole, trah = char(db, "Cole"), trah_too(db)
    w = player.get(f"/characters/{cole.id}/items/758022089/give").text
    assert "Give Potion of Healing" in w and "Cole has 2" in w and f'value="{trah.id}"' in w
    r = player.post(f"/characters/{cole.id}/items/758022089/give", data={"receiver": str(trah.id), "quantity": "1"})
    assert r.status_code == 200, r.text
    took, got = intents(db)
    assert (took.character_id, took.kind, took.data["delta"]) == (cole.id, "item", -1)
    assert (got.character_id, got.kind) == (trah.id, "add_item")
    assert got.data | {"name": ""} == {"definition": sheet_def(sheet, 758022089), "entityTypeId": 112130694, "quantity": 1, "name": ""}
    assert took.label == "Cole gave Trah Potion of Healing" and got.label == "Trah got Potion of Healing from Cole"


def sheet_def(sheet, item_id):
    return next(i for i in sheet["inventory"] if i["id"] == item_id)["definition"]["id"]


def test_giving_the_last_one_removes_it(player, db, sheet):
    cole, trah = char(db, "Cole"), trah_too(db)
    player.post(f"/characters/{cole.id}/items/758020411/give", data={"receiver": str(trah.id)})
    took, got = intents(db)
    assert took.kind == "remove_item" and got.kind == "add_item"


def test_nothing_is_taken_while_the_other_sheet_cant_be_reached(player, db, sheet):
    """A standing rule (Brett, 2026-10-28): a change with no way to D&D Beyond isn't accepted. Here, half a hand-over
    would lose the item, so neither half is made."""
    cole, trah = char(db, "Cole"), trah_too(db)
    trah.sheet_heard_at = None
    db.flush()
    r = player.post(f"/characters/{cole.id}/items/758020411/give", data={"receiver": str(trah.id)})
    assert r.status_code == 409 and "Nothing was taken from Cole" in r.json()["detail"] and not intents(db)


def test_a_bag_with_things_in_it_and_a_homebrew_item_are_handed_over_on_d_and_d_beyond(player, db, sheet):
    cole, trah = char(db, "Cole"), trah_too(db)
    bag = next(i for i in sheet["inventory"] if i["definition"]["name"] == "Bag of Holding")  # (Cole's holds his gear)
    next(i for i in sheet["inventory"] if i["id"] == 758020411)["definition"]["isHomebrew"] = True
    characters.refresh(db, cole)
    assert "take them out first" in player.get(f"/characters/{cole.id}/items/{bag['id']}/give").text
    r = player.post(f"/characters/{cole.id}/items/758020411/give", data={"receiver": str(trah.id)})
    assert r.status_code == 409 and "homebrew" in r.json()["detail"] and not intents(db)


# ------------------------------------------------------------------ loot from the DM


@pytest.fixture
def items(monkeypatch):
    monkeypatch.setattr(giving, "_catalog", {"at": 9e18, "items": [{"id": 8960641, "entityTypeId": 112130694, "name": "Potion of Healing", "magic": True, "rarity": "Common"}]})


def test_the_dm_gives_loot_an_item_and_coins(dm, db, sheet, items):
    cole = char(db, "Cole")
    set_role(db, "dm@example.com", "dm")
    w = dm.get(f"/characters/{cole.id}/loot").text
    assert "Loot for Cole" in w and 'value="Potion of Healing"' in w
    r = dm.post(f"/characters/{cole.id}/loot", data={"item": "potion of healing", "quantity": "2", "amount": "50", "coin": "gp"}).json()
    assert r["text"] == "Potion of Healing ×2 and 50 gp to Cole: on its way to D&D Beyond"
    item, coins = intents(db)
    assert item.data == {"definition": 8960641, "entityTypeId": 112130694, "quantity": 2, "name": "Potion of Healing"}
    assert coins.data["field"] == "coin:gp" and coins.data["delta"] == 50 and item.label == "Cole got Potion of Healing ×2 from the DM"


def test_loot_is_the_dms_and_only_from_d_and_d_beyonds_list(player, dm, db, sheet, items):
    cole = char(db, "Cole")
    set_role(db, "dm@example.com", "dm")
    assert player.get(f"/characters/{cole.id}/loot").status_code == 404
    r = dm.post(f"/characters/{cole.id}/loot", data={"item": "Sword of Made-Up Things"})
    assert r.status_code == 409 and "no item called" in r.json()["detail"] and not intents(db)
    assert "Give loot" in dm.get(f"/characters/{cole.id}").text


# ------------------------------------------------------------------ the Prepare spells screen


def test_the_prepare_screen_counts_and_makes_every_change_at_once(player, db, sheet):
    cole = char(db, "Cole")
    aid = next(s for s in sheet["askdnd"]["availableSpells"]["2190878"] if s["definition"]["name"] == "Aid")
    aid.update(id=21170801, entityTypeId=435869154)
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}/spells/prepare").text
    assert "<b data-prep-have>10</b>" in page and " of 10</span>" in page and "0 left<" in page
    assert "Druid 6 · <span title=\"After a Long Rest" in page and "change any after a Long Rest" in page  # (the whole rule on hover)
    assert 'data-name="Aid"' in page and 'data-name="Healing Word"' in page
    assert 'id="peek-title">Prepare spells' in page  # a large modal, like the Spell Book
    r = player.post(f"/characters/{cole.id}/spells/prepare", json={"changes": [{"key": "spell:Healing Word", "on": False}, {"key": "spell:Aid", "on": True}]})
    assert r.status_code == 200 and r.json()["text"] == "2 changes on its way to D&D Beyond"
    assert [(i.kind, i.data["name"], i.data["value"]) for i in intents(db)] == [("prepare", "Healing Word", False), ("prepare", "Aid", True)]
    assert {op["body"]["prepared"] for op in ops(db, cole)} == {True, False}  # one batch, both changes
    page = player.get(f"/characters/{cole.id}/spells/prepare").text
    assert page.count('title="On its way to D&amp;D Beyond"') == 2  # each shows ↻ until D&D Beyond has it


def test_the_prepare_screen_turns_away_what_it_cant_make(player, db, sheet):
    cole = char(db, "Cole")
    url = f"/characters/{cole.id}/spells/prepare"
    assert player.post(url, json={"changes": []}).status_code == 409
    # A cantrip with one it can make: the one is made and the other said (review, Nov 2: one spell no longer fails the lot)
    r = player.post(url, json={"changes": [{"key": "spell:Mending", "on": True}, {"key": "spell:Healing Word", "on": False}]})
    assert r.json()["text"] == "1 change on its way to D&D Beyond; 1 spell can't be prepared from askdnd, left as it is"
    assert [i.data["name"] for i in intents(db)] == ["Healing Word"]
    for i in intents(db):
        db.delete(i)
    db.flush()
    assert player.post(url, json={"changes": [{"key": "spell:Healing Word", "on": "yes"}]}).status_code == 409
    r = player.post(url, json={"changes": [{"key": "spell:Healing Word", "on": True}]})  # already prepared
    assert r.json()["text"].startswith("Nothing to change") and not intents(db)


def test_your_notes_show_on_the_prepare_screen(player, db, sheet):
    """Brett, 2026-11-02: notes matter when choosing what to prepare."""
    from app import picks

    cole = char(db, "Cole")
    picks.set_note(db, cole, "spell:Healing Word", "Bonus Action: keep for Trah")
    db.commit()
    assert "✎ Bonus Action: keep for Trah" in player.get(f"/characters/{cole.id}/spells/prepare").text


def test_a_long_rest_offers_prepare_spells(player, db, sheet):
    cole = char(db, "Cole")
    assert "/spells/prepare?cls=Druid" in player.get(f"/characters/{cole.id}/rest?kind=long").text
    assert "/spells/prepare" not in player.get(f"/characters/{cole.id}/rest?kind=short").text
    assert "/spells/prepare?cls=Druid" in player.get(f"/characters/{cole.id}").text  # Sheet › Spells
    assert 'data-modal-url="/characters/%d/spells/prepare"' % cole.id in player.get(f"/characters/{cole.id}/spellbook").text  # the Spell Book


def test_a_class_d_and_d_beyond_gives_no_number_for_gets_the_rules_number(player, db, sheet):
    """Brett, 2026-11-02 ("Do I have 2 slots left?"): D&D Beyond leaves a 2024 Cleric's number out; the 2024 rules'
    table (SRD 5.2.1) fills it, and the count shows a box for each spell the class prepares."""
    from app.ddb_sheet import prepared_by_rules

    assert (prepared_by_rules("Cleric", 9), prepared_by_rules("Druid", 6), prepared_by_rules("Artificer", 10)) == (14, 10, None)
    cole = char(db, "Cole")
    druid = next(c for c in sheet["classes"] if c["definition"]["name"] == "Druid")
    druid["definition"]["spellRules"]["levelPreparedSpellMaxes"] = None  # as D&D Beyond sends a Cleric
    characters.refresh(db, cole)
    page = player.get(f"/characters/{cole.id}/spells/prepare").text
    assert " of 10</span>" in page and page.count('<i class="on"></i>') == 10 and 'aria-label="10 of 10 prepared"' in page


def test_a_failed_item_list_isnt_read_again_at_once(monkeypatch):
    """Review, Nov 2: with D&D Beyond's item list down, every Give loot waited for its timeout; now a failed read waits
    CATALOG_RETRY before the next try."""
    calls = []

    def down(url, timeout):
        calls.append(url)
        raise OSError("D&D Beyond is down")

    monkeypatch.setattr(giving, "_catalog", {"at": 0.0, "tried": 0.0, "items": []})
    monkeypatch.setattr(giving.ddb, "_get_json", down)
    assert giving.catalog() == [] and giving.catalog() == []
    assert len(calls) == 1
