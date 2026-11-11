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


def test_an_upcast_spell_has_its_levels_and_their_dice(plans):
    """Cure Wounds at each slot Big C has: the levels are the card's Cast at, not a step of their own (the roll audit,
    Nov 10: Spiritual Weapon's "At what level?" was played as Grapple's choice), and its dice at each level are worked
    out on the server (`effects`), the same as the browser worked them out before (every recipe, every level)."""
    p = by(plans, "big_c", "Cure Wounds")
    assert "choose" not in p["steps"] and p["choice"] is None and p["levels"] == [1, 2, 3] and p["heal"][0]["dice"] == "2d8"
    e = roll_plan.effects(roll_plan.rr.spell("Cure Wounds"), sheet("big_c"), "Cure Wounds", False)
    assert [e["effects"][0]["at"][str(x)]["parts"][0] for x in (1, 2, 3)] == ["2d8", "4d8", "6d8"]
    assert e["effects"][0]["at"]["1"]["parts"][-1] == "+3 spellcasting modifier"


def test_a_cantrip_grows_with_the_character_and_true_strike_waits_for_5():
    rec = {"level": 0, "events": [{"on": "hit", "parts": ["1d10 fire"], "cantrip": "dice"}, {"on": "hit", "parts": ["1d6 radiant"], "cantrip": "extra"}]}
    assert [roll_plan.at_level(rec, rec["events"][0], 0, lv)["parts"] for lv in (1, 5, 11, 17)] == [["1d10 fire"], ["2d10 fire"], ["3d10 fire"], ["4d10 fire"]]
    assert roll_plan.at_level(rec, rec["events"][1], 0, 4) is None and roll_plan.at_level(rec, rec["events"][1], 0, 11)["parts"] == ["2d6 radiant"]


def test_every_roll_button_kind_gets_a_plan_the_card_can_play():
    """Each kind of roll button (app/roll_plan.py `button`): what the card plays, decided here, never in the browser."""
    b = roll_plan.button
    assert b("check", "Stealth check", "+6")["adv_keys"] == ["check", "check:dex", "d20"] and b("check", "Stealth check", "+6")["bonus"] == 6
    assert b("check", "Initiative", "+3")["adv_keys"][0] == "initiative" and "Surprised" in b("check", "Initiative", "+3")["notes"][0]
    assert b("save", "Con save", "+2")["play"] == "d20" and "Concentration" in b("save", "Con save", "+2")["notes"][0]
    assert b("death", "Death save")["play"] == "death" and b("heal", "Hit Point Die", "", "1d8+1")["play"] == "single"
    assert b("damage", "Fireball", save="Dex 15")["save"] == {"ability": "Dex", "dc": 15, "success": ""}
    assert b("attack", "Unarmed Strike", "+5", "1")["flat"] == 1 and b("dice", "Dice")["play"] == "single"


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


def test_riders_are_only_the_ones_that_can_apply(plans):
    from app.character_views import options

    """The roll audit (Nov 10): Eldritch Blast's card listed Savage Attacker, Stunning Strike and Empowered Strikes
    (a weapon's or an Unarmed Strike's), and the Maul's listed Guided Strike and Favored by the Gods under On a hit.
    Each rider applies where its own words say, at the time they say; one that's already a pill isn't said again."""
    blast = {r["name"] for r in by(plans, "no_name", "Eldritch Blast")["riders"]}
    assert not blast & {"Savage Attacker", "Stunning Strike", "Empowered Strikes"}
    strike = {r["name"] for r in by(plans, "no_name", "Unarmed Strike")["riders"]}
    assert {"Stunning Strike", "Empowered Strikes"} <= strike
    assert "Stunning Strike" not in {r["name"] for r in by(plans, "no_name", "Dart")["riders"]}  # (not a Monk weapon)
    assert "Stunning Strike" in {r["name"] for r in by(plans, "no_name", "Vicious Quarterstaff")["riders"]}
    maul = next(p for p in plans["big_c"] if p["name"].startswith("Hammer of Thunderbolts"))
    when = {r["name"]: r["when"] for r in maul["riders"]}
    assert when.get("Savage Attacker") == "hit" and "Favored by the Gods" not in when
    assert "Guided Strike" not in when  # (Brett's Roll Audit comment, Nov 10: chosen with the to-hit, so a pill there)
    guided = next(m for m in maul["modifiers"] if m.get("short") == "Guided Strike")
    assert guided["when"] == "after_roll" and guided["adds"] == "10"
    # (what it goes with is the rules book's `with`, matched against the attack's traits: no reading of words)
    nn = sheet("no_name")
    dart = next(o for o in options(nn, set()) if o["name"] == "Dart")
    assert roll_plan.traits(nn, dart, "weapon") == {"weapon", "ranged_weapon", "finesse"} - {"ranged_weapon"} | {"melee_weapon"}
    assert roll_plan.applies({"with": ["melee_weapon", "unarmed"]}, {"unarmed"}) and not roll_plan.applies({"with": ["spell"]}, {"weapon"})
    assert roll_plan.applies({}, {"spell"})  # (no `with`: any attack)


def test_a_spell_that_only_adds_to_hits_rolls_that_damage():
    """The every-roll test (Nov 10): Hunter's Mark's and Absorb Elements' Roll had nothing to roll, and askdnd refused it."""
    e = roll_plan.effects(roll_plan.rr.spell("Hunter's Mark"), sheet("no_name"), "Hunter's Mark", False)
    assert e["effects"][0]["on"] == "rider" and e["effects"][0]["at"] == {"1": {"parts": ["1d6 force"], "count": 1, "text": "1d6 force"}}


def test_healing_that_only_heals_yourself_says_so(plans):
    """Brett's Roll Audit comment (Nov 10): the plan of a heal only its roller takes carries `self`, so its roll offers
    Apply to for that character alone."""
    meta = next(p for p in roll_plan.plans(sheet("cole")) if p["name"] == "Uncanny Metabolism")
    from app.character_views import option_rolls, options
    o = next(o for o in options(sheet("cole"), set()) if o["name"] == "Uncanny Metabolism")
    import json as _json
    plan = _json.loads(option_rolls(o)[-1]["attrs"]["plan"])
    assert plan["self"] is True and meta["heal"]
    assert roll_plan.button("heal", "Hit Point Die", "", "1d8+1", self_only=True)["self"] is True
    assert "self" not in roll_plan.button("heal", "Healing Word", "", "2d4+4")


def test_a_rider_with_a_kind_is_something_the_card_can_press(plans):
    """Riders on a Hit (Brett, Nov 10, docs/mockups/rider-actions/): a rider is one of a few kinds the card plays (adds
    dice, asks for a save, changes the damage), with what it costs; the rest stay words."""
    strike = {r["name"]: r.get("act") for r in by(plans, "no_name", "Unarmed Strike")["riders"]}
    stun = strike["Stunning Strike"]
    assert stun["kind"] == "save" and stun["save"] == "Con" and isinstance(stun["dc"], int)
    assert stun["spend"]["name"] == "Focus Points" and stun["spend"]["field"].startswith("uses:") and stun["spend"]["left"] >= 0
    assert strike["Empowered Strikes"] == {"kind": "change", "type": "force"}
    maul = next(p for p in plans["big_c"] if p["name"].startswith("Hammer of Thunderbolts"))
    acts = {r["name"]: r.get("act") for r in maul["riders"]}
    assert acts["Savage Attacker"] == {"kind": "change", "twice": True}
    smite = acts["Divine Smite"]  # a spell cast right after a hit (its recipe's on_hit): its dice at the slots it can use
    assert smite["kind"] == "dice" and smite["cast"]["time"] == "Bonus Action" and smite["cast"]["key"] == "spell:Divine Smite"
    levels = {str(w["level"]) for w in smite["cast"]["ways"]}
    assert levels and set(smite["rolls"]["effects"][0]["at"]) <= levels | {"1"}
    assert smite["rolls"]["effects"][0]["at"]["2"]["parts"] == ["3d8 radiant"]
    assert roll_plan.rider_act({}, {"kind": "words"}) is None and roll_plan.rider_act({}, {"kind": "save", "dc": "x"}) is None


def test_what_adds_to_a_spells_damage_is_offered_where_it_applies():
    """Brett, Nov 10 (what's left to complete rolls): a modifier to spell damage (a Chromatic Dragon-Touched Focus, marked
    by its player: a d6 when a slot is used on acid, cold, fire, lightning or poison damage) is on those spells' plans,
    never a cantrip's or another damage type's; a type the caster picks (Chromatic Orb) counts."""
    s = sheet("trah")
    focus = next(i for i in s["inventory"] if "Dragon-Touched" in i["name"])
    s["_item_choices"] = {focus["key"].split(":", 1)[1]: "Chromatic"}
    got = {p["name"]: [m["name"] for m in p["modifiers"] if m["when"] == "on_damage"] for p in roll_plan.plans(s)}
    assert all(got[n] == ["Dragon-Touched Focus: Chromatic"] for n in ("Fireball", "Burning Hands", "Chromatic Orb"))
    assert got["Fire Bolt"] == [] and got["Magic Missile"] == [] and got["Raulothim's Psychic Lance"] == []
    assert not any(m["when"] == "on_damage" for p in roll_plan.plans(sheet("trah")) for m in p["modifiers"])  # (unmarked: none)
