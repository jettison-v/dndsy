"""Spell components (Brett chose A, B and D, Nov 13, docs/mockups/spell-components/; app/components.py): a spell's
Material component said where it's chosen and cast when the character lacks it or the spell uses it up, never stopping
a cast, and the table's own way as a house rule."""

import json
from pathlib import Path

import pytest

from app import components, ddb, house_rules
from app.importer import import_bundle
from tests.roles import set_role
from tests.table_setup import BUNDLE

ROOT = Path(__file__).resolve().parents[1]


def party(name: str) -> dict:
    return ddb.parse_character(ddb.sanitize(json.loads((ROOT / "tests" / "fixtures" / "ddb" / f"{name}.json").read_text())["data"]))


def spell(sheet: dict, name: str) -> dict:
    return next(s for s in sheet["spells"] if s["name"] == name)


def test_a_components_words_say_its_cost_and_whether_its_used_up():
    m = components.material("diamond dust worth at least 100 gp, which the spell consumes")
    assert m["cost"] == 100 and m["consumed"] and {"diamond", "dust"} <= m["words"]
    m = components.material("a diamond worth 50+ GP")
    assert m["cost"] == 50 and not m["consumed"] and "diamond" in m["words"]
    assert components.material("a melee weapon worth at least 1 sp")["cost"] == pytest.approx(0.1)
    assert components.material("a bit of fleece")["cost"] is None


def test_the_partys_costly_components_are_said():
    """Everyone carries a Component Pouch, so only the costly ones are said: Big C's Greater Restoration needs diamond
    dust he doesn't carry; Trah carries a diamond whose worth D&D Beyond doesn't know; a free one says nothing."""
    big_c, trah = party("big_c"), party("trah")
    assert components.need(spell(big_c, "Greater Restoration"), big_c)["kind"] == "missing"
    assert components.need(spell(big_c, "Bless"), big_c) is None  # (the pouch covers it)
    assert components.need(spell(trah, "Chromatic Orb"), trah)["kind"] == "unsure"


def test_without_a_pouch_or_focus_every_material_component_is_said_unless_the_table_says_otherwise():
    sheet = {"inventory": []}
    bless = {"name": "Bless", "components": ["V", "S", "M"], "material": "a sprinkling of holy water"}
    assert components.need(bless, sheet)["kind"] == "missing"
    assert components.need(bless, sheet, {components.COSTLY_ONLY: True}) is None  # (D: costly only)


def test_a_component_carried_and_used_up_says_so():
    sheet = {"inventory": [{"key": "item:9", "name": "Diamond Dust", "cost": 50, "count": 2}]}
    need = components.need({"components": ["M"], "material": "diamond dust worth at least 100 gp, which the spell consumes"}, sheet)
    assert need == {"kind": "consumes", "says": "uses Diamond Dust (consumed)", "item": "item:9"}


def test_the_dm_sets_the_tables_way_and_only_the_dm(dm, player, db):
    import_bundle(db, BUNDLE)
    set_role(db, "dm@example.com", "dm")
    db.commit()
    house_rules.invalidate()
    assert player.post("/c/main/manage/house-rules/components/costly_only", data={"on": "1"}).status_code == 403
    dm.post("/c/main/manage/house-rules/components/costly_only", data={"on": "1"})
    page = dm.get("/c/main/manage/house-rules").text
    assert 'data-rule="costly_only" aria-checked="true"' in page
    dm.post("/c/main/manage/house-rules/components/costly_only", data={})
    assert 'data-rule="costly_only" aria-checked="false"' in dm.get("/c/main/manage/house-rules").text


def test_the_marks_reach_every_spell_screens_data():
    """A: what Battle's rows, Sheet's spells and the Spell Book draw carries each spell's component: Cole's Find
    Familiar burns incense he doesn't carry (Sheet, the Spell Book); Big C's Greater Restoration is an Action, so his
    Battle row says it too."""
    from app import character_views, spellbook

    cole, big_c = party("cole"), party("big_c")
    by_name = {e["name"]: e for e in spellbook.sheet_entries(cole)}
    assert by_name["Find Familiar"]["need"]["kind"] == "unsure" and by_name["Message"]["need"] is None
    assert any(e["name"] == "Find Familiar" and e["need"] for e in spellbook.entries(cole))
    rows = {o["name"]: o for o in character_views.options(big_c) if o.get("kind") == "spell"}
    assert rows["Greater Restoration"]["need"]["kind"] == "missing"
