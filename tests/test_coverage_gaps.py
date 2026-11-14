"""The books' coverage, completed (Brett, Nov 14: "the same scalable way"): the last gaps each a line of data in
app/data/rules/phb-2024.json, played by what the engine already does plus six new shapes, each built once:

- `row`: a feature that rolls but isn't one of D&D Beyond's actions gets its own Battle row (character_views.options);
- "2x…": a part that counts twice (rr.times; Mantle of Inspiration);
- an add's `op` "max": a spell's healing dice at their highest (Supreme Healing), and "self_heal": you regain it after
  healing someone else (Blessed Healer), both played by the roll card;
- a scale for a spell's die (Hunter's Mark's d10 at Ranger 20, Foe Slayer; tests/test_spellbook.py);
- `remind`: said where the moment is (the hit points window at 0, the Rest window), its roll on Battle;
- {hp_half} and plain sums ("5+2" is 7) when tokens are filled.
"""

import json

import pytest

from app import character_views as views
from app import roll_plan, rules_book
from app import roll_recipes as rr
from app import table_rolls as tr
from tests.table_setup import plain_id
from tests.test_class_rules import made_up

ROWS = [  # (class, level, subclass, feats, the row's name, its column, each effect's parts)
    ("Bard", 5, "College of Glamour", [], "Mantle of Inspiration", "Bonus action", [["2x1d8"]]),
    ("Fighter", 18, "Champion", [], "Survivor", "No action", [["7"]]),
    ("Paladin", 20, "Oath of the Ancients", [], "Undying Sentinel", "No action", [["1", "3x20"]]),
    ("Paladin", 20, "Oath of the Ancients", [], "Elder Champion", "No action", [["10"]]),
    ("Warlock", 10, "Fiend Patron", [], "Dark One's Blessing", "No action", [["10"]]),
    ("Warlock", 10, "Celestial Patron", [], "Celestial Resilience", "No action", [["10"], ["5"]]),
    ("Cleric", 17, "Trickery Domain", [], "Improved Duplicity", "No action", [["17"]]),
    ("Fighter", 5, "Champion", [("Healer", "Feat")], "Healer", "Action", [["1d6+3"], ["1d8+3"], ["1d10+3"], ["1d12+3"]]),
    ("Fighter", 5, "Champion", [("Inspiring Leader", "Feat")], "Inspiring Leader", "No action", [["7"], ["5"]]),
    ("Fighter", 20, "Champion", [("Boon of Recovery", "Feat")], "Boon of Recovery", "No action", [["1", "60"], ["1d10"]]),
]


def sheet(cls, level, sub, feats=()):
    s = made_up((cls, level, sub), features=feats)
    s["hit_points"] = {"max": 120, "current": 80}
    return s


@pytest.mark.parametrize("cls, level, sub, feats, name, column, parts", ROWS, ids=plain_id)
def test_a_feature_that_rolls_has_its_row_and_its_roll(cls, level, sub, feats, name, column, parts):
    """Each gap is a Battle row in its column (no action needed: it happens when something sets it off), and its
    button rolls exactly the data's dice, tokens filled from the sheet; the server takes every one of them."""
    rows = {o["name"]: o for o in views.options(sheet(cls, level, sub, feats))}
    o = rows[name]
    assert o["cost"] == column and o["meta"]
    plan = json.loads(next(r for r in views.option_rolls(o) if r.get("attrs"))["attrs"]["plan"])
    got = [e["at"][str(plan["rolls"]["base"])]["parts"] for e in plan["rolls"]["effects"]]
    assert got == parts
    assert all(tr.check_parts(p) for p in got)


def test_a_row_is_only_for_who_has_it():
    """A Champion below 18 has no Heroic Rally; a Glamour Bard's row isn't a Lore Bard's."""
    assert "Survivor" not in {o["name"] for o in views.options(sheet("Fighter", 17, "Champion"))}
    assert "Mantle of Inspiration" not in {o["name"] for o in views.options(sheet("Bard", 5, "College of Lore"))}


def test_twice_the_roll_and_every_die_at_its_highest():
    rolls = iter([3, 5])
    twice = tr.roll_parts(["2x1d8"], roll=lambda sides: next(rolls))
    assert twice["total"] == 6 and twice["parts"][0]["formula"] == "2×(1d8)"
    best = tr.roll_parts(["2d8+4"], best=True)
    assert best["total"] == 20 and best["dice"] == [8, 8]
    assert rr.times("2x1d8") == 2 and rr.times("1d8") == 1 and rr.parse_part("2x1d8") == (1, 8, 0, "")


def test_a_life_clerics_healing_spell_offers_its_highest_dice_and_its_own_healing():
    """Supreme Healing (Cleric 17) is a pill for every die at its highest; Blessed Healer (Cleric 6) is your own
    2 + the slot's level once it healed someone else; Disciple of Life still adds to the healing."""
    s = sheet("Cleric", 17, "Life Domain")
    mods = {m["name"]: m for m in roll_plan.modifiers_for(s, "", spell={"level": 1, "heals": True, "damages": False})}
    assert mods["Supreme Healing"]["op"] == "max" and not mods["Supreme Healing"].get("adds")
    assert mods["Blessed Healer"]["op"] == "self_heal" and mods["Blessed Healer"]["adds_at"]["3"] == "+5"
    assert "op" not in mods["Disciple of Life"]
    low = {m["name"] for m in roll_plan.modifiers_for(sheet("Cleric", 6, "Life Domain"), "", spell={"level": 1, "heals": True, "damages": False})}
    assert "Blessed Healer" in low and "Supreme Healing" not in low


def test_the_moments_are_said_where_they_happen():
    """At 0 Hit Points the hit points window names what keeps you up (Undying Sentinel); after a rest, the Rest window
    names what gives Temporary Hit Points (Celestial Resilience); at your turn, Heroic Rally."""
    assert [r["name"] for r in rules_book.reminded(sheet("Paladin", 15, "Oath of the Ancients"), "zero")] == ["Undying Sentinel"]
    assert [r["name"] for r in rules_book.reminded(sheet("Warlock", 10, "Celestial Patron"), "rest")] == ["Celestial Resilience"]
    assert [r["name"] for r in rules_book.reminded(sheet("Fighter", 18, "Champion"), "turn")] == ["Survivor"]
    assert rules_book.reminded(sheet("Paladin", 14, "Oath of the Ancients"), "zero") == []


def test_numbers_alone_add_up_and_a_dies_own_bonus_is_left():
    s = {"abilities": [{"short": "con", "modifier": 2}], "hit_points": {"max": 51}}
    assert rules_book.fill("5+{mod:con}", s) == "7"
    assert rules_book.fill("{hp_half}", s) == "25"
    assert rules_book.fill("1d4-2+3", s) == "1d4-2+3" and rules_book.fill("1d8+3", s) == "1d8+3"
