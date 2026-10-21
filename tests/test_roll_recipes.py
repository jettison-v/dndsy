"""Roll recipes (app/roll_recipes.py): the stored, audited way each spell, Beast action and item
rolls (scripts/roll_audit.py builds them from the 2024 rules text; docs/rules/rolls-audit.md)."""

import json
from pathlib import Path

import pytest

from app import roll_recipes as rr
from app import wild_shape as ws

BEASTS = {b["name"]: b for b in json.loads((Path(__file__).parent.parent / "app" / "data" / "beasts_2024.json").read_text())["beasts"]}


def action(beast, name):
    b = BEASTS[beast]
    return next(e for k in ("actions", "bonus_actions", "reactions") for e in b.get(k) or [] if e["name"] == name)


def test_every_stored_recipe_is_well_formed():
    data = rr.recipes()
    assert len(data["spells"]) >= 120 and data["items"]
    for name, recipe in list(data["spells"].items()) + list(data["items"].items()):
        assert recipe["checked"], name
        for e in recipe["events"]:
            assert e["on"] in ("hit", "save", "auto", "heal", "temp", "plain"), name
            assert e["parts"] and all(rr.parse_part(p) for p in e["parts"]), name
            assert len(e.get("upcast") or e["parts"]) == len(e["parts"]), name
            if e["on"] == "save":
                assert e.get("success") in ("half", "none"), name


@pytest.mark.parametrize("name, slot, level, expected", [
    ("Fireball", 3, 5, [["8d6 fire"]]),
    ("Fireball", 5, 9, [["10d6 fire"]]),
    ("Ice Knife", 3, 5, [["1d10 piercing"], ["4d6 cold"]]),  # only the Cold damage upcasts
    ("Cure Wounds", 2, 3, [["4d8"]]),
    ("False Life", 3, 5, [["2d4+14"]]),  # a flat 5 per level
    ("Fire Bolt", None, 11, [["3d10 fire"]]),
    ("Spirit Guardians", 4, 7, [["4d8 radiant or necrotic"]]),  # one or the other, never both
    ("Flame Strike", 6, 11, [["6d6 fire", "6d6 radiant"]]),
    ("Vitriolic Sphere", 5, 9, [["12d4 acid"], ["5d4 acid"]]),  # only the initial damage upcasts
    ("Wall of Ice", 7, 13, [["12d6 cold"], ["6d6 cold"]]),
])
def test_upcasting_and_cantrips(name, slot, level, expected):
    assert [e["parts"] for e in rr.resolve(rr.spell(name), slot, level)] == expected


def test_instances_and_their_growth():
    mm = rr.resolve(rr.spell("Magic Missile"), 3)[0]
    assert (mm["count"], mm["parts"], mm["on"]) == (5, ["1d4+1 force"], "auto")  # each dart rolled on its own
    ray = rr.resolve(rr.spell("Scorching Ray"), 4)[0]
    assert (ray["count"], ray["parts"], ray["on"]) == (5, ["2d6 fire"], "hit")
    # Eldritch Blast isn't in the SRD: D&D Beyond's recipe adds beams like this
    assert rr.resolve({"level": 0, "events": [{"on": "hit", "parts": ["1d10 force"], "cantrip": "count"}]}, None, 11)[0]["count"] == 3
    assert rr.resolve(rr.spell("True Strike"), None, 4) == []  # nothing extra before level 5
    assert rr.resolve(rr.spell("True Strike"), None, 11)[0]["parts"] == ["2d6 radiant"]


def test_hand_written_cases():
    assert [e["name"] for e in rr.spell("Toll the Dead")["events"]] == ["Unhurt target", "Target missing Hit Points"]
    assert rr.spell("Chain Lightning")["events"][0].get("count", 1) == 1  # one roll for all targets
    assert rr.spell("Healing Word")["events"][0]["mod"] and not rr.spell("Prayer of Healing")["events"][0].get("mod")
    assert rr.spell("Melf's Acid Arrow") is rr.spell("Acid Arrow")  # D&D Beyond's name finds the SRD recipe
    assert rr.spell("Bigby's Hand") is rr.spell("Arcane Hand")
    assert rr.spell("Bless") is None  # the 1d4 is the target's, not a roll you make
    assert rr.item("Use an item: Potion of Healing (Superior)")["events"][0]["parts"] == ["8d4+8"]


def test_beast_attacks_keep_every_part_and_never_add_conditions():
    bite = ws.beast_recipe(action("Giant Toad", "Bite"))["events"]
    assert [e["parts"] for e in bite] == [["1d6+2 piercing", "2d4 poison"]]
    gore = ws.beast_recipe(action("Rhinoceros", "Gore"))["events"]
    assert gore[0]["parts"] == ["2d8+5 piercing"] and gore[1] == {**gore[0], "name": "After a 20-ft charge", "parts": ["2d8+5 piercing", "2d8 piercing"]}
    swarm = ws.beast_recipe(action("Swarm of Venomous Snakes", "Bites"))["events"]
    assert swarm[1]["parts"] == ["1d4+4 piercing", "3d6 poison"] and swarm[1]["name"] == "Swarm Bloodied"
    assert ws.beast_recipe(action("Goat", "Ram"))["events"][0]["parts"] == ["1 bludgeoning"]
    trample = ws.beast_recipe(action("Elephant", "Trample"))["events"][0]
    assert (trample["on"], trample["save"], trample["success"]) == ("save", "Dex", "half")
    assert ws.beast_recipe(action("Giant Toad", "Bite"), damage_bonus=1)["events"][0]["parts"][0] == "1d6+3 piercing"  # worn item


def test_every_beast_die_is_accounted_for():
    import re

    for b in BEASTS.values():
        for k in ("actions", "bonus_actions", "reactions"):
            for e in b.get(k) or []:
                dice = set(re.findall(r"\d+d\d+", e["text"]))
                got = {re.match(r"\d+d\d+", p).group(0) for ev in (ws.beast_recipe(e) or {"events": []})["events"]
                       for p in ev["parts"] if re.match(r"\d+d\d+", p)}
                assert dice <= got, (b["name"], e["name"], dice - got)
