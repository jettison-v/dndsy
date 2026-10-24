"""Each person's dice (app/dice.py; docs/mockups/dice-two-ways.html): a set, a material and whether damage dice take
their damage type's look; pages carry yours, rolls carry their roller's, and the VTT piece throws everyone's."""

import json

from sqlalchemy import select

from app import access, dice
from app.models import User
from tests.test_campaigns import two  # noqa: F401


def test_defaults_differ_by_person_and_bad_values_fall_back():
    a, b = User(id=1, email="a@x", name="A"), User(id=2, email="b@x", name="B")
    assert dice.prefs(a)["set"] != dice.prefs(b)["set"] and dice.prefs(a)["material"] == "glass" and dice.prefs(a)["by_type"]
    a.dice = {"set": "nope", "material": "jelly", "by_type": False}
    assert dice.prefs(a) == {"set": dice.DEFAULTS[1], "material": "glass", "by_type": False}


def test_choose_your_dice(two, db):  # noqa: F811
    pat = two["pat"]
    page = pat.get("/dice").text
    assert page.count('name="set"') == len(dice.SETS) and "Dice sounds" in page
    r = pat.post("/dice", data={"set": "bloodmoon", "material": "metal", "by_type": ""})
    assert json.loads(r.headers["HX-Trigger"])["diceChanged"] == {"set": "bloodmoon", "material": "metal", "by_type": False}
    me = db.scalar(select(User).where(User.email == "pat@example.com"))
    assert me.dice == {"set": "bloodmoon", "material": "metal", "by_type": False}
    access.invalidate()
    assert "data-dice='{\"by_type\": false, \"material\": \"metal\", \"set\": \"bloodmoon\"}'" in pat.get("/c/main/").text
    assert 'data-modal-url="/dice"' in pat.get("/c/main/").text  # Your dice, in the account menu


def test_the_vtt_piece_throws_everyones_rolls(two, db):  # noqa: F811
    admin, strahd = two["admin"], two["strahd"]
    assert "data-dice-all" not in admin.get("/c/strahd/").text
    strahd.is_test = True  # a test campaign has every VTT piece
    db.flush()
    access.invalidate()
    assert "data-dice-all" in admin.get("/c/strahd/").text
