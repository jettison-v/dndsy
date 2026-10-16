"""D&D Beyond parsing, against saved public character JSON (tests/fixtures/ddb).
No network: fixtures were saved with scripts/ddb_fixture.py."""

import io
import json
import urllib.error
from pathlib import Path

import pytest

from app import ddb

FIXTURES = Path(__file__).parent / "fixtures" / "ddb"


def load(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())["data"]


@pytest.fixture(scope="module")
def cole():
    return ddb.parse_character(load("cole"))


@pytest.fixture(scope="module")
def no_name():
    return ddb.parse_character(load("no_name"))


@pytest.fixture(scope="module")
def big_c():
    return ddb.parse_character(load("big_c"))


def by_name(items, name):
    return next(x for x in items if x["name"] == name)


def test_identity_and_multiclass(cole):
    assert cole["name"] == "Cole Lockhard" and cole["species"] == "Wood Elf" and cole["background"] == "Wayfarer"
    assert cole["classes"] == [
        {"name": "Druid", "level": 6, "subclass": "Circle of the Moon"},
        {"name": "Monk", "level": 2, "subclass": ""},
    ]
    assert cole["level"] == 8 and cole["proficiency_bonus"] == 3
    assert cole["sheet_url"] == "https://www.dndbeyond.com/characters/75423618"


def test_ability_scores_include_species_background_feat_and_equipped_items(cole, big_c):
    scores = {a["short"]: (a["score"], a["label"]) for a in cole["abilities"]}
    assert scores["Wis"] == (20, "+5")  # 15 + species + War Caster + Wayfarer (+2/+1)
    assert scores["Dex"] == (17, "+3")  # 13 + species + Manual of Quickness of Action
    assert by_name(big_c["abilities"], "Strength")["score"] == 21  # Belt of Hill Giant Strength sets 21


def test_hp_ac_speed(cole, no_name, big_c):
    assert cole["armor_class"] == 18  # Monk Unarmored Defense: 10 + Dex + Wis
    assert cole["speed"]["walk"] == 45  # Fleet of Foot 35 + Unarmored Movement 10
    assert cole["hit_points"]["max"] == 51
    assert no_name["hit_points"]["max"] == 75  # includes Tough (+2 per level)
    assert big_c["armor_class"] == 19  # plate 18 + Defense fighting style
    assert big_c["speed"]["walk"] == 30  # Unarmored Movement doesn't apply to Monks only; Big C isn't one


def test_multiclass_saves_come_from_the_first_class_only(cole, big_c):
    saves = {s["short"]: s for s in cole["saves"]}
    assert saves["Wis"]["proficient"] and saves["Int"]["proficient"]
    assert not saves["Str"]["proficient"] and not saves["Dex"]["proficient"]  # Monk was the second class
    assert saves["Wis"]["label"] == "+9"  # +5 Wis, +3 proficiency, +1 Luckstone
    big = {s["short"]: s for s in big_c["saves"]}
    assert big["Cha"]["proficient"] and not big["Con"]["proficient"]  # Sorcerer was the second class
    assert big["Str"]["label"] == "+8"  # Aura of Protection adds Cha to every save


def test_spell_slots_single_multiclass_and_pact(cole, no_name, big_c):
    assert [(s["level"], s["max"]) for s in cole["spell_slots"]["slots"]] == [(1, 4), (2, 3), (3, 3)]
    assert big_c["spell_slots"]["slots"][2] == {"level": 3, "max": 2, "used": 0}  # Paladin 6 + Sorcerer 2 = caster level 5
    assert no_name["spell_slots"]["slots"] == [] and no_name["spell_slots"]["pact"] == {"level": 1, "max": 2, "used": 0}
    assert cole["spellcasting"] == [{"class": "Druid", "ability": "Wisdom", "save_dc": 16, "attack": "+8"}]


def test_spells_detail(cole, big_c):
    heat = by_name(cole["spells"], "Heat Metal")
    assert heat["level"] == 2 and heat["concentration"] and not heat["ritual"] and heat["prepared"]
    assert heat["components"] == ["V", "S", "M"] and heat["range"] == "60 ft" and heat["casting_time"] == "Action"
    assert heat["duration"] == "Concentration, up to 1 minute" and heat["material"]
    assert by_name(cole["spells"], "Water Breathing")["ritual"]
    assert by_name(cole["spells"], "Healing Word")["casting_time"] == "Bonus action"
    assert by_name(cole["spells"], "Absorb Elements")["casting_time"] == "Reaction"
    assert by_name(cole["spells"], "Mending")["casting_time"] == "1 minute"
    rebuke = by_name(big_c["spells"], "Hellish Rebuke")  # free once per Long Rest, or with a slot
    assert rebuke["uses"]["max"] == 1 and rebuke["uses"]["reset"] == "Long Rest" and rebuke["uses_slot"]
    agathys = by_name(big_c["spells"], "Armor of Agathys")  # listed twice on D&D Beyond; shown once
    assert agathys["always_prepared"] and agathys["sources"] == ["Paladin", "Class feature"]
    assert len([s for s in big_c["spells"] if s["name"] == "Armor of Agathys"]) == 1


def test_resources_and_what_restores_them(cole, no_name):
    wild = by_name(cole["actions"], "Wild Shape")
    assert wild["activation"] == "Bonus action" and wild["uses"]["max"] == 3 and wild["uses"]["reset"] == "Long Rest"
    focus = by_name(cole["actions"], "Focus Points")
    assert focus["uses"]["max"] == 2 and focus["uses"]["reset_phrase"] == "back after a Short or Long Rest"
    assert by_name(no_name["actions"], "Focus Points")["uses"]["max"] == 6
    assert by_name(cole["actions"], "Luck Points")["uses"]["max"] == 3  # = proficiency bonus
    names = [r["name"] for r in cole["resources"]]
    assert names[0] == "Wild Shape" and "Focus Points" in names and names[-1] == "Spell slots"


def test_features_skip_headings_and_future_levels(cole):
    names = {(f["name"], f["source"]) for f in cole["features"]}
    assert ("Wild Shape", "Druid") in names and ("Circle Forms", "Circle of the Moon") in names
    assert ("Fey Ancestry", "Wood Elf") in names and ("War Caster", "Feat") in names
    assert not any(n in {"Core Druid Traits", "Druid Subclass", "Age", "Size", "Archdruid"} for n, _ in names)
    wild = next(f for f in cole["features"] if f["name"] == "Wild Shape")
    assert "<" not in wild["text"] and wild["summary"]


def test_inventory_magic_items_attunement_and_charges(cole, big_c):
    ring = by_name(cole["inventory"], "Ring of Invisibility")
    assert ring["magic"] and ring["equipped"] and ring["attunement"] == "attuned" and ring["rarity"] == "Legendary"
    armor = by_name(cole["inventory"], "Demon Armor")
    assert armor["attunement"] == "required" and armor["in"] == "Bag of Holding" and not armor["equipped"]
    assert sorted(cole["attuned"]) == ["Ring of Invisibility", "Stone of Good Luck (Luckstone)"]
    hammer = by_name(big_c["inventory"], "Hammer of Thunderbolts (Maul)")
    assert hammer["charges"]["max"] == 5 and hammer["charges"]["reset"] == "Dawn" and hammer["damage"] == "2d6 Bludgeoning"
    assert by_name(cole["inventory"], "Potion of Healing")["quantity"] == 2
    assert cole["currency"]["gp"] == 654


def test_wild_shape_forms(cole):
    bear = by_name(cole["creatures"], "Polar Bear")
    assert bear["group"] == "Wild Shape form" and bear["cr"] == "2" and bear["hit_points"] == 42


def test_proficiencies_and_skills(cole):
    p = cole["proficiencies"]
    assert "Shields" in p["armor"] and "Elvish" in p["languages"] and "Darkvision 60 ft" in p["senses"]
    assert "Scimitar" not in p["weapons"]  # Monk weapon proficiencies don't carry over when multiclassing
    assert by_name(cole["skills"], "Perception")["label"] == "+9" and cole["passive_perception"] == 19
    assert by_name(cole["skills"], "Arcana")["label"] == "+6"  # Magician: + Wis modifier, + Luckstone


def test_sanitize_drops_player_notes():
    raw = {"name": "X", "notes": {"backstory": "secret"}, "traits": {"bonds": "secret"},
           "characterValues": [{"typeId": 9, "value": "secret item note"}, {"typeId": 8, "value": "Custom name"}]}
    clean = ddb.sanitize(raw)
    assert "secret" not in json.dumps(clean) and clean["characterValues"] == [{"typeId": 8, "value": "Custom name"}]
    for name in ("cole", "no_name", "big_c"):  # fixtures were saved sanitized
        data = load(name)
        assert "notes" not in data and "traits" not in data
        assert not [v for v in data["characterValues"] if v["typeId"] == 9]


def test_unknown_format_raises_ddb_error():
    with pytest.raises(ddb.DdbError):
        ddb.parse_character({"id": 1})
    assert ddb.parse_character({"name": "X", "classes": "not a list"})["classes"] == []
    with pytest.raises(ddb.DdbError, match="format may have changed"):
        ddb.parse_character({"name": "X", "inventory": [None, 3]})
    minimal = ddb.parse_character({"name": "Bare"})  # missing sections are blanks, not errors
    assert minimal["level"] == 1 and minimal["spells"] == [] and minimal["armor_class"] == 10


def test_ddb_id_from_links():
    assert ddb.ddb_id_from("https://www.dndbeyond.com/characters/75423618") == "75423618"
    assert ddb.ddb_id_from("dndbeyond.com/profile/Jettison/characters/75423618/builder") == "75423618"
    assert ddb.ddb_id_from(" 75423618 ") == "75423618"
    assert ddb.ddb_id_from("https://example.com/characters/1") is None


def test_fetch_errors_are_friendly(monkeypatch):
    def private(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b""))

    monkeypatch.setattr(ddb.urllib.request, "urlopen", private)
    with pytest.raises(ddb.DdbError, match="private"):
        ddb.fetch_character_json("1")

    def timeout(req, timeout):
        raise TimeoutError

    monkeypatch.setattr(ddb.urllib.request, "urlopen", timeout)
    with pytest.raises(ddb.DdbError, match="too long"):
        ddb.fetch_character_json("1")

    class Resp(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    seen = {}

    def ok(req, timeout):
        seen["ua"], seen["timeout"] = req.get_header("User-agent"), timeout
        return Resp(json.dumps({"success": True, "data": {"id": 1, "name": "Pat"}}).encode())

    monkeypatch.setattr(ddb.urllib.request, "urlopen", ok)
    assert ddb.fetch_character_json("1")["name"] == "Pat"
    assert seen["ua"].startswith("askdnd/") and seen["timeout"] == ddb.TIMEOUT_SECONDS
    monkeypatch.setattr(ddb.urllib.request, "urlopen", lambda req, timeout: Resp(b"<html>maintenance</html>"))
    with pytest.raises(ddb.DdbError, match="isn't character data"):
        ddb.fetch_character_json("1")
