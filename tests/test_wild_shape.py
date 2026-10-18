"""Wild Shape (app/wild_shape.py): which Beasts a druid can learn, forms with the
druid's stats carried over, the Battle switch, and notes on shortlists and reminders."""

import copy

import pytest

from app import characters
from app import wild_shape as ws
from app.importer import import_bundle
from tests.test_characters import BUNDLE, COLE, admin, char, dm, no_network, owned_by, player  # noqa: F401
from tests.test_suggestions import HX


def cole_sheet(level=6, moon=True) -> dict:
    """Cole's parsed sheet, with the Druid level (and Circle) changed for rule checks."""
    from app import ddb

    data = copy.deepcopy(COLE)
    data = data.get("data", data)
    sheet = ddb.parse_character(data)
    sheet["classes"] = [{"name": "Druid", "level": level, "subclass": "Circle of the Moon" if moon else ""}]
    if not moon:
        sheet["features"] = [f for f in sheet["features"] if f["name"] not in ("Circle Forms", "Improved Circle Forms")]
    return sheet


def test_limits_follow_druid_level_and_circle_of_the_moon():
    d = ws.druid(cole_sheet(level=6, moon=True))
    assert (d["known"], d["max_cr_label"], d["fly"], d["temp_hp"], d["hours"]) == (6, "2", False, 18, 3)
    d = ws.druid(cole_sheet(level=4, moon=False))
    assert (d["known"], d["max_cr_label"], d["fly"], d["temp_hp"]) == (6, "1/2", False, 4)
    d = ws.druid(cole_sheet(level=8, moon=False))
    assert (d["known"], d["max_cr_label"], d["fly"]) == (8, "1", True)
    assert ws.druid(cole_sheet(level=1)) is None
    assert ws.druid({"classes": [{"name": "Monk", "level": 5, "subclass": ""}]}) is None


def test_forms_list_learnable_beasts_known_ones_first():
    sheet = cole_sheet(level=4, moon=False)
    rows = ws.forms(sheet, fav={"form:Tiger"})
    names = [r["name"] for r in rows]
    assert names[:6] == [r["name"] for r in rows if r["known"]]  # known on D&D Beyond come first
    assert "Wolf" in names and "Black Bear" in names  # CR 1/4 and 1/2
    assert "Brown Bear" not in names  # CR 1 is above 1/2
    assert "Pteranodon" not in names  # flies (not until level 8)
    tiger = next(r for r in rows if r["name"] == "Tiger")  # shortlisted, so still listed, with the reason
    assert tiger["why_not"] == "CR 1 is above your max of 1/2"
    polar = next(r for r in rows if r["name"] == "Polar Bear")
    assert polar["known"] and polar["why_not"].startswith("CR 2")


def test_a_form_keeps_the_druids_mind_and_proficiencies():
    sheet = cole_sheet()
    f = ws.shaped(sheet, ws.beast_for(sheet, "Polar Bear"))
    scores = {a["key"]: (a["score"], a["from"]) for a in f["abilities"]}
    assert scores["str"] == (20, "form") and scores["wis"] == (19, "yours") and scores["int"] == (10, "yours")
    assert f["ac"] == 17  # Circle Forms: 13 + Wis +4 beats the bear's 12
    assert f["temp_hp"] == 18 and f["hp"]["max"] == sheet["hit_points"]["max"]  # keeps their own Hit Points
    saves = {s["key"]: s["bonus"] for s in f["saves"]}
    assert saves["con"] == 3 + 4  # form's Con +3, Increased Toughness adds Wis
    assert saves["wis"] == 4 + sheet["proficiency_bonus"]  # their own Wis and save proficiency
    rend = next(o for o in f["columns"]["Action"]["shown"] if o["name"] == "Rend")
    assert rend["hit"] == "+7" and "9 (1d8 + 5) Slashing (or Radiant)" in rend["meta"]
    bonus = [o["name"] for o in f["columns"]["Bonus action"]["shown"]]
    assert "Leave the form" in bonus and "Flurry of Blows" in bonus
    assert not any("Spell" in o["name"] for col in f["columns"].values() for o in col["shown"])  # no spellcasting


def test_without_circle_of_the_moon_the_beasts_ac_and_level_temp_hp_apply():
    sheet = cole_sheet(level=4, moon=False)
    f = ws.shaped(sheet, ws.beast_for(sheet, "Wolf"))
    assert f["ac"] == ws.catalog_beast("Wolf")["ac"] and f["temp_hp"] == 4
    assert all("(or Radiant)" not in o["meta"] for o in f["columns"]["Action"]["shown"])


@pytest.fixture
def cole(db, player):
    import_bundle(db, BUNDLE)
    c = char(db, "Cole")
    characters.refresh(db, c)
    owned_by(db, c, "player@example.com")
    return c


def test_wild_shape_tab_panel_and_battle_switch(db, cole, player, dm):
    page = player.get(f"/characters/{cole.id}").text
    assert ">Wild Shape</button>" in page and "Known 6 of 6" in page and "form?name=Polar%20Bear" in page
    assert 'data-modal-url="/characters/%d/form?name=Polar%%20Bear" data-modal-size="large"' % cole.id in page  # opens in the large modal
    panel = player.get(f"/characters/{cole.id}/form?name=Polar Bear").text
    assert "Circle Forms" in panel and "Shift into it on Battle" in panel and "dndbeyond.com/avatars" in panel
    assert player.get(f"/characters/{cole.id}/form?name=Unicorn").status_code == 404

    assert dm.post(f"/characters/{cole.id}/wild-shape", data={"form": "Polar Bear"}).status_code == 403  # their player only
    assert player.post(f"/characters/{cole.id}/wild-shape", data={"form": "Tiger"}, headers=HX).status_code == 400  # not known
    r = player.post(f"/characters/{cole.id}/wild-shape", data={"form": "polar bear"}, headers=HX)
    assert "In Wild Shape: Polar Bear" in r.text and "Wild Shape: Polar Bear" in r.headers["HX-Trigger"]
    assert 'data-modal-size="large"' in r.text
    db.refresh(cole)
    assert cole.wild_shape == "Polar Bear"
    assert "In Wild Shape: Polar Bear" in dm.get(f"/characters/{cole.id}/battle").text  # the whole table sees it
    player.post(f"/characters/{cole.id}/wild-shape", data={"form": ""}, headers=HX)
    db.refresh(cole)
    assert cole.wild_shape is None


def test_notes_on_shortlist_and_reminders_are_the_players_and_hidden_from_the_dm(db, cole, player, dm):
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    url = f"/characters/{cole.id}"
    r = player.post(f"{url}/pick", data={"kind": "fav", "ref": "form:Tiger", "wrap": "1"})
    assert "Why is it on your shortlist?" in r.text
    assert player.post(f"{url}/pick/note", data={"kind": "fav", "ref": "form:Tiger", "note": "Pounce when I hit 9"}).text.endswith("Saved</span>")
    assert player.post(f"{url}/pick/note", data={"kind": "star", "ref": "form:Tiger", "note": "x"}).status_code == 400
    assert player.post(f"{url}/pick/note", data={"kind": "remind", "ref": "form:Tiger", "note": "x"}).status_code == 404  # not a reminder
    assert dm.post(f"{url}/pick/note", data={"kind": "fav", "ref": "form:Tiger", "note": "x"}).status_code == 403
    player.post(f"{url}/pick", data={"kind": "remind", "ref": "form:Tiger"})
    player.post(f"{url}/pick/note", data={"kind": "remind", "ref": "form:Tiger", "note": "Only at night"})
    page = player.get(url).text
    assert "✎ Pounce when I hit 9" in page and "✎ Only at night" in page
    assert "Tiger (Wild Shape, CR 1)" in player.get(f"{url}/battle").text  # reminder text for a form they don't know yet
    assert "Pounce" not in dm.get(url).text and "Only at night" not in dm.get(f"{url}/battle").text


def _names(f, cost="Action"):
    return [o["name"] for o in f["columns"][cost]["shown"]]


def test_circle_of_the_moon_spells_can_be_cast_in_a_form_and_nothing_else():
    sheet = cole_sheet(level=6)
    f = ws.shaped(sheet, ws.beast_for(sheet, "Polar Bear"))
    assert {"Starry Wisp", "Cure Wounds", "Moonbeam", "Conjure Animals"} <= set(_names(f))  # levels 3 and 5
    assert f["castable"] and all(n in ws.druid(sheet)["moon_spells"] for n in f["castable"])
    assert "Cure Wounds" in ws.druid(cole_sheet(level=3))["moon_spells"] and "Conjure Animals" not in ws.druid(cole_sheet(level=3))["moon_spells"]
    other = ws.shaped(cole_sheet(level=6, moon=False), ws.catalog_beast("Wolf"))
    assert other["castable"] == [] and not other["magic_action"]


def test_beast_spells_at_18_skip_costly_or_consumed_materials():
    sheet = cole_sheet(level=18, moon=False)
    base = next(s for s in sheet["spells"] if s["name"] == "Cure Wounds")
    sheet["spells"].append({**base, "key": "spell:Pricey", "name": "Pricey", "material": "a diamond worth 300+ GP, which the spell consumes"})
    f = ws.shaped(sheet, ws.catalog_beast("Brown Bear"))
    assert "Cure Wounds" in _names(f) and "Pricey" not in _names(f)
    assert any(o["tags"][0] == "Beast Spells" for o in f["columns"]["Action"]["shown"] if o["name"] == "Cure Wounds")


def test_primal_strike_and_lunar_form_add_damage_to_form_attacks():
    sheet = cole_sheet(level=15)
    sheet["features"].append({"key": "feature:Druid:Primal Strike", "name": "Elemental Fury: Primal Strike", "source": "Druid", "summary": "", "text": "", "level": 7, "use": False})
    rend = next(o for o in ws.shaped(sheet, ws.catalog_beast("Polar Bear"))["columns"]["Action"]["shown"] if o["name"] == "Rend")
    assert "+2d8 Cold/Fire/Lightning/Thunder once per turn" in rend["meta"] and "+2d10 Radiant once per turn" in rend["meta"]
    d = ws.druid(cole_sheet(level=7))
    assert d["fury"] == "" and d["primal_strike"] == "1d8"  # option not on the sheet: the panel explains both
    assert not ws.druid(cole_sheet(level=13))["lunar_form"]


def test_other_uses_of_wild_shape_come_from_the_sheet():
    names = [u["name"] for u in ws.other_uses(cole_sheet())]
    assert "Wild Companion" in names and any(n.startswith("Wild Resurgence") for n in names)
    assert len([n for n in names if n.startswith("Wild Resurgence")]) == 2  # the two actions, not the feature again
