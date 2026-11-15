"""The outside review's smaller rules points (Nov 10, docs/artifacts/outside-review.html), done Nov 14:

- R4: one way a rules name is matched (`rules_book.norm`), where four slightly different cleaners were;
- R6: on a sheet that lists its class's features (D&D Beyond's do), a class feature applies only if the sheet names it
  (or the feature it's `part_of`), so a 2014 class's character isn't given a 2024 feature of the same level;
- R7: "at least one die" and "at least +1" as a floor on a token ({mod:wisdom|1}); Lifedrinker once a turn; Dreadful
  Strike left unpressed; Charger with an Unarmed Strike; a magic weapon's bonus only while it's equipped and attuned.
"""

import re

import pytest

from app import roll_plan, roll_recipes, rules_book
from app.class_rules import norm as class_norm
from tests.table_setup import made_up, plain_id


def entries():
    return [(e["_book"], e) for e in rules_book.entries()]


def names(sheet):
    return {e["name"] for e in rules_book.active(sheet)}


def adds(sheet):
    return {a["name"]: a for a in rules_book.adds(sheet)}


# ------------------------------------------------------------------ R4: one norm


@pytest.mark.parametrize("raw, base, whole", [
    ("Oath of Conquest (XGtE)", "oath of conquest", "oath of conquest (xgte)"),
    ("Monk’s  Focus ", "monk's focus", "monk's focus"),
    ("Potion of Healing (Greater)", "potion of healing", "potion of healing (greater)"),
    (None, "", ""),
], ids=plain_id)
def test_a_name_is_matched_one_way(raw, base, whole):
    assert rules_book.norm(raw) == base and rules_book.norm(raw, whole=True) == whole
    assert class_norm is rules_book.norm  # (class_rules matches with the same one, not a copy)


def test_items_and_features_are_found_by_that_one_way():
    assert roll_recipes.item("Use an item: potion of healing (greater)") is roll_recipes.item("Potion of Healing (Greater)")
    assert roll_recipes.item("Potion of Healing (Greater)") is not roll_recipes.item("Potion of Healing")
    assert roll_recipes.item("Hammer of Thunderbolts (Maul)") is roll_recipes.item("Hammer of Thunderbolts")
    assert roll_recipes.feature("Second  Wind") is roll_recipes.feature("second wind") is not None


# ------------------------------------------------------------------ R6: the sheet names it


def listed(cls, level, sub, features):
    """A sheet as D&D Beyond's are: its class's features listed with the class as their source."""
    return made_up((cls, level, sub), features=[(f, cls) for f in features])


def test_a_2014_class_isnt_given_a_2024_feature_of_the_same_level():
    """A 2014 Cleric 5's sheet lists Destroy Undead, not Sear Undead: it isn't given the 2024 Sear Undead's roll. A 2024
    Cleric's lists it, and a made-up character with nothing listed goes by class and level, as before."""
    old = listed("Cleric", 5, "Life Domain", ["Spellcasting", "Channel Divinity", "Destroy Undead"])
    new = listed("Cleric", 5, "Life Domain", ["Spellcasting", "Channel Divinity", "Divine Spark", "Sear Undead"])
    assert "Sear Undead" not in names(old) and "Divine Spark" not in names(old)
    assert {"Sear Undead", "Divine Spark"} <= names(new)
    assert "Sear Undead" in names(made_up(("Cleric", 5, "Life Domain")))


def test_an_option_counts_by_the_feature_its_part_of():
    """Rage Damage is part of Rage (D&D Beyond lists Rage): a Barbarian whose sheet lists Rage has it."""
    assert "Rage Damage" in names(listed("Barbarian", 5, "Path of the Berserker", ["Rage", "Reckless Attack"]))
    assert "Rage Damage" not in names(listed("Barbarian", 5, "Path of the Berserker", ["Reckless Attack"]))


def test_every_part_of_names_a_feature_of_its_own_class():
    for _, e in entries():
        if "part_of" in e:
            assert e.get("class") and isinstance(e["part_of"], str) and e["part_of"] != e["name"], e["name"]


# ------------------------------------------------------------------ R7: the small points


@pytest.mark.parametrize("mod, dice, aura", [(-1, "1d8", "1"), (0, "1d8", "1"), (3, "3d8", "3")], ids=plain_id)
def test_at_least_one_die_and_at_least_plus_one(mod, dice, aura):
    """Sear Undead: a number of d8s equal to Wisdom (minimum of 1d8); Aura of Protection: Charisma (minimum +1)."""
    s = made_up(("Cleric", 5, "Life Domain"), mods={"Str": 0, "Dex": 0, "Con": 0, "Int": 0, "Wis": mod, "Cha": 0})
    sear = next(e for e in rules_book.entries() if e["name"] == "Sear Undead")
    assert rules_book.fill(sear["rolls"][0]["dice"][0], s) == f"{dice} radiant"
    p = made_up(("Paladin", 6, "Oath of Devotion"), mods={"Str": 0, "Dex": 0, "Con": 0, "Int": 0, "Wis": 0, "Cha": mod})
    assert adds(p)["Aura of Protection"]["amount"] == aura


def test_a_count_of_dice_from_a_modifier_always_has_its_floor():
    """The guard: dice counted by an ability modifier ({mod:wisdom}d8) say their floor, or "0d8" and "-1d6" come back."""
    for _, e in entries():
        for r in e.get("rolls") or []:
            assert not any(re.search(r"\{mod:\w+\}d", p) for p in r["dice"]), e["name"]


def test_the_small_data_points():
    by = {a["name"]: a for _, e in entries() for a in e.get("adds") or []}
    assert by["Lifedrinker"]["once"] == "a turn"
    assert all(a.get("pressed") is False for _, e in entries() if e["name"].startswith("Dreadful Strike (") or e["name"] == "Dreadful Strike"
               for a in e["adds"])
    assert roll_plan.applies(by["Charger"], {"unarmed"}) and roll_plan.applies(by["Charger"], {"weapon", "melee_weapon"})


@pytest.mark.parametrize("equipped, attunement, has", [
    (True, "", True), (False, "", False), (True, "attuned", True), (True, "required", False),
], ids=plain_id)
def test_a_magic_weapons_bonus_is_there_while_its_in_use(equipped, attunement, has):
    s = made_up(("Fighter", 5, "Champion"))
    s["inventory"] = [{"name": "Thunderous Greatclub", "base_name": "Greatclub", "key": "item:1", "category": "Weapon",
                       "equipped": equipped, "attunement": attunement}]
    assert ("Thunderous Greatclub" in adds(s)) is has


def test_a_wondrous_item_counts_while_carried_unless_it_needs_attuning():
    s = made_up(("Fighter", 5, "Champion"))
    s["_homebrew"] = {"guiding compass": {"kind": "item", "name": "Guiding Compass", "adds": [
        {"name": "Guiding needle", "when": "before", "to": ["check"], "amount": "1"}]}}
    s["inventory"] = [{"name": "Guiding Compass", "key": "item:2", "category": "Other Gear", "equipped": False, "attunement": ""}]
    assert "Guiding needle" in adds(s)
    s["inventory"][0]["attunement"] = "required"
    assert "Guiding needle" not in adds(s)
