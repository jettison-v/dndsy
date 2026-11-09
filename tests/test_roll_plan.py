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
            assert set(p["steps"]) <= {"choose", "attack", "save", "damage", "heal", "apply"}, (who, p["name"])
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


def test_the_unarmed_strike_asks_first(plans):
    p = by(plans, "no_name", "Unarmed Strike")
    assert p["steps"] == ["choose", "attack", "damage", "apply"]
    assert [o["name"] for o in p["choice"]["options"]] == ["Damage", "Grapple", "Shove"] and "(DC 15)" in p["choice"]["options"][1]["says"]
    assert p["attack"] == {"bonus": 7} and (p["damage"][0]["dice"], p["damage"][0]["flat"], p["damage"][0]["type"]) == ("1d8", 4, "bludgeoning")
    assert "Stunning Strike" in [r["name"] for r in p["riders"]]


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
