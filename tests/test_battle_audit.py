"""Battle's columns and On a hit against each feature's own text (feedback 15, Nov 5; scripts/battle_audit.py): the
party's saved sheets audit clean, and the round's three fixes hold."""

import importlib.util
import json
from pathlib import Path

import pytest

from app import character_views as views
from app import class_rules, ddb

HERE = Path(__file__).parent


def sheet_of(name: str) -> dict:
    d = json.loads((HERE / "fixtures" / "ddb" / f"{name}.json").read_text())
    return ddb.parse_character(ddb.sanitize(d.get("data", d)))


def _audit():
    spec = importlib.util.spec_from_file_location("battle_audit", HERE.parent / "scripts" / "battle_audit.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.audit


@pytest.mark.parametrize("name", ["cole", "trah", "no_name", "big_c"])
def test_the_partys_battle_matches_what_each_feature_says(name):
    assert _audit()(sheet_of(name)) == []


def test_an_action_d_and_d_beyond_calls_special_goes_where_its_text_says():
    """Big C's Conquering Presence: "Special" on D&D Beyond, "As an action" in its text."""
    s = sheet_of("big_c")
    o = next(o for o in views.options(s) if o["name"] == "Channel Divinity: Conquering Presence")
    assert o["cost"] == "Action" and o["cost_from"] == "text"
    assert views.stated_cost("As a Bonus Action, you can…") == "Bonus action" and views.stated_cost("It has no action.") is None


def test_find_familiar_is_a_magic_action_with_wild_companion_or_pact_of_the_chain():
    s = sheet_of("cole")
    s["features"] = [f for f in s.get("features") or [] if f["name"] not in ("Wild Companion", "Pact of the Chain")]
    s["spells"] = [x for x in s.get("spells") or [] if x["name"] != "Find Familiar"] + [
        {"key": "spell:Find Familiar", "name": "Find Familiar", "level": 1, "casting_time": "1 hour", "summary": "", "text": ""}]
    assert not any(o["name"] == "Find Familiar" for o in views.options(s))  # (an hour, without either)
    s["features"] = [*(s.get("features") or []), {"name": "Wild Companion", "text": ""}]
    o = next(o for o in views.options(s) if o["name"] == "Find Familiar")
    assert o["cost"] == "Action" and o["cast"] and "Wild Companion" in o["meta"]


def test_the_tables_2014_subclasses_have_their_extras_on_a_hit():
    assert {"Guided Strike", "Favored by the Gods"} <= {r["name"] for r in class_rules.turn(sheet_of("big_c"))["riders"]}
    vi = {"classes": [{"name": "Artificer", "subclass": "Artillerist", "level": 10}], "abilities": []}
    assert "Arcane Firearm" in {r["name"] for r in class_rules.turn(vi)["riders"]}
