"""Short and Long Rests (app/rests.py): what comes back, by the 2024 rules, through the bridge."""

import pytest
from sqlalchemy import select

from app import characters, rests
from app.models import BridgeIntent, Campaign, TableRoll
from tests.table_setup import char


@pytest.fixture(autouse=True)
def test_campaign(db, sheet):
    """Live state comes with Sync with D&D Beyond (app/vtt.py), switched on for the campaign."""
    db.get(Campaign, char(db, "Cole").campaign_id).vtt_pieces = ["sync"]
    db.flush()


def sheet_with(**kw):
    return {"hit_points": {"current": 20, "max": 30, "damage": 10, "temp": 0, "hit_dice": [{"id": 5, "class": "Druid", "die": "d8", "total": 6, "used": 2}]},
            "spell_slots": {"slots": [{"level": 1, "max": 4, "used": 2}], "pact": {"level": 2, "max": 2, "used": 1}},
            "actions": [{"id": 1, "name": "Focus Points", "uses": {"used": 1, "reset": "Short or Long Rest"}},
                        {"id": 2, "name": "Wild Resurgence", "uses": {"used": 1, "reset": "Long Rest"}},
                        {"id": 3, "name": "Sunrise", "uses": {"used": 1, "reset": "Dawn"}}],
            "inventory": [{"key": "item:9", "name": "Wand", "charges": {"used": 2, "reset": "Long Rest"}}], "conditions": [], **kw}


def test_a_short_rest_brings_back_only_what_comes_back_on_one():
    assert [c["field"] for c in rests.counts(sheet_with(), "short")] == ["pact:2", "uses:1"]


def test_a_long_rest_brings_back_slots_and_everything_else_but_not_what_comes_at_dawn():
    assert [c["field"] for c in rests.counts(sheet_with(), "long")] == ["slot:1", "pact:2", "uses:1", "uses:2", "charges:9"]
    assert rests.at_dawn(sheet_with()) == ["Sunrise"]


def test_a_long_rest_says_all_hit_points_all_hit_dice_and_exhaustion_down_one():
    s = sheet_with(conditions=[{"name": "Exhaustion", "level": 2}])
    s["hit_points"]["temp"] = 5
    words = rests.lines(rests.plan(s, "long"), "long")
    assert "All Hit Points: 10 back" in words and "All Hit Point Dice: 2 back" in words
    assert "Temporary Hit Points end (5)" in words and "Exhaustion 2 goes down 1" in words


def test_hit_point_dice_add_constitution_once_each():
    druid, monk = {"die": "d8"}, {"die": "d10"}
    assert rests._formula([(druid, 2), (monk, 1)], 2) == "2d8+1d10+6"
    assert rests._formula([(druid, 1)], -1) == "1d8-1"
    assert rests._formula([(druid, 1)], 0) == "1d8"


def test_no_rest_at_0_hit_points():
    s = sheet_with()
    s["hit_points"]["current"] = 0
    assert not rests.plan(s, "long")["can"]


def test_concentration_ends_when_the_rest_outlasts_it():
    """Brett, Nov 3: a Short Rest (an hour) ends a spell lasting an hour or less; a Long Rest's sleep ends any."""
    minute, day, unknown = {"spell": "Moonbeam", "rounds": 10}, {"spell": "Find the Path", "rounds": 14400}, {"spell": "X", "rounds": 0}
    assert rests.conc_ends(minute, "short") == "Moonbeam" and rests.conc_ends({"spell": "Y", "rounds": 600}, "short") == "Y"
    assert rests.conc_ends(day, "short") == "" and rests.conc_ends(unknown, "short") == ""
    assert rests.conc_ends(day, "long") == "Find the Path" and rests.conc_ends(None, "long") == ""


def test_a_rest_ends_concentration_unless_you_untick_it(player, db, sheet):
    cole = char(db, "Cole")
    cole.concentration = {"spell": "Moonbeam", "key": "spell:Moonbeam", "level": 2, "round": 1, "rounds": 10}
    db.flush()
    page = player.get(f"/characters/{cole.id}/rest?kind=short").text
    assert 'name="conc_ends" value="1" checked' in page and "Concentration on Moonbeam ends" in page
    player.post(f"/characters/{cole.id}/rest?kind=short")  # unticked: not sent, so it lasts (the DM's ruling)
    db.refresh(cole)
    assert cole.concentration["spell"] == "Moonbeam"
    r = player.post(f"/characters/{cole.id}/rest?kind=short", data={"conc_ends": "1"})
    assert "Concentration on Moonbeam ended" in r.json()["text"]
    db.refresh(cole)
    assert cole.concentration is None


def worn(db, sheet, cole):
    """Cole with damage, a slot and Focus Points used, as D&D Beyond has it."""
    data = sheet
    data["removedHitPoints"] = 14
    next(c for c in data["classes"] if c["level"] >= 2)["hitDiceUsed"] = 1
    next(s for s in data["spellSlots"] if s["level"] == 1)["used"] = 1
    next(a for a in data["actions"]["class"] if a["name"] == "Focus Points")["limitedUse"]["numberUsed"] = 1
    characters.refresh(db, cole)


def test_a_long_rest_lists_it_all_then_makes_it_on_d_and_d_beyond(player, db, sheet):
    cole = char(db, "Cole")
    worn(db, sheet, cole)
    page = player.get(f"/characters/{cole.id}/rest?kind=long").text
    assert "All Hit Points: 14 back" in page and "Focus Points: 1 back" in page and "Take a Long Rest" in page
    # Short and Long side by side, always (Brett, 2026-11-02: Long Rest was hard to find)
    assert 'aria-label="Which rest"' in page and 'rest?kind=short">Short Rest' in page and 'aria-pressed="true">Long Rest' in page
    assert db.scalar(select(BridgeIntent)) is None  # (nothing moves until Rest)
    r = player.post(f"/characters/{cole.id}/rest?kind=long")
    assert r.status_code == 200 and r.json()["deliver"]
    made = {(i.kind, i.data.get("field")) for i in db.scalars(select(BridgeIntent))}
    assert ("hp", None) in made and ("use", "slot:1") in made
    assert any(k == "use" and f and f.startswith("hitdice:") for k, f in made)
    assert any(k == "use" and f and f.startswith("uses:") for k, f in made)


def test_a_short_rest_spends_the_dice_you_chose_rolls_them_and_heals(player, db, sheet):
    cole = char(db, "Cole")
    worn(db, sheet, cole)
    druid = next(d for d in rests.dice(characters.character_summary(cole)) if d["left"])
    assert f'name="dice_{druid["id"]}"' in player.get(f"/characters/{cole.id}/rest?kind=short").text
    r = player.post(f"/characters/{cole.id}/rest?kind=short", data={f"dice_{druid['id']}": "1"})
    assert r.status_code == 200, r.text
    assert db.scalar(select(TableRoll).where(TableRoll.label == "Hit Point Dice")) is not None
    kinds = {i.kind for i in db.scalars(select(BridgeIntent))}
    assert {"short_rest", "hp"} <= kinds


def test_a_short_rest_spending_nothing_still_brings_resources_back(player, db, sheet):
    cole = char(db, "Cole")
    worn(db, sheet, cole)
    r = player.post(f"/characters/{cole.id}/rest?kind=short")
    assert r.status_code == 200 and "Focus Points" in r.json()["text"]
    assert db.scalar(select(TableRoll).where(TableRoll.label == "Hit Point Dice")) is None


def test_a_closed_sheet_and_someone_elses_character(player, dm, db, sheet):
    cole = char(db, "Cole")
    assert dm.post(f"/characters/{cole.id}/rest?kind=long").status_code == 404
    cole.sheet_heard_at = None
    db.flush()
    assert "can't be reached" in player.get(f"/characters/{cole.id}/rest?kind=long").text
    assert player.post(f"/characters/{cole.id}/rest?kind=long").status_code == 409
