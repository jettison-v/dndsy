"""The live test's reading of D&D Beyond's record (scripts/real_table.py, run on the Mac Mini): a run's change is seen,
and D&D Beyond's own rebuilding after a save isn't taken for one (Nov 10: the twins' give-back checks missed on it)."""
import copy
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import real_table as rt  # noqa: E402


def spell(name: str, component: int, used: int = 0) -> dict:
    return {"id": None, "componentId": component, "componentTypeId": 12168134, "definition": {"id": component * 10, "name": name},
            "limitedUse": {"numberUsed": used}}


def record() -> dict:
    return {"spellSlots": [{"level": 1, "used": 0}, {"level": 2, "used": 0}],
            "spells": {"class": [spell("Find Steed", 1), spell("Find Steed", 1), spell("Command", 2), spell("Divine Smite", 3)],
                       "race": [spell("Hellish Rebuke", 4)]},
            "actions": {"class": [{"id": "a1", "limitedUse": {"numberUsed": 0}}, {"id": "a2", "limitedUse": {"numberUsed": 0}}]},
            "choices": {"definitionKeyNameMap": {"feat:1": "Tough"}}}


def test_a_spent_slot_is_a_change_and_putting_it_back_undoes_it():
    before, after = record(), record()
    after["spellSlots"][0]["used"] = 1
    assert rt.steady(rt.changes(before, after)) == [(".spellSlots[0].used", 0, 1)]
    assert not rt.steady(rt.changes(before, record()))


def test_d_and_d_beyonds_own_rebuilding_is_not_a_change():
    """After a save D&D Beyond lists granted spells with more or fewer duplicate copies, and looks choices' names up anew."""
    before, after = record(), record()
    after["spells"]["class"] = after["spells"]["class"][1:] + [spell("Divine Smite", 3)]  # (one Find Steed less, a second Smite)
    after["actions"]["class"].append({"id": "a1", "limitedUse": {"numberUsed": 0}})
    after["choices"]["definitionKeyNameMap"] = {"feat:2": "Lucky"}
    diff = rt.changes(before, after)
    assert diff and not rt.steady(diff)


def test_a_change_inside_a_rebuilt_list_is_still_seen():
    """A slot or a use spent while D&D Beyond also rebuilds the list it sits in."""
    before = record()
    after = copy.deepcopy(before)
    after["spells"]["class"].append(spell("Find Steed", 1))
    after["actions"]["class"][1]["limitedUse"]["numberUsed"] = 1
    after["spells"]["race"][0]["limitedUse"]["numberUsed"] = 1
    after["spells"]["class"][2]["limitedUse"]["numberUsed"] = 1  # (Command, its own use)
    kept = rt.steady(rt.changes(before, after))
    assert sorted(p for p, _, _ in kept) == [".actions.class[1].limitedUse.numberUsed",
                                            ".spells.class[Command#0].limitedUse.numberUsed",
                                            ".spells.race[0].limitedUse.numberUsed"]


def test_a_new_entry_elsewhere_is_still_a_change():
    """Only granted spells and actions are rebuilt: an item added to the inventory is a run's change."""
    before, after = record(), record()
    before["inventory"] = [{"id": 1, "quantity": 1}]
    after["inventory"] = [{"id": 1, "quantity": 1}, {"id": 2, "quantity": 1}]
    assert [p for p, _, _ in rt.steady(rt.changes(before, after))] == [".inventory{+}"]
