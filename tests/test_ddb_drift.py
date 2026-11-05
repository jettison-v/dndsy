"""scripts/ddb_drift.py: telling D&D Beyond changing its sheet from what's simply not on these sheets."""

import importlib.util
from pathlib import Path


def _drift():
    spec = importlib.util.spec_from_file_location("ddb_drift", Path(__file__).parent.parent / "scripts" / "ddb_drift.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_a_renamed_or_retyped_field_is_drift_and_an_empty_part_isnt():
    d = _drift()
    copies = d.shape({"weight": 12, "stats": [{"id": 1, "value": 10}], "customItems": [{"name": "Rope"}], "askdnd": {"x": 1},
                      "race": {"fullName": "Elf", "subRaceShortName": "High"}})
    today = d.shape({"carried": 12, "stats": [{"id": 1, "value": "10"}], "customItems": [], "race": {"fullName": "Elf", "subRaceShortName": None}})
    gone, changed = d.compare(copies, today)
    assert gone == [".weight"]  # (not the custom item's name: these sheets have none; not askdnd's own; null is still there)
    assert changed == [".stats[].value: int → str"]


def test_a_parsed_sheet_missing_what_every_character_has_is_said():
    d = _drift()
    full = {"name": "Levi", "level": 8, "hit_points": {"max": 59}, "armor_class": 13, "abilities": [0] * 6, "saves": [0] * 6,
            "skills": [0] * 18, "classes": ["Druid"], "actions": ["Wild Shape"], "inventory": ["Staff"], "spells": ["Entangle"]}
    assert d.essentials(full) == []
    assert d.essentials({**full, "armor_class": None, "skills": []}) == ["Armor Class", "eighteen skills"]
