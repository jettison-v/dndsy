"""The rules engine's own workings (app/rules_book.py: `fill`, `active`, `has_names`, `reminded`, the scales), each
pinned where mutation testing (scripts/mutation.py rules_book, Nov 14) planted a bug the other tests didn't notice:
a multiclass character's levels, an upgraded feature replacing its first form, an item marked with its kind, a token
the sheet can't fill. The books' entries themselves are checked in test_rules_books.py and test_every_roll."""

from app import rules_book
from tests.table_setup import made_up


def names(sheet):
    return {e["name"] for e in rules_book.active(sheet)}


def entry(name):
    return next(e for e in rules_book.entries() if e["name"] == name)


# ------------------------------------------------------------------ fill: levels


def test_a_multiclass_characters_class_level_is_that_class_alone():
    """{lv} and {half} count the entry's own class; with no class they count the whole character; {level:X} and
    {half:X} name the class, 0 for one the character doesn't have."""
    s = made_up(("Barbarian", 7, "Path of the Zealot"), ("Fighter", 5, "Champion"))
    assert rules_book.fill("{lv}", s, "Barbarian") == "7" and rules_book.fill("{lv}", s) == "12"
    assert rules_book.fill("{half}", s, "Barbarian") == "3" and rules_book.fill("{half}", s) == "6"
    assert rules_book.fill("{level:Fighter}", s) == "5" and rules_book.fill("{half:Fighter}", s) == "2"
    assert rules_book.fill("{level:Wizard}", s) == "0" and rules_book.fill("{half:Wizard}", s) == "0"
    assert rules_book.fill("{lv}", made_up(("Fighter", None, "Champion"))) == "0"  # (a level D&D Beyond left out)


def test_an_entrys_bonus_uses_its_own_classs_level():
    """Divine Fury: 1d6 + half the Barbarian level, not half the character's; its source is the subclass."""
    s = made_up(("Barbarian", 7, "Path of the Zealot"), ("Fighter", 5, "Champion"))
    fury = next(a for a in rules_book.adds(s) if a["name"] == "Divine Fury")
    assert fury["amount"] == "1d6+3" and fury["effect"] == "+1d6+3 Necrotic or Radiant"
    assert fury["source"] == "Path of the Zealot"


def test_a_scale_goes_by_its_class_or_by_the_whole_character():
    """Martial Arts goes by Monk levels, the Dragonborn's Breath Weapon by character level, and a class the character
    doesn't have scales to nothing."""
    s = made_up(("Monk", 4, "Warrior of the Open Hand"), ("Fighter", 6, "Champion"))
    assert rules_book.fill("{ma}", s) == "1d6"  # (Monk 4, not character level 10's d8)
    assert rules_book.fill("{breath}d10", s) == "2d10"  # (character level 10: 2d10 from 5)
    assert rules_book.fill("{breath}d10", made_up(("Fighter", 4, "Champion"))) == "1d10"
    assert rules_book.fill("{sneak}", s) == ""


# ------------------------------------------------------------------ fill: abilities and numbers


def test_an_ability_is_found_by_its_key_or_its_short_name():
    """D&D Beyond's abilities carry a key ("dexterity") and a short name ("Dex"); either alone is enough."""
    by_key = {"abilities": [{"key": "dexterity", "modifier": 4}], "proficiency_bonus": 3}
    by_short = {"abilities": [{"short": "Dex", "modifier": 4}], "proficiency_bonus": 3}
    for s in (by_key, by_short):
        assert rules_book.fill("{mod:dex}", s) == "4" and rules_book.fill("{mod:dexterity}", s) == "4"
        assert rules_book.fill("1d6+{mod_dex}", s) == "1d6+4" and rules_book.fill("{dc:dexterity}", s) == "15"


def test_a_missing_ability_or_bonus_counts_as_its_plain_value():
    """No abilities: a modifier is 0 (a +0 is left out); no proficiency bonus: 2."""
    assert rules_book.fill("{mod:wisdom}", {}) == "0" and rules_book.fill("1d6+{mod_wis}", {}) == "1d6"
    assert rules_book.fill("{pb}", {}) == "2" and rules_book.fill("{dc:wisdom}", {}) == "10"


def test_signs_come_out_once():
    """A negative modifier after a plus is a minus; a signed token after a plus isn't doubled; a +0 is left out."""
    def s(mod):
        return made_up(("Fighter", 5, "Champion"), mods={"Str": mod})

    assert rules_book.fill("1d8+{mod_str}", s(-1)) == "1d8-1"
    assert rules_book.fill("1d8+{mod_str}", s(2)) == "1d8+2"
    assert rules_book.fill("1d8+{mod_str}", s(0)) == "1d8"
    assert rules_book.fill("{mod_str|1}", s(-1)) == "+1" and rules_book.fill("{mod:strength|1}", s(-1)) == "1"
    assert rules_book.fill(None, s(0)) == ""


def test_a_token_the_engine_doesnt_know_is_left_as_written():
    s = made_up(("Fighter", 5, "Champion"))
    assert rules_book.fill("2{unknown}", s) == "2{unknown}"
    assert rules_book.fill("2{unknown|1}", s) == "2{unknown|1}"


# ------------------------------------------------------------------ what a character has


def test_upgraded_features_replace_their_first_form():
    """Brutal Strike becomes Brutal Strike (2d10) at Barbarian 17: one of a group, the highest the character has."""
    assert {"Brutal Strike"} == {n for n in names(made_up(("Barbarian", 9, "Path of the Berserker"))) if n.startswith("Brutal")}
    assert {"Brutal Strike (2d10)"} == {n for n in names(made_up(("Barbarian", 17, "Path of the Berserker"))) if n.startswith("Brutal")}


def test_a_spell_or_feature_the_sheet_lists_brings_its_entry():
    s = made_up(("Paladin", 5, "Oath of Devotion"))
    assert "Branding Smite" not in names(s)
    s["spells"] = [{"name": "Branding Smite"}]
    assert "Branding Smite" in names(s)
    d = made_up(("Fighter", 5, "Champion"))
    assert "Breath Weapon" not in names(d)
    d["features"] = [{"name": "Breath Weapon", "source": "Species"}]
    assert "Breath Weapon" in names(d)


def test_an_item_marked_with_its_kind_counts_while_equipped():
    """Dragon-Touched Focus's Chromatic bonus: the item marked Chromatic (askdnd's item choice), equipped, by its
    magic item name (`base_name`) or by its own name with D&D Beyond's note in brackets."""
    def s(**item):
        out = made_up(("Sorcerer", 5, "Draconic Sorcery"))
        out["inventory"] = [{"key": "item:7", "equipped": True} | item]
        out["_item_choices"] = {"7": "Chromatic"}
        return out

    assert "Dragon-Touched Focus" in names(s(name="Dragon-Touched Focus (Wakened)"))
    assert "Dragon-Touched Focus" in names(s(name="Grandmother's Focus", base_name="Dragon-Touched Focus"))
    assert "Dragon-Touched Focus" not in names(s(name="Dragon-Touched Focus (Wakened)", equipped=False))


def test_a_magic_weapon_is_found_by_its_magic_item_name():
    """A weapon D&D Beyond shows by its own name ("Grandfather's Club") is found by the magic item it is."""
    s = made_up(("Fighter", 5, "Champion"))
    s["inventory"] = [{"name": "Grandfather's Club", "base_name": "Thunderous Greatclub", "key": "item:1",
                       "category": "Weapon", "equipped": True, "attunement": ""}]
    assert "Thunderous Greatclub" in names(s)


def test_a_homebrew_item_counts_only_for_who_carries_it():
    s = made_up(("Fighter", 5, "Champion"))
    s["_homebrew"] = {"guiding compass": {"kind": "item", "name": "Guiding Compass", "adds": [
        {"name": "Guiding needle", "when": "before", "to": ["check"], "amount": "1"}]}}
    s["inventory"] = [{"name": "Rope", "key": "item:3", "category": "Adventuring Gear", "equipped": False, "attunement": ""}]
    assert "Guiding Compass" not in names(s)


def test_a_class_is_listed_by_its_features_sources():
    """R6 asks only of a sheet that lists its class's features: one sourced to the class or its subclass, not a feat."""
    feat_only = made_up(("Cleric", 5, "Life Domain"), features=[("Alert", "Feat")])
    assert "Sear Undead" in names(feat_only)
    by_subclass = made_up(("Cleric", 5, "Life Domain"), features=[("Disciple of Life", "Life Domain")])
    assert "Sear Undead" not in names(by_subclass)


def test_a_reminder_says_when():
    s = made_up(("Fighter", 18, "Champion"))
    assert {"name": "Survivor", "when": entry("Survivor")["row"]["when"]} in rules_book.reminded(s, "turn")


def test_an_action_the_sheet_lists_brings_its_entry():
    d = made_up(("Fighter", 5, "Champion"))
    assert "Healing Hands" not in names(d)
    d["actions"] = [{"name": "Healing Hands"}]
    assert "Healing Hands" in names(d)


def test_a_feature_that_needs_a_choice_comes_with_it():
    """A Battle Master's Ambush only when the sheet has the maneuver, on a sheet that lists its features or not."""
    assert "Ambush" not in names(made_up(("Fighter", 3, "Battle Master")))
    assert "Ambush" in names(made_up(("Fighter", 3, "Battle Master"), features=[("Ambush", "Battle Master")]))
    assert "Ambush" not in names(made_up(("Fighter", 2, "Battle Master"), features=[("Ambush", "Battle Master")]))


def test_a_bonus_says_where_it_comes_from():
    """Its subclass, else its class, "Feat" for a feat, else its own name; an item's bonus names the item."""
    s = made_up(("Paladin", 6, "Oath of Devotion"), ("Fighter", 3, "Battle Master"),
                features=[("Charger", "Feat"), ("Ambush", "Battle Master")])
    s["inventory"] = [{"name": "Thunderous Greatclub", "key": "item:1", "category": "Weapon", "equipped": True, "attunement": ""}]
    by = {a["name"]: a for a in rules_book.adds(s)}
    assert by["Aura of Protection"]["source"] == "Paladin" and by["Aura of Protection"]["_kind"] == "feature"
    assert by["Ambush"]["source"] == "Battle Master" and by["Charger"]["source"] == "Feat"
    club = next(a for a in by.values() if a.get("item") == "Thunderous Greatclub")
    assert club["_kind"] == "item" and "item" not in by["Charger"]
