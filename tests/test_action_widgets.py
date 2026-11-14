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


def party(name: str) -> tuple[dict, dict]:
    sheet = ddb.parse_character(ddb.sanitize(json.loads((ROOT / "tests" / "fixtures" / "ddb" / f"{name}.json").read_text())["data"]))
    return sheet, {o["name"]: o for o in cv.options(sheet)}


def test_the_use_window_is_for_a_cost_with_no_roll_and_its_data_says_the_rest():
    """Brett chose A on the Use Window mockup (Nov 13): Divine Sense and Patient Defense spend their cost with Use;
    Lay On Hands is a pool, for one creature, in two ways, its D&D Beyond row choosing the first. A roll spends on the
    roll card instead (Flurry of Blows); a Reaction's cost is a choice (Deflect Attack's Focus Point only to redirect);
    Wild Shape has its own window."""
    from app import feature_use

    big_c, rows = party("big_c")
    s = feature_use.spec(big_c, rows["Channel Divinity: Divine Sense"])
    assert s["ways"] == [{"key": "use", "name": "Spend 1 use of Channel Divinity"}] and not s["pool"] and not s["for"]
    heal = feature_use.spec(big_c, rows["Lay On Hands: Heal"])
    assert heal["pool"] and heal["for"] == "one" and [w["key"] for w in heal["ways"]] == ["heal", "poison"]
    assert [w["key"] for w in feature_use.spec(big_c, rows["Lay On Hands: Purify Poison"])["ways"]] == ["poison", "heal"]
    cole, rows = party("cole")
    assert feature_use.spec(cole, rows["Patient Defense"]) and rows["Patient Defense"]["use_window"]
    assert not rows["Flurry of Blows"].get("use_window") and not rows["Wild Shape"].get("use_window")
    no_name, rows = party("no_name")
    assert not rows["Deflect Attack"].get("use_window")


def test_use_spends_it_on_d_and_d_beyond_and_undo_gives_it_back(player, db, sheet):
    """Patient Defense on Cole's test sheet: the window says its cost, Use spends a Focus Point through Use one's count,
    the corner card's Undo gives it back, and only an Undo askdnd gave is taken."""
    from urllib.parse import quote

    from sqlalchemy import select

    from app.models import BridgeIntent
    from tests.table_setup import char

    cole = char(db, "Cole")
    url = f"/characters/{cole.id}/feature?key={quote('action:Patient Defense')}"
    page = player.get(url).text
    assert "data-use-go" in page and "Focus Point" in page
    r = player.post(url, data={"way": "use"}).json()
    sent = [i.data for i in db.scalars(select(BridgeIntent).order_by(BridgeIntent.id)) if i.kind == "use"]
    assert [(d["field"], d["delta"]) for d in sent] == [(r["undo"]["field"], 1)]
    assert player.post(r["undoUrl"], data={**r["undo"], "n": "9"}).status_code == 409  # (only what it answered)
    player.post(r["undoUrl"], data=r["undo"])
    sent = [i.data for i in db.scalars(select(BridgeIntent).order_by(BridgeIntent.id)) if i.kind == "use"]
    assert [d["delta"] for d in sent] == [1, -1]
    assert player.get(f"/characters/{cole.id}/feature?key={quote('action:Flurry of Blows')}").status_code == 404  # (it rolls)


def test_lay_on_hands_heals_yourself_at_once_and_another_through_table_rolls(player, db, sheet):
    """Lay On Hands (Big C's sheet in Cole's place): How many starts at what the one it's for is missing; on your own
    character it spends the points and heals through the hit points window's rules, Undo taking both back; on someone
    else's it spends them and puts the healing in Table rolls for that character's player to apply (a standing rule: a
    player changes only their own sheet; tests/test_refusals.py)."""
    import copy
    from urllib.parse import quote

    from sqlalchemy import select

    from app import characters
    from app.models import BridgeIntent, Character, TableRoll
    from tests.table_setup import char

    sheet.clear()
    sheet.update(copy.deepcopy(json.loads((ROOT / "tests" / "fixtures" / "ddb" / "big_c.json").read_text())["data"]))
    sheet["removedHitPoints"] = 7
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    url = f"/characters/{cole.id}/feature?key={quote('action:Lay On Hands: Heal')}"
    page = player.get(url).text
    assert 'name="target"' in page and 'value="7"' in page  # (all it needs: the 7 missing)

    r = player.post(url, data={"way": "heal", "n": "7", "target": str(cole.id)}).json()
    made = [(i.kind, i.data) for i in db.scalars(select(BridgeIntent).order_by(BridgeIntent.id))]
    assert ("use", 7) in [(k, d.get("delta")) for k, d in made] and ("hp", 7) in [(k, d.get("amount")) for k, d in made]
    assert r["undo"]["healed"] == "7"
    player.post(r["undoUrl"], data=r["undo"])
    made = [(i.kind, i.data) for i in db.scalars(select(BridgeIntent).order_by(BridgeIntent.id))]
    assert ("use", -7) in [(k, d.get("delta")) for k, d in made] and ("hp", -7) in [(k, d.get("amount")) for k, d in made]

    other = next((c for c in db.scalars(select(Character)) if c.id != cole.id and c.campaign_id == cole.campaign_id
                  and c.ddb_id and c.copy_of_id is None), None)
    if other is None:
        pytest.skip("no other character the bridge reaches in the test campaign")
    r = player.post(url, data={"way": "heal", "n": "4", "target": str(other.id)}).json()
    row = db.scalar(select(TableRoll).where(TableRoll.kind == "heal").order_by(TableRoll.id.desc()))
    assert row.total == 4 and other.name in row.label and "to apply" in r["text"]
    assert not [d for k, d in ((i.kind, i.data) for i in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == other.id))) if k == "hp"]
