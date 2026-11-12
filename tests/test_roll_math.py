"""Show the Math (app/roll_math.py, app/check_numbers.py; Brett chose A, B, D and E, Nov 12, docs/mockups/show-the-math/):
every number askdnd rolls with says how it adds up, the parts travel with the roll and stay with it in Table rolls, and
a breakdown never disagrees with its total."""

import json
import re
from pathlib import Path

import pytest

from app import characters, ddb, roll_math
from app.character_views import options
from app.importer import import_bundle
from tests.roles import set_role
from tests.table_setup import BUNDLE, char, owned_by, sign_in

ROOT = Path(__file__).resolve().parents[1]
PARTY = ["big_c", "cole", "no_name", "trah"]


def sheet(name: str) -> dict:
    return ddb.parse_character(ddb.sanitize(json.loads((ROOT / "tests" / "fixtures" / "ddb" / f"{name}.json").read_text())["data"]))


@pytest.fixture(scope="module")
def cole():
    return sheet("cole")


@pytest.fixture
def table(monkeypatch, db, no_network):
    """Cole, played by player@; dm@ is the campaign's DM. A signed-in client each."""
    import_bundle(db, BUNDLE)
    c = char(db, "Cole")
    owned_by(db, c, "player@example.com")
    characters.refresh(db, c)
    set_role(db, "dm@example.com")
    return {"cole": c, "player": sign_in(monkeypatch, db, "player@example.com"), "dm": sign_in(monkeypatch, db, "dm@example.com")}


def test_coles_unarmed_strike_says_each_part(cole):
    o = next(o for o in options(cole, set()) if o["name"] == "Unarmed Strike")
    m = o["math"]
    assert [(r["n"], r["what"], r["src"]) for r in m["bonus"]] == [
        (2, "Dexterity modifier (Martial Arts)", "sheet"), (3, "Proficiency Bonus", "sheet"), (1, "Insignia of Claws", "sheet")]
    assert m["dmg"][0] == {"n": "1d6", "what": "Martial Arts die (Monk 2)", "src": "rules"}


def test_a_spells_dc_and_how_its_dice_grow(cole):
    moon = next(o for o in options(cole, set()) if o["name"] == "Moonbeam")
    assert [r["n"] for r in moon["math"]["dc"]] == [8, 3, 4] and moon["math"]["dice"] == "rules"
    at = moon["rolls"]["other"]["effects"][0]["at"]
    assert "why" not in at["2"] and at["3"]["why"] == "2d10 at level 2, +1d10 for the level-3 slot"
    cure = next(o for o in options(cole, set()) if o["name"] == "Cure Wounds")["rolls"]["other"]["effects"][0]["at"]
    assert cure["3"]["text"].startswith("6d8") and cure["3"]["why"] == "2d8 at level 1, +4d8 for the level-3 slot"


def test_every_breakdown_on_the_partys_sheets_adds_up():
    """A breakdown never disagrees with its number: every to-hit's and DC's parts come to it, on every party sheet."""
    for name in PARTY:
        s = sheet(name)
        for o in options(s, set()):
            m, p = o.get("math") or {}, o.get("plan") or {}
            if m.get("bonus") and (p.get("attack") or {}).get("bonus") is not None:
                assert roll_math.adds_up(m["bonus"], p["attack"]["bonus"]), (name, o["name"], m["bonus"])
            if m.get("dc"):
                assert roll_math.adds_up(m["dc"], p["save"]["dc"]), (name, o["name"], m["dc"])
        for sv in s["saves"]:
            assert roll_math.adds_up(roll_math.rows(sv["parts"]), sv["bonus"]), (name, sv["short"])
        for a in s["abilities"]:
            assert roll_math.adds_up(roll_math.rows(a["check_parts"]), a["check"]), (name, a["name"])


def test_an_ability_check_takes_what_adds_to_every_check(cole):
    """Show the Math's own find (Nov 12): a plain Wisdom check skipped the Stone of Good Luck's +1 that every skill had."""
    wis = next(a for a in cole["abilities"] if a["key"] == "wisdom")
    assert wis["label"] == "+4" and wis["check_label"] == "+5"
    assert ("Stone of Good Luck (Luckstone)", 1) in [tuple(x) for x in wis["check_parts"]]


def test_what_the_card_sends_is_checked_before_its_kept():
    bonus = [{"n": 2, "what": "Dexterity modifier", "src": "sheet"}, {"n": 3, "what": "Proficiency Bonus", "src": "sheet"}]
    sent = json.dumps({"bonus": bonus, "dmg": [{"n": "1d6", "what": "Martial Arts die", "src": "rules"}], "why": "  a  line ", "dice": "rules"})
    kept = roll_math.clean(sent, 5)
    assert kept["bonus"] == bonus and kept["dmg"][0]["n"] == "1d6" and kept["why"] == "a line" and kept["dice"] == "rules"
    assert "bonus" not in roll_math.clean(sent, 6)  # (parts that don't come to the roll's bonus aren't kept)
    bad = json.dumps({"bonus": [{"n": "<script>", "what": "x"}, {"n": 999, "what": "big"}, {"n": True, "what": "bool"}, "nope"],
                      "dmg": [{"n": 1, "what": ""}], "dice": "elsewhere"})
    assert roll_math.clean(bad, 0) == {} and roll_math.clean("not json", 0) == {} and roll_math.clean("[1]", 0) == {}
    long = roll_math.clean(json.dumps({"bonus": [{"n": 1, "what": "x" * 500, "src": "sheet"}] * 20}), 8)
    assert len(long["bonus"]) == 8 and len(long["bonus"][0]["what"]) == 70


def test_a_roll_keeps_its_parts_in_table_rolls(table):
    """B: the parts sent with a roll come back on its entry, as rolled, for whoever sees the roll (the DM too)."""
    cid = table["cole"].id
    bonus = [{"n": 2, "what": "Dexterity modifier (Martial Arts)", "src": "sheet"}, {"n": 3, "what": "Proficiency Bonus", "src": "sheet"},
             {"n": 1, "what": "Insignia of Claws", "src": "sheet"}]
    math = json.dumps({"bonus": bonus, "dmg": [{"n": "1d6", "what": "Martial Arts die (Monk 2)", "src": "rules"},
                                               {"n": 2, "what": "Dexterity modifier", "src": "sheet"}, {"n": 1, "what": "Insignia of Claws", "src": "sheet"}]})
    r = table["player"].post("/rolls", data={"character": cid, "kind": "attack", "label": "Unarmed Strike", "mod": "+6", "dmg": "1d6+3",
                                             "to": "table", "math": math})
    assert r.status_code == 200, r.text
    e = r.json()["roll"]
    hit = e["math"]["hit"]
    assert hit["rows"][0]["what"] == "the d20" and hit["rows"][1:] == bonus and hit["total"] == e["total"]
    d = table["player"].post("/rolls", data={"parent": e["id"], "action": "damage"}).json()["roll"]["math"]["dmg"]
    assert d["rows"][0]["what"] == "1d6, Martial Arts die (Monk 2)" and [x["n"] for x in d["rows"][1:]] == [2, 1]
    assert sum(x["n"] for x in d["rows"]) == d["total"]
    log = table["dm"].get("/rolls").text
    assert 'class="math-n"' in log and "Insignia of Claws" in log and "Martial Arts die (Monk 2)" in log


def test_a_roll_without_parts_still_says_its_die_and_bonus(table):
    r = table["player"].post("/rolls", data={"character": table["cole"].id, "kind": "check", "label": "Stealth check", "mod": "+6", "to": "table"})
    rows = r.json()["roll"]["math"]["hit"]["rows"]
    assert [x["what"] for x in rows] == ["the d20", "Bonus"] and rows[1]["n"] == 6


def test_check_your_numbers(table):
    """E: one window with every roll, how it adds up and what it was checked against; anyone who can see the character."""
    cid = table["cole"].id
    page = table["player"].get(f"/characters/{cid}/numbers").text
    assert "Check Cole's numbers" in page and "Insignia of Claws" in page and "Moonbeam" in page
    assert re.search(r"Unarmed Strike</b><span class=\"cn-why\">Action · Bonus action", page)  # (one row for the same roll)
    assert "Checks and saves" in page and "Stone of Good Luck (Luckstone)" in page
    assert table["dm"].get(f"/characters/{cid}/numbers").status_code == 200
    assert 'data-modal-url="/characters/%d/numbers"' % cid in table["player"].get(f"/characters/{cid}/battle").text


def _battles(name: str):
    """Every Battle a party sheet has: the character's own, each Wild Shape form it knows, each of its creatures."""
    from app import creatures
    from app import wild_shape as ws

    s = sheet(name)
    yield f"{name}", options(s, set())
    beasts = ws.beasts()
    for kf in ws.known_forms(s, beasts):
        f = ws.shaped(s, ws.beast_for(s, kf["name"], beasts), keep=ws.chosen_keep(s, None))
        yield f"{name} as {kf['name']}", [o for col in f["columns"].values() for o in col["all"]]
    for c in creatures.yours(s):
        if c.get("block"):
            yield f"{name}'s {c['name']}", [o for col in creatures.card(s, c)["columns"].values() for o in col["all"]]


@pytest.mark.parametrize("name", PARTY)
def test_every_row_on_every_battle_is_ready_the_same_way(name):
    """Brett, Nov 12 ("applies as globally as possible to avoid any future oversights"): a form's Unarmed Strike had no
    parts and no Grapple or Shove, because a form's rows skipped the step Battle's own rows go through. Every row that
    rolls, on every Battle a party sheet has, now has its plan (character_views.planned), parts that add up to its
    to-hit, and an Unarmed Strike always offers Damage, Grapple and Shove with its DC."""
    seen = 0
    for where, rows in _battles(name):
        for o in rows:
            hit = str(o.get("hit") or "")
            if not hit or hit[0] not in "+-−":
                continue
            seen += 1
            p, m = o.get("plan") or {}, o.get("math") or {}
            assert p.get("attack") or p.get("save"), (where, o["name"], "no roll plan")
            if p.get("attack"):  # (a sheet's attack the 2024 rules make a save, Inflict Wounds, rolls the save instead)
                assert m.get("bonus") and roll_math.adds_up(m["bonus"], p["attack"]["bonus"]), (where, o["name"], hit, m.get("bonus"))
            if o["name"].startswith("Unarmed Strike"):
                said = [x["key"] for x in (p.get("choice") or {}).get("options") or []]
                assert said == ["damage", "grapple", "shove"], (where, o["name"])
                assert "DC None" not in str(p["choice"]), (where, o["name"])
    assert seen


def test_a_creatures_rows_take_none_of_its_masters_extras(cole):
    """A familiar's attack is its own: no Stunning Strike, no Bless pills from its master's sheet."""
    from app import creatures

    for c in creatures.yours(cole):
        if c.get("block"):
            for col in creatures.card(cole, c)["columns"].values():
                for o in col["all"]:
                    if o.get("plan"):
                        assert not o["plan"]["modifiers"] and not [r for r in o["plan"]["riders"] if r.get("on") != "mastery"], (c["name"], o["name"])


def test_a_forms_grapple_dc_is_the_forms(cole):
    from app import wild_shape as ws

    beasts = ws.beasts()
    bear = ws.shaped(cole, ws.beast_for(cole, "Polar Bear", beasts), keep=[])
    u = next(o for o in bear["columns"]["Action"]["all"] if o["name"] == "Unarmed Strike")
    assert u["unarmed_dc"] == 8 + 5 + 3 and f"DC {u['unarmed_dc']}" in str(u["plan"]["choice"])  # (the bear's Strength +5, not Cole's −1)
    rend = next(o for o in bear["columns"]["Action"]["all"] if o["name"] == "Rend")
    assert "monk_weapon" not in str(rend["plan"]) and not [r for r in rend["plan"]["riders"] if "Stunning" in r["name"]]


def test_every_wild_shape_attack_says_its_parts(cole):
    """Brett, Nov 12: a form's Unarmed Strike showed only "Bonus". Every attack in each of Cole's forms has parts that
    add up: the form's Strength (or Dexterity with Martial Arts), his Proficiency Bonus and what he keeps."""
    from app import wild_shape as ws

    beasts = ws.beasts()
    for kf in ws.known_forms(cole, beasts):
        f = ws.shaped(cole, ws.beast_for(cole, kf["name"], beasts), keep=ws.chosen_keep(cole, None))
        for o in (o for col in f["columns"].values() for o in col["all"]):
            if o.get("hit") and str(o["hit"])[0] in "+-−":
                rows = (o.get("math") or {}).get("bonus")
                assert rows and roll_math.adds_up(rows, o["hit"]), (kf["name"], o["name"], o["hit"], rows)
    bear = ws.shaped(cole, ws.beast_for(cole, "Polar Bear", beasts), keep=["item:Insignia of Claws"])
    u = next(o for o in bear["columns"]["Action"]["all"] if o["name"] == "Unarmed Strike")
    assert [r["src"] for r in u["math"]["bonus"]][:2] == ["form", "sheet"] and u["math"]["dmg"][0]["n"] == "1d6"

