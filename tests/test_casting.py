"""Casting a spell in play (app/casting.py): the slot through the bridge, Concentration by itself, Undo."""

import pytest
from sqlalchemy import select

from app import casting, characters
from app import spellbook as sb
from app.models import BridgeIntent, Campaign
from tests.table_setup import char


@pytest.fixture(autouse=True)
def test_campaign(db, sheet):
    """Live state is a VTT piece still being reviewed: a test campaign sees it."""
    db.get(Campaign, char(db, "Cole").campaign_id).is_test = True
    db.flush()


def spell(sheet, **want):
    return next(e for e in sb.entries(sheet) if all(e[k] == v for k, v in want.items()))


def url(cole, e):
    return f"/characters/{cole.id}/cast?key={e['key']}"


def test_a_spell_can_use_its_own_slot_or_a_higher_one_and_nothing_else():
    e = {"level": 2, "avgs": {3: {"dice": "3d8"}}, "ritual": False}
    sheet = {"spell_slots": {"slots": [{"level": 1, "max": 4, "used": 0}, {"level": 2, "max": 3, "used": 3}, {"level": 3, "max": 3, "used": 1}],
                             "pact": {"level": 2, "max": 2, "used": 0}}}
    got = casting.ways(sheet, e)
    assert [w["way"] for w in got] == ["pact:2", "slot:3", "none"]
    assert got[1]["label"] == "3rd-level (2 left) · 3d8"
    assert [w["way"] for w in casting.ways(sheet, {**e, "ritual": True})][-2:] == ["ritual", "none"]
    assert casting.ways(sheet, {"level": 0, "avgs": {}, "ritual": False}) == []


def test_casting_spends_the_slot_on_d_and_d_beyond_and_concentration_starts_by_itself(player, db, sheet):
    cole = char(db, "Cole")
    e = spell(characters.character_summary(cole), conc=True, level=1)
    assert 'name="way"' in player.get(url(cole, e)).text
    r = player.post(url(cole, e), data={"way": "slot:2"})
    assert r.status_code == 200 and "at 2nd-level" in r.json()["text"] and r.json()["deliver"]
    change = db.scalar(select(BridgeIntent))
    assert change.kind == "use" and change.data["field"] == "slot:2" and change.data["delta"] == 1
    db.refresh(cole)
    assert cole.concentration["spell"] == e["name"] and cole.concentration["level"] == 2


def test_a_second_concentration_spell_says_it_ends_the_first_and_undo_puts_it_back(player, db, sheet):
    cole = char(db, "Cole")
    spells = [x for x in sb.entries(characters.character_summary(cole)) if x["conc"] and x["level"]]
    first, second = spells[0], spells[1]
    player.post(url(cole, first), data={"way": f"slot:{first['level']}"})
    assert f"Ends Concentration on {first['name']}" in player.get(url(cole, second)).text
    r = player.post(url(cole, second), data={"way": "none"}).json()
    assert f"{first['name']} ended" in r["text"]
    db.refresh(cole)
    assert cole.concentration["spell"] == second["name"]
    player.post(r["undoUrl"], data=r["undo"])
    db.refresh(cole)
    assert cole.concentration["spell"] == first["name"] and "was" not in cole.concentration


def test_undo_gives_the_slot_back(player, db, sheet):
    cole = char(db, "Cole")
    e = spell(characters.character_summary(cole), level=1)
    r = player.post(url(cole, e), data={"way": "slot:1"}).json()
    assert player.post(r["undoUrl"], data=r["undo"]).status_code == 200
    assert sorted(i.data["delta"] for i in db.scalars(select(BridgeIntent))) == [-1, 1]


def test_a_slot_that_isnt_left_is_refused(player, db, sheet):
    cole = char(db, "Cole")
    e = spell(characters.character_summary(cole), level=2)
    assert player.post(url(cole, e), data={"way": "slot:1"}).status_code == 409
    assert db.scalar(select(BridgeIntent)) is None


def test_a_closed_sheet_says_how_and_spends_nothing(player, db, sheet):
    cole = char(db, "Cole")
    cole.sheet_heard_at = None
    db.flush()
    e = spell(characters.character_summary(cole), level=1)
    assert "can't be reached" in player.get(url(cole, e)).text
    assert player.post(url(cole, e), data={"way": "slot:1"}).status_code == 409
    db.refresh(cole)
    assert db.scalar(select(BridgeIntent)) is None and cole.concentration is None


def test_only_the_characters_own_player_casts(dm, db, sheet):
    cole = char(db, "Cole")
    e = spell(characters.character_summary(cole), level=1)
    assert dm.post(url(cole, e), data={"way": "slot:1"}).status_code == 404


def test_a_free_use_comes_first_and_takes_the_place_of_no_slot():
    """Brett, 2026-10-31: the Cast window names a feat's free use and counts it."""
    sheet = {"spell_slots": {"slots": [{"level": 2, "max": 3, "used": 0}]}}
    e = {"level": 2, "avgs": {}, "ritual": False, "from": "Fey Touched", "uses": {"left": 1, "max": 1}}
    got = casting.ways(sheet, e)
    assert got[0]["label"] == "Free: Fey Touched (1 left)"
    assert not any(w["way"] == casting.NO_SLOT for w in got)
    assert any(w["way"] == casting.NO_SLOT for w in casting.ways(sheet, e | {"uses": {"left": 0, "max": 1}}))
