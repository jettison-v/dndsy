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


def test_tuning_is_kept_in_range():
    assert dice.clean_tuning(None) == dice.TUNING  # askdnd's own until an admin saves
    t = dice.clean_tuning({"mine": {"gravity": "5000", "stay": "2.04", "shadows": "yes", "dim": "x"}, "tray": "nope", "elsewhere": {}})
    assert t["mine"]["gravity"] == 800 and t["mine"]["stay"] == 2.0 and t["mine"]["shadows"] is True and t["mine"]["dim"] == 55
    assert t["tray"] == dice.TUNING["tray"] and set(t) == {"mine", "tray", "vtt"}
    assert dice.shown(1, "x") == "1.0×" and dice.shown(0.7, "pct") == "70%" and dice.shown(0.25, "s") == "0.25 s" and dice.shown(2, "px") == "2 px"
    for place, _, _, groups in dice.PLACES:  # every knob a place has is on its tab, once
        assert sorted(k for _, keys in groups for k in keys) == sorted(dice.TUNING[place])


def test_admins_tune_the_dice_for_everyone(two, db):  # noqa: F811
    admin, pat = two["admin"], two["pat"]
    assert pat.get("/manage/dice").status_code == 403
    assert pat.post("/manage/dice", data={"mine.gravity": "200"}).status_code == 403
    page = admin.get("/manage/dice").text
    assert 'aria-current="page">Dice tuning' in page and page.count('class="tn-row"') == 10 + 7 + 10
    assert 'name="mine.gravity" min="100" max="800" step="10" value="300"' in page and "now 1.4×" in page
    # Save: the shadows switch posts "1" when on, nothing when off
    form = {f"{p}.{k}": ("1" if v else "") if isinstance(v, bool) else str(v) for p, knobs in dice.TUNING.items() for k, v in knobs.items()}
    admin.post("/manage/dice", data={**form, "mine.gravity": "200", "tray.shadows": "1", "vtt.stay": "5"})
    saved = dice.tuning_from(db)
    assert saved["mine"]["gravity"] == 200 and saved["tray"]["shadows"] is True and saved["vtt"]["stay"] == 5
    assert saved["mine"]["shadows"] is True and saved["vtt"]["blur"] == 0
    # Every signed-in page carries it for the dice
    tuned = pat.get("/c/main/").text.split("data-dice-tuning='")[1].split("'")[0]
    assert json.loads(tuned)["mine"]["gravity"] == 200
    admin.post("/manage/dice", data={"reset": "1"})
    assert dice.tuning_from(db) == dice.TUNING
