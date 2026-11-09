"""The roll plan (app/roll_plan.py; Brett chose the Roll Card Prototype, Nov 9, and asked how every rolling action gets the
right metadata): each Battle option on the party's saved sheets has a plan the roll card can play, every gap is known
with what fills it, and docs/rules/roll-coverage.md says where each stands."""

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from app import ddb, roll_plan

ROOT = Path(__file__).resolve().parents[1]
PARTY = ["big_c", "cole", "no_name", "trah"]


def sheet(name: str) -> dict:
    return ddb.parse_character(ddb.sanitize(json.loads((ROOT / "tests" / "fixtures" / "ddb" / f"{name}.json").read_text())["data"]))


@pytest.fixture(scope="module")
def plans() -> dict[str, list[dict]]:
    return {n: roll_plan.plans(sheet(n)) for n in PARTY}


def by(plans, who, name):
    return next(p for p in plans[who] if p["name"] == name)


def test_every_plan_is_one_the_card_can_play(plans):
    for who, ps in plans.items():
        for p in ps:
            assert p["status"] in ("ready", "unchecked", "gap", "no roll"), (who, p["name"])
            assert set(p["steps"]) <= {"choose", "attack", "save", "damage", "heal", "apply", "modify"}, (who, p["name"])
            assert ("attack" in p["steps"]) == bool(p["attack"]) and ("save" in p["steps"]) == bool(p["save"]), (who, p["name"])
            if p["attack"]:
                assert isinstance(p["attack"]["bonus"], int), (who, p["name"])
            if p["save"]:
                assert re.fullmatch(r"Str|Dex|Con|Int|Wis|Cha", p["save"]["ability"]) and p["save"]["dc"], (who, p["name"])
            for part in p["damage"] + p["heal"]:
                assert part["dice"] or isinstance(part["flat"], int), (who, p["name"], part)  # (Trah's Unarmed Strike: 1 + Str −1 = 0)
                assert not part["dice"] or re.fullmatch(r"\d+d\d+", part["dice"]), (who, p["name"], part)
            if p["damage"] or p["heal"]:
                assert p["steps"][-1] == "apply", (who, p["name"])
            assert set(p["sources"].values()) <= {"correction", "checked", "sheet", "rule", "ddb", "text"}, (who, p["name"])


def test_every_gap_is_known_with_what_fills_it(plans):
    """A new rolling action with dice the plan doesn't roll fails here: give it a plan, or say what fills it in
    roll_plan.KNOWN_GAPS. One that's filled comes off the list."""
    gaps = {p["name"] for ps in plans.values() for p in ps if p["status"] == "gap"}
    assert gaps - set(roll_plan.KNOWN_GAPS) == set(), "Gaps with no reason: give them a plan or a KNOWN_GAPS line"
    assert set(roll_plan.KNOWN_GAPS) - gaps == set(), "Filled: take them off KNOWN_GAPS"
    assert gaps == set() and not [p for ps in plans.values() for p in ps if p["status"] == "unchecked"]  # (Nov 9: every party roll checked)


def test_the_unarmed_strike_asks_first(plans):
    p = by(plans, "no_name", "Unarmed Strike")
    assert p["steps"] == ["choose", "attack", "damage", "apply"]
    assert [o["name"] for o in p["choice"]["options"]] == ["Damage", "Grapple", "Shove"] and "(DC 15)" in p["choice"]["options"][1]["says"]
    assert p["attack"] == {"bonus": 7} and (p["damage"][0]["dice"], p["damage"][0]["flat"], p["damage"][0]["type"]) == ("1d8", 4, "bludgeoning")
    assert "Stunning Strike" in [r["name"] for r in p["riders"]]


def test_a_mastered_weapon_says_its_mastery(plans):
    """Feedback (Nov 9): the roll card left out what the roll window's row says, a weapon's mastery (Trah's Shortsword:
    Vex). It's a rider in words, on a hit; Graze's is on a miss."""
    vex = [r for r in by(plans, "trah", "Shortsword")["riders"] if r["on"] == "mastery"]
    assert vex == [{"name": "Vex", "when": "hit", "says": roll_plan.class_rules.MASTERIES["Vex"], "on": "mastery"}]
    graze = roll_plan.plan({}, {"name": "Greatsword", "hit": "+5", "kind": "attack", "dice": "2d6", "tags": ["Mastery: Graze"]})
    assert [(r["name"], r["when"]) for r in graze["riders"]] == [("Graze", "miss")]
    assert not roll_plan.plan({}, {"name": "Club", "hit": "+5", "kind": "attack", "dice": "1d4", "tags": ["Mastery: Nonsense"]})["riders"]


def test_a_checked_recipe_decides_attack_or_save():
    """Inflict Wounds: D&D Beyond's sheet has the 2014 attack roll, the 2024 rules a Constitution save."""
    p = next(p for p in roll_plan.plans(sheet("big_c")) if p["name"] == "Inflict Wounds")
    assert p["attack"] is None and p["save"]["ability"] == "Con" and p["save"]["dc"] == 14 and p["status"] == "ready"
    assert "the 2024 rules make it a save" in p["notes"][0]


def test_an_upcast_spell_asks_its_level_first(plans):
    p = by(plans, "big_c", "Cure Wounds")
    assert p["steps"][0] == "choose" and [o["name"] for o in p["choice"]["options"]] == ["1", "2", "3"] and p["heal"][0]["dice"] == "2d8"


def test_the_coverage_report_is_current():
    """docs/rules/roll-coverage.md is what scripts/roll_coverage.py writes for the party's sheets."""
    before = (ROOT / "docs" / "rules" / "roll-coverage.md").read_text()
    subprocess.run([sys.executable, str(ROOT / "scripts" / "roll_coverage.py")], check=True, capture_output=True, cwd=ROOT)
    assert (ROOT / "docs" / "rules" / "roll-coverage.md").read_text() == before, "Run scripts/roll_coverage.py"


def test_spells_from_other_books_roll_as_their_own_words_say(plans):
    """The table's sheets have spells from older books (Xanathar's, Tasha's, the 2014 PHB): checked recipes, by hand."""
    smite = by(plans, "big_c", "Branding Smite")
    assert smite["riders"] and smite["riders"][0]["parts"][0]["dice"] == "2d6" and "damage" not in smite["steps"]  # (on the next hit, not on casting)
    depth = by(plans, "cole", "Depth Charge")
    assert depth["save"]["ability"] == "Con" and depth["damage"][0]["dice"] == "7d6" and depth["alternatives"][0]["parts"][0]["dice"] == "9d6"
    lance = by(plans, "trah", "Raulothim's Psychic Lance")
    assert lance["save"] == {"ability": "Int", "dc": 15, "success": "half"} and lance["status"] == "ready"


def test_features_roll_their_own_shape_with_the_sheets_numbers(plans):
    um = by(plans, "no_name", "Uncanny Metabolism")
    assert um["steps"] == ["heal", "apply"] and (um["heal"][0]["dice"], um["heal"][0]["flat"]) == ("1d8", 6)  # Martial Arts die + Monk 6
    redirect = by(plans, "no_name", "Deflect Attack: Redirect Attack")
    assert redirect["save"]["ability"] == "Dex" and redirect["save"]["dc"] == 14 and (redirect["damage"][0]["dice"], redirect["damage"][0]["flat"]) == ("2d8", 4)
    assert roll_plan.fill("{sneak}d6", {"classes": [{"name": "Rogue", "level": 5}]}) == "3d6"
    assert roll_plan.fill("{lands_aid}d6 necrotic", {"classes": [{"name": "Druid", "level": 10}]}) == "3d6 necrotic"


def test_what_changes_another_roll_is_a_modifier(plans):
    """Guidance, Favored by the Gods, Deflect Attacks: the card's pills (Brett's prototype), never a roll of their own."""
    g = by(plans, "cole", "Guidance")
    assert g["steps"] == ["modify"] and g["modifier"]["when"] == "before" and g["modifier"]["to"] == ["check"] and g["modifier"]["adds"] == "1d4"
    favored = by(plans, "big_c", "Favored by the Gods")
    assert favored["modifier"]["when"] == "after_fail" and favored["modifier"]["adds"] == "2d4"
    assert "Favored by the Gods" in [m["name"] for m in by(plans, "big_c", "Hammer of Thunderbolts (Maul)")["modifiers"]]
    deflect = by(plans, "no_name", "Deflect Attack")
    assert deflect["modifier"]["when"] == "damage_taken" and deflect["modifier"]["reduces"].startswith("1d10")
