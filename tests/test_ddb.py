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


# Expected numbers below are what D&D Beyond's own sheet showed for these characters
# on 2026-10-16 (checked side by side), not what we think the rules say.


def test_ability_scores_follow_d_and_d_beyond(cole, big_c):
    scores = {a["short"]: (a["score"], a["label"]) for a in cole["abilities"]}
    # Legacy Wood Elf increases are ignored because the 2024 Wayfarer background gives them
    assert scores["Wis"] == (19, "+4")  # 15 + War Caster + Wayfarer (+2/+1)
    assert scores["Dex"] == (15, "+2")  # 13 + Manual of Quickness of Action (equipped)
    # Belt of Hill Giant Strength sets 21; Hammer of Thunderbolts stacks +4 on top
    assert by_name(big_c["abilities"], "Strength")["score"] == 25


def test_hp_ac_speed(cole, no_name, big_c):
    assert cole["armor_class"] == 16  # Monk Unarmored Defense: 10 + Dex + Wis
    assert cole["initiative"] == "+3"  # Dex +2, Luckstone +1 (counted once)
    assert cole["speed"]["walk"] == 45  # Fleet of Foot 35 + Unarmored Movement 10
    assert cole["hit_points"]["max"] == 51
    assert no_name["hit_points"]["max"] == 75  # includes Tough (+2 per level)
    assert big_c["armor_class"] == 19  # plate 18 + Defense fighting style
    assert big_c["speed"]["walk"] == 30  # Unarmored Movement doesn't apply to Monks only; Big C isn't one


def test_multiclass_saves_come_from_the_first_class_only(cole, big_c):
    saves = {s["short"]: s for s in cole["saves"]}
    assert saves["Wis"]["proficient"] and saves["Int"]["proficient"]
    assert not saves["Str"]["proficient"] and not saves["Dex"]["proficient"]  # Monk was the second class
    assert saves["Wis"]["label"] == "+8"  # +4 Wis, +3 proficiency, +1 Luckstone
    big = {s["short"]: s for s in big_c["saves"]}
    assert big["Cha"]["proficient"] and not big["Con"]["proficient"]  # Sorcerer was the second class
    assert big["Str"]["label"] == "+10"  # +7 Str, +3 Aura of Protection  # Aura of Protection adds Cha to every save


def test_spell_slots_single_multiclass_and_pact(cole, no_name, big_c):
    assert [(s["level"], s["max"]) for s in cole["spell_slots"]["slots"]] == [(1, 4), (2, 3), (3, 3)]
    assert big_c["spell_slots"]["slots"][2] == {"level": 3, "max": 2, "used": 0}  # Paladin 6 + Sorcerer 2 = caster level 5
    assert no_name["spell_slots"]["slots"] == [] and no_name["spell_slots"]["pact"] == {"level": 1, "max": 2, "used": 0}
    assert cole["spellcasting"] == [{"class": "Druid", "ability": "Wisdom", "save_dc": 15, "attack": "+7"}]


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
    # Shortbow is covered by Simple Weapons; Scimitar is listed as a Monk weapon
    assert p["weapons"] == ["Longbow", "Longsword", "Scimitar", "Shortsword", "Simple Weapons"]
    assert by_name(cole["skills"], "Perception")["label"] == "+8" and cole["passive_perception"] == 18
    assert by_name(cole["skills"], "Arcana")["label"] == "+5"  # Magician: + Wis modifier, + Luckstone


def test_sanitize_drops_player_notes_but_keeps_the_backstory():
    raw = {"name": "X", "notes": {"backstory": "Born at sea.", "allies": "secret", "otherNotes": "secret"},
           "traits": {"bonds": "My ship."},
           "characterValues": [{"typeId": 9, "value": "secret item note"}, {"typeId": 8, "value": "Custom name"}]}
    clean = ddb.sanitize(raw)
    assert "secret" not in json.dumps(clean) and clean["characterValues"] == [{"typeId": 8, "value": "Custom name"}]
    assert clean["notes"] == {"backstory": "Born at sea."} and clean["traits"] == {"bonds": "My ship."}
    for name in ("cole", "no_name", "big_c", "trah"):  # fixtures hold none of the player's writing (they're in git)
        data = load(name)
        assert "notes" not in data and "traits" not in data
        assert not [v for v in data["characterValues"] if v["typeId"] == 9]
        assert not [c for c in data["customItems"] if "notes" in c]


def test_sanitize_keeps_only_which_items_have_notes():
    raw = {"name": "X", "inventory": [{"id": 7, "definition": {"name": "Flask"}}],
           "characterValues": [{"typeId": 9, "valueId": 7, "value": "secret item note"}],
           "customItems": [{"id": 1, "name": "Egg", "description": "Golden.", "notes": "secret custom note"}]}
    clean = ddb.sanitize(raw)
    assert "secret" not in json.dumps(clean) and clean["customItems"][0]["description"] == "Golden."
    assert clean["noteItemIds"] == ["custom:1", "item:7"]
    # The notes themselves are taken out separately (stored in character_item_notes, never in git)
    assert ddb.item_notes(raw) == [{"ref": "item:7", "name": "Flask", "note": "secret item note"},
                                   {"ref": "custom:1", "name": "Egg", "note": "secret custom note"}]


def test_custom_and_changed_items_are_marked(cole):
    items = {x["name"]: x for x in cole["inventory"]}
    egg = items["Golden Dragon Egg"]
    assert egg["custom"] and egg["key"].startswith("custom:") and egg["type"] == "Custom item" and not egg["changes"]
    mask = items["Mind Control Mask"]
    assert mask["text"].startswith("Took off a young woman") and "Trah analysized" not in json.dumps(cole)  # a custom item's note
    flask = items["Flask (blessed water)"]
    assert not flask["custom"] and flask["base_name"] == "Flask"
    assert flask["changes"] == ["Renamed (the D&D Beyond item is Flask)", "Has a note from the player (below)"]
    assert items["Ruby"]["changes"] == ["Other details changed on D&D Beyond (such as cost or weight)"]
    assert not items["Bag of Holding"]["changes"] and not items["Bag of Holding"]["custom"]


def test_portrait_comes_from_d_and_d_beyond_only(cole):
    assert cole["portrait"].startswith("https://www.dndbeyond.com/avatars/")
    assert ddb.parse_character({**load("cole"), "decorations": {"avatarUrl": "https://evil.example/x.png"}})["portrait"] == ""


def test_spell_lists_match_d_and_d_beyond(cole, no_name):
    trah = ddb.parse_character(load("trah"))
    moon = by_name(cole["spells"], "Moonbeam")  # Circle of the Moon spell, fetched separately
    assert moon["always_prepared"] and moon["sources"] == ["Druid"]
    assert {"Starry Wisp", "Conjure Animals", "Cure Wounds"} <= {s["name"] for s in cole["spells"]}
    names = {s["name"] for s in no_name["spells"]}
    assert "Enlarge/Reduce" not in names  # from a Potion of Growth that isn't equipped
    trah_names = {s["name"] for s in trah["spells"]}
    assert "Fireball" in trah_names and "Knock" not in trah_names  # a wizard's unprepared spellbook spells
    assert "Mage Hand" in trah_names  # cantrips are always shown


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


def test_fetch_character_adds_always_prepared_spells_and_tolerates_failure(monkeypatch):
    base = {"id": 1, "name": "Pat", "classes": [{"level": 6, "definition": {"id": 10}, "subclassDefinition": {"id": 20}}]}
    monkeypatch.setattr(ddb, "fetch_character_json", lambda _id, timeout=ddb.TIMEOUT_SECONDS: dict(base))

    def extra(url, timeout):
        if "classId=10" in url:
            raise OSError("down")
        return {"success": True, "data": [{"definition": {"name": "Moonbeam", "level": 2}}]}

    monkeypatch.setattr(ddb, "_get_json", extra)
    data = ddb.fetch_character("1")
    assert data["askdnd"]["alwaysPreparedSpells"] == {"20": [{"definition": {"name": "Moonbeam", "level": 2}}]}


def test_attacks_match_d_and_d_beyond(cole, no_name, big_c):
    trah = ddb.parse_character(load("trah"))
    got = {(s["name"], a["name"]): (a["to_hit"], a["damage"]) for s in (cole, no_name, big_c, trah) for a in s["attacks"]}
    assert got[("Cole Lockhard", "Unarmed Strike")] == ("+6", "1d6+3 bludgeoning")  # Martial Arts die + Insignia of Claws
    assert got[("NaN", "Vicious Quarterstaff")] == ("+7", "1d8+4 bludgeoning")  # Monk weapon uses the Martial Arts die
    assert got[("NaN", "Dart")] == ("+7", "1d4+4 piercing")
    assert got[("Cecilas Steiner", "Hammer of Thunderbolts (Maul)")] == ("+11", "2d6+8 bludgeoning")  # +1 weapon
    assert got[("Cecilas Steiner", "Unarmed Strike")] == ("+10", "8 bludgeoning")
    assert got[("Trah Belosity", "Shortsword")] == ("+5", "1d6+2 piercing")


def test_spell_attacks_saves_and_cantrip_scaling(cole, no_name):
    wisp = by_name(cole["spells"], "Starry Wisp")
    assert wisp["attack"] == "+7" and wisp["damage"] == "2d8 radiant"  # cantrip at level 8: two dice
    assert by_name(cole["spells"], "Moonbeam")["save"] == "Con 15"
    assert by_name(cole["spells"], "Healing Word")["healing"] == "2d4"
    assert by_name(no_name["spells"], "Eldritch Blast")["damage"] == "1d10 force"  # adds beams instead of dice
    assert "Healing" in by_name(cole["spells"], "Healing Word")["tags"]


def test_situational_rules_and_save_notes(cole):
    texts = {x["text"]: x for x in cole["situational"]}
    charmed = texts["Advantage on saving throws against being charmed"]
    assert charmed["kind"] == "advantage" and charmed["source"] == "Fey Ancestry"
    assert "Advantage on Constitution saving throws that you make to maintain Concentration" in texts
    assert texts["Immune to magical sleep"]["kind"] == "immunity"
    absorb = next(x for x in cole["situational"] if x["key"] == "spell:Absorb Elements")
    assert absorb["kind"] == "reaction" and "acid, cold, fire" in absorb["text"]
    assert cole["save_notes"] == ["Advantage on saving throws against being charmed"]
    assert {s["short"]: s["notes"] for s in cole["saves"]}["Con"] == ["Adv. to maintain Concentration"]


def test_items_usable_in_battle_and_keys(cole):
    potion = by_name(cole["inventory"], "Potion of Healing")
    assert potion["battle"] and potion["key"].startswith("item:")
    assert not by_name(cole["inventory"], "Bag of Holding")["battle"]
    assert all(x["key"] for x in cole["actions"] + cole["spells"] + cole["features"] + cole["creatures"])


def test_spellbook_for_the_planner(cole, big_c):
    trah = ddb.parse_character(load("trah"))
    druid = cole["spellbook"][0]
    states = {sp["name"]: sp["state"] for sp in druid["spells"]}
    assert states["Moonbeam"] == "always" and states["Heat Metal"] == "prepared" and states["Mending"] == "known"
    assert states["Barkskin"] == "available"  # on the Druid list, not prepared
    assert (druid["prepared_count"], druid["prepared_max"], druid["cantrips_count"], druid["cantrips_max"]) == (10, 10, 3, 3)
    wizard = trah["spellbook"][0]
    w = {sp["name"]: sp["state"] for sp in wizard["spells"]}
    assert w["Fireball"] == "prepared" and w["Knock"] == "spellbook" and wizard["spellbook"]
    paladin = big_c["spellbook"][0]
    assert {sp["name"]: sp["state"] for sp in paladin["spells"]}["Command"] == "always"  # Oath Spells
    assert (paladin["prepared_count"], paladin["prepared_max"]) == (4, 6)  # Oath Spells don't count toward the 6


def test_features_split_into_usable_and_always_on(cole):
    use = {f["name"]: f["use"] for f in cole["features"]}
    assert use["Wild Shape"] and use["Mask of the Wild"] and use["War Caster"] and use["Circle of the Moon Spells"]
    assert not use["Fleet of Foot"] and not use["Keen Senses"] and not use["Unarmored Defense"]


def test_dndbeyond_formulas_are_filled_in():
    v = {"classlevel": 6, "proficiency": 3, "modifier:wis": 4, "modifier:dex": 2, "scalevalue": "1d6"}
    r = ddb.render_template
    assert r("for {{(classlevel/2)@rounddown}} hours", v) == "for 3 hours"
    assert r("AC {{(13+modifier:wis)#unsigned}}", v) == "AC 17"
    assert r("AC {{10+modifier:dex+modifier:wis#unsigned}}", v) == "AC 16"
    assert r("regain {{scalevalue}}{{classlevel#signed}} HP", v) == "regain 1d6+6 HP"
    assert r("{{modifier:cha@min:1#unsigned}}", v) == "(see D&D Beyond)"  # unknown value: say so, don't guess
    assert r("CR {{(classlevel/3)@rounddown}}", v) == "CR 2" and r("{{(classlevel/4)@roundup}}", v) == "2"
