"""The action widgets (roadmap 8, docs/plans/2026-11-05-action-widgets.md): what an action costs travels with its roll,
so the roll card spends it as it's rolled (Brett, Nov 13: Flurry of Blows showed its Focus Point and didn't spend it).
tests/browser/test_action_widgets.py spends it in a real page, with Undo."""

import json
from pathlib import Path

import pytest

from app import character_views as cv
from app import ddb

ROOT = Path(__file__).resolve().parents[1]


def rows(name: str) -> dict:
    sheet = ddb.parse_character(ddb.sanitize(json.loads((ROOT / "tests" / "fixtures" / "ddb" / f"{name}.json").read_text())["data"]))
    return {o["name"]: o for o in cv.planned(sheet, cv.options(sheet))}


def first_pay(o: dict):
    """What the option's first roll button says making it spends."""
    button = next(r for r in cv.option_rolls(o) if r.get("attrs"))
    return json.loads(button["attrs"]["plan"]).get("pay")


@pytest.mark.parametrize(("who", "row", "label"), [("cole", "Flurry of Blows", "1 Focus Point"), ("trah", "Second Wind", "1 use of Second Wind")],
                         ids=["flurry", "second-wind"])
def test_a_rows_cost_rides_on_its_first_roll(who, row, label):
    """Flurry of Blows spends the Focus Point it says it expends; Second Wind its own use. Only the first button
    carries it (an attack's damage is part of the same roll), as Use one's count, whose Undo is that window's."""
    o = rows(who)[row]
    pay = first_pay(o)
    assert [(p["label"], p["n"]) for p in pay] == [(label, 1)] and pay[0]["field"].startswith("uses:")
    assert all("pay" not in json.loads(r["attrs"]["plan"]) for r in cv.option_rolls(o)[1:] if r.get("attrs"))


def test_a_spell_or_a_free_row_spends_nothing_as_it_rolls():
    """A spell's slot is spent by Cast, never by its roll; a row that costs nothing carries nothing."""
    cole = rows("cole")
    assert not cole["Unarmed Strike"].get("pay") and not first_pay(cole["Unarmed Strike"])
    assert all(not o.get("pay") for o in cole.values() if o.get("kind") == "spell")
