"""Hit points' working and its paths, as whole results (app/hit_points.py; the bug-planting check, foundations F8, Nov 15):
each case checks everything the working gives back, so a number, a flag or a step that changes is caught. The words
each step says aren't pinned (CLAUDE.md, markers not text): its title and its why are left out of the comparison."""

import re
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from starlette.datastructures import FormData

from app import ddb_bridge, death_saves, hit_points, realtime, rules_data
from app.models import Campaign, Character, TableRoll
from tests.roles import set_role
from tests.table_setup import char

HP = {"current": 40, "max": 51, "temp": 0}
SAVE = {"bonus": 7, "label": "+7", "adv": True, "why": "War Caster"}


def bare(w: dict) -> dict:
    """The working without its words: each step's title and why left out."""
    plain = lambda steps: [{k: v for k, v in s.items() if k not in ("title", "why")} for s in steps]
    return {**w, "steps": plain(w["steps"]), "parts": [{**p, "steps": plain(p["steps"])} for p in w["parts"]]}


def base(hp=HP, **kw) -> dict:
    """What every working starts from: nothing changed."""
    cur, top, temp = hp.get("current", 0), hp.get("max", 0), hp.get("temp", 0)
    return {"hp_before": cur, "max": top, "temp_before": temp, "parts": [], "steps": [], "conc": None, "down": False,
            "massive": 0, "taken": 0, "hp_after": cur, "temp_after": temp, "amount": 0, "unconscious": False, "up": False,
            "death_fail": 0, **kw}


def d(kind, t, key=None):
    return {"key": key or f"own:{kind}:{t}", "kind": kind, "type": t, "from": "your sheet"}


# ------------------------------------------------------------------ healing


def test_healing_goes_up_to_the_maximum_and_leaves_the_rest_as_it_was():
    w = hit_points.work({**HP, "temp": 5}, "heal", [{"amount": 20}], [], set())
    assert bare(w) == base({**HP, "temp": 5}, mode="heal", amount=20, hp_after=51, steps=[{"value": "+11"}])


def test_healing_from_zero_ends_unconscious_unless_crossed_out():
    at0 = {"current": 0, "max": 20, "temp": 0}
    w = hit_points.work(at0, "heal", [{"amount": 1}], [], set())
    assert bare(w) == base(at0, mode="heal", amount=1, hp_after=1, up=True,
                           steps=[{"value": "+1"}, {"key": "unconscious", "off": False, "value": "Unconscious ends"}])
    w = hit_points.work(at0, "heal", [{"amount": 3}], [], {"unconscious"})
    assert w["up"] is False and w["steps"][1]["off"] is True
    w = hit_points.work(at0, "heal", [{"amount": 0}], [], set())  # (nothing typed: still at 0, nothing ends)
    assert w["up"] is False and w["empty"] is True and len(w["steps"]) == 1


# ------------------------------------------------------------------ Temporary Hit Points


@pytest.mark.parametrize("temp, amount, take, after", [
    (7, 10, None, 10),  # the higher
    (7, 7, None, 7),  # (the same: kept)
    (7, 5, None, 7),
    (7, 5, True, 5),  # you choose
    (0, 4, False, 0),
])
def test_temporary_hit_points_keep_or_take(temp, amount, take, after):
    w = hit_points.work({**HP, "temp": temp}, "temp", [{"amount": amount}], [], set(), temp_take=take)
    took = take if take is not None else amount > temp
    want = base({**HP, "temp": temp}, mode="temp", amount=amount, temp_after=after, take=took,
                steps=[{"value": f"{'take' if took else 'keep'} {amount if took else temp}", "choose": True}])
    if after == temp:
        want["nothing"] = w["nothing"]  # (says why nothing changes; its words aren't pinned)
    assert bare(w) == want


def test_temporary_hit_points_with_nothing_typed_wait():
    for parts in ([{"amount": 0}], [{"amount": None}], [{}]):
        w = hit_points.work({**HP, "temp": 3}, "temp", parts, [], set())
        assert (w["amount"], w["empty"], w["take"], w["temp_after"]) == (0, True, False, 3)


# ------------------------------------------------------------------ damage


def test_a_hit_of_two_types_each_through_its_own_defenses_then_temporary_hit_points():
    defs = [d("resistance", "fire"), d("vulnerability", "cold")]
    w = hit_points.work({**HP, "temp": 5}, "damage", [{"amount": 9, "type": "Fire"}, {"amount": 4, "type": "cold"}, {"amount": 3}], defs, set())
    assert bare(w) == base({**HP, "temp": 5}, mode="damage", amount=15, taken=15, temp_after=0, hp_after=30, parts=[
        {"amount": 9, "type": "fire", "after": 4, "steps": [{"key": "own:resistance:fire", "value": "9 → 4", "off": False}]},
        {"amount": 4, "type": "cold", "after": 8, "steps": [{"key": "own:vulnerability:cold", "value": "4 → 8", "off": False}]},
        {"amount": 3, "type": "", "after": 3, "steps": []},
    ], steps=[{"value": "5 → 0"}, {"value": "40 → 30"}])


def test_immunity_takes_it_all_and_crossed_out_lets_the_rest_count():
    defs = [d("resistance", "poison"), d("immunity", "poison"), d("vulnerability", "poison")]
    w = hit_points.work(HP, "damage", [{"amount": 30, "type": "poison"}], defs, set())
    assert w["taken"] == 0 and [s["key"] for s in w["parts"][0]["steps"]] == ["own:immunity:poison"]
    assert "empty" not in w  # (a hit a defense takes whole is still a hit: it's applied)
    w = hit_points.work(HP, "damage", [{"amount": 30, "type": "poison"}], defs, {"own:immunity:poison"})
    assert w["taken"] == 30 and [(s["value"], s["off"]) for s in w["parts"][0]["steps"]] == [("30 → 30", True), ("30 → 15", False), ("15 → 30", False)]
    w = hit_points.work(HP, "damage", [{"amount": 30, "type": "poison"}], defs, {"own:immunity:poison", "own:vulnerability:poison"})
    assert w["taken"] == 15


@pytest.mark.parametrize("parts", [[{"amount": 0}], [{"amount": None}], [{}], [{"amount": -4}]])
def test_a_hit_with_nothing_typed_waits(parts):
    w = hit_points.work(HP, "damage", parts, [], set(), None, "Moonbeam", SAVE)
    assert (w["empty"], w["taken"], w["conc"], w["hp_after"]) == (True, 0, None, 40)


def test_concentration_takes_the_save_given_or_a_plain_one():
    w = hit_points.work(HP, "damage", [{"amount": 25}], [], set(), None, "Moonbeam", SAVE)
    assert w["conc"] == {"spell": "Moonbeam", "dc": 12, **SAVE}  # (half of 25, rounded down)
    assert w["steps"][-1]["value"] == "DC 12"
    w = hit_points.work(HP, "damage", [{"amount": 3}], [], set(), None, "Moonbeam")
    assert w["conc"] == {"spell": "Moonbeam", "dc": 10, "bonus": 0, "label": "+0", "adv": False, "why": ""}
    assert hit_points.work(HP, "damage", [{"amount": 3}], [], set())["conc"] is None  # (not concentrating)


def test_out_of_temporary_hit_points_in_a_form_says_the_form_stays():
    form = {"beast": {"name": "Polar Bear"}}
    w = hit_points.work({**HP, "temp": 4}, "damage", [{"amount": 10}], [], set(), form)
    assert [s.get("value") for s in w["steps"]] == ["4 → 0", "40 → 34", "still a Polar Bear"]
    w = hit_points.work({**HP, "temp": 4}, "damage", [{"amount": 4}], [], set(), form)  # (exactly used up: nothing comes off)
    assert [s.get("value") for s in w["steps"]] == ["4 → 0", "40 → 40"]


def test_dropping_to_zero_starts_unconscious_unless_crossed_out():
    hp = {"current": 5, "max": 20, "temp": 0}
    w = hit_points.work(hp, "damage", [{"amount": 12}], [], set())
    assert bare(w) == base(hp, mode="damage", amount=12, taken=12, hp_after=0, down=True, unconscious=True, parts=[
        {"amount": 12, "type": "", "after": 12, "steps": []}],
        steps=[{"value": "5 → 0"}, {"key": "unconscious", "off": False, "value": "Unconscious"}])
    w = hit_points.work(hp, "damage", [{"amount": 12}], [], {"unconscious"})
    assert (w["down"], w["unconscious"], w["steps"][-1]["off"]) == (True, False, True)
    assert hit_points.work(hp, "damage", [{"amount": 4}], [], set())["down"] is False  # (still up)


@pytest.mark.parametrize("death, crit, off, fail, value", [
    (None, False, set(), 1, "+1 failure"),
    ({"success": 1, "fail": 1, "stable": False}, True, set(), 2, "+2 failures"),
    ({"success": 0, "fail": 0, "stable": True}, False, set(), 1, "+1 failure"),
    (None, False, {"death"}, 0, "+1 failure"),  # (crossed out: a ruling)
])
def test_a_hit_at_zero_is_a_death_save_failure(death, crit, off, fail, value):
    at0 = {"current": 0, "max": 20, "temp": 0}
    w = hit_points.work(at0, "damage", [{"amount": 3}], [], off, death=death, crit=crit)
    assert bare(w) == base(at0, mode="damage", amount=3, taken=3, hp_after=0, death_fail=fail,
                           parts=[{"amount": 3, "type": "", "after": 3, "steps": []}],
                           steps=[{"value": "0 → 0"}, {"key": "death", "off": not fail, "value": value}])


def test_massive_damage_is_pointed_out_and_marks_nothing():
    hp = {"current": 5, "max": 20, "temp": 0}
    w = hit_points.work(hp, "damage", [{"amount": 25}], [], set())
    assert (w["massive"], w["down"], w["unconscious"]) == (20, True, True)
    assert {k: v for k, v in w["steps"][-1].items() if k not in ("title", "why")} == {"value": "20 ≥ 20", "mass": True}
    at0 = {"current": 0, "max": 20, "temp": 0}
    w = hit_points.work(at0, "damage", [{"amount": 20}], [], set())  # (at 0: no failure marked, it's the DM's ruling)
    assert (w["massive"], w["death_fail"], w["down"]) == (20, 0, False)
    w = hit_points.work({"current": 0}, "damage", [{"amount": 5}], [], set())  # (no maximum known: never massive)
    assert (w["massive"], w["death_fail"]) == (0, 1)


# ------------------------------------------------------------------ defenses and the Constitution save


def test_defenses_put_the_forms_first_and_count_each_once():
    summary = {"proficiencies": {"defenses": {"Immunities": ["Poison"], "Resistances": ["Cold, Fire"],
                                              "Vulnerabilities": ["Thunder"], "Advantage on": ["Fire"]}}}
    form = {"beast": {"name": "Polar Bear", "immunities": [], "resistances": ["cold"], "vulnerabilities": ["Radiant"]}}
    got = hit_points.defenses(summary, form)
    assert [(x["key"], x["kind"], x["type"]) for x in got] == [
        ("form:resistance:cold", "resistance", "cold"), ("form:vulnerability:radiant", "vulnerability", "radiant"),
        ("own:immunity:poison", "immunity", "poison"), ("own:resistance:fire", "resistance", "fire"),
        ("own:vulnerability:thunder", "vulnerability", "thunder")]
    assert got[0]["from"].endswith("Polar Bear") and got[2]["from"] != hit_points.defenses(summary, None)[0]["from"]
    assert [x["key"] for x in hit_points.defenses(summary, None)][:2] == ["own:immunity:poison", "own:resistance:cold"]
    assert hit_points.defenses({}, None) == [] and hit_points.defenses(None, {"beast": {"name": "X", "immunities": ["fire"]}})[0]["kind"] == "immunity"


def test_the_constitution_save_is_the_forms_then_your_own():
    con = {"short": "Con", "bonus": 2, "label": "+2", "advantage": True, "notes": ["Adv. to maintain Concentration"]}
    assert hit_points.con_save({"saves": [{"short": "Dex", "bonus": 9, "label": "+9"}, con]}, None) == {
        "bonus": 2, "label": "+2", "adv": True, "why": "Adv. to maintain Concentration"}
    keyed = {"key": "con", "bonus": 5, "label": "+5", "adv": [{"text": "War Caster"}, "plain", {"text": "Luck"}]}
    assert hit_points.con_save({"saves": [con]}, {"saves": [keyed]}) == {"bonus": 5, "label": "+5", "adv": True, "why": "War Caster; Luck"}
    assert hit_points.con_save({"saves": [{"key": "con", "short": "Dex", "bonus": 1, "label": "+1"}]}, None)["bonus"] == 1  # (the key wins)
    assert hit_points.con_save({"saves": [{"short": "Con", "bonus": 1, "label": "+1"}]}, None) == {"bonus": 1, "label": "+1", "adv": False, "why": ""}
    assert hit_points.con_save(None, None) == {"bonus": 0, "label": "+0", "adv": False, "why": ""}


# ------------------------------------------------------------------ a monster's attack


def test_a_monsters_attack_type_from_any_of_its_lists(monkeypatch):
    asked = []
    dragon = {"source": "Homebrew", "actions": [{"name": "Bite", "text": "Hit: 13 (2d10 + 2) Piercing damage plus 7 (2d6) Fire damage."}],
              "bonus_actions": [{"name": "Tail (Recharge 5–6)", "text": "Hit: 9 (2d8) Bludgeoning damage."}],
              "reactions": [{"name": "Snap", "text": "Hit: 4 (1d8) Slashing damage."}],
              "legendary_actions": [{"name": "Gust", "text": "Each creature takes 5 (2d4) Thunder damage."}, {"name": "Roar", "text": "Frightened."}]}
    monkeypatch.setattr(rules_data, "find", lambda kind, name, db=None, cid=None: asked.append((kind, name, db, cid)) or (dragon if name == "Drake" else None))
    db = object()
    assert hit_points.attack_type(db, 7, "Drake", "Bite", "2d6") == ("fire", "Homebrew")  # (the roll's dice pick the type)
    assert asked[-1] == ("monster", "Drake", db, 7)
    assert hit_points.attack_type(db, 7, "Drake", "Bite", "2d10+2") == ("piercing", "Homebrew")
    assert hit_points.attack_type(db, 7, "Drake", "bite", "") == ("piercing", "Homebrew")  # (no dice: the first)
    assert hit_points.attack_type(db, 7, "Drake", "Tail") == ("bludgeoning", "Homebrew")
    assert hit_points.attack_type(db, 7, "Drake", "Snap") == ("slashing", "Homebrew")
    assert hit_points.attack_type(db, 7, "Drake", "Gust") == ("thunder", "Homebrew")
    assert hit_points.attack_type(db, 7, "Drake", "Roar") == ("", "")  # (no damage in it)
    assert hit_points.attack_type(db, 7, "Drake", "Claw") == ("", "")
    assert hit_points.attack_type(db, 7, "", "Bite") == ("", "") and len(asked) == 8  # (no monster: nothing asked)


# ------------------------------------------------------------------ what a roll brings, and the window's form


def roll(db, cid, **kw):
    r = TableRoll(campaign_id=cid, label="Greatclub", formula="2d8+4", dice=[], total=kw.pop("total", 13), **kw)
    db.add(r)
    db.flush()
    return r


def test_a_roll_brings_its_damage_by_type_or_its_healing(db, sheet):
    cole = char(db, "Cole")
    cid = cole.campaign_id
    attack = roll(db, cid, kind="attack", who="Ogre", kept=20)
    other = roll(db, cid, kind="attack", who="Ogre")
    roll(db, cid, kind="damage", parent_id=other.id, total=99)  # (another attack's damage)
    roll(db, cid, kind="note", parent_id=attack.id)
    roll(db, cid, kind="damage", parent_id=attack.id, parts=[{"total": 9, "kind": "fire", "kind_from": "SRD"}, {"total": 4}, {"kind": "cold"}])
    assert hit_points.from_roll(db, attack) == ("damage", [{"amount": 9, "type": "fire", "type_from": "SRD"}, {"amount": 4, "type": "", "type_from": ""}], "Ogre · Greatclub")
    assert hit_points.from_roll(db, other) == ("damage", [{"amount": 99, "type": ""}], "Ogre · Greatclub")
    lone = roll(db, cid, kind="attack")
    assert hit_points.from_roll(db, lone) == ("", [], "")  # (an attack without its damage)
    plain = roll(db, cid, kind="damage", total=6)
    assert hit_points.from_roll(db, plain) == ("damage", [{"amount": 6, "type": ""}], "Someone · Greatclub")
    heal = roll(db, cid, kind="heal", character_id=cole.id, total=8)
    assert hit_points.from_roll(db, heal) == ("heal", [{"amount": 8, "type": ""}], "Cole · Greatclub")
    assert hit_points.from_roll(db, roll(db, cid, kind="temp", total=5))[:2] == ("temp", [{"amount": 5, "type": ""}])
    assert hit_points.from_roll(db, roll(db, cid, kind="check")) == ("", [], "")
    assert hit_points.from_roll(db, None) == ("", [], "")
    assert hit_points._crit(attack) and not hit_points._crit(other) and not hit_points._crit(None)
    assert hit_points._crit(roll(db, cid, kind="damage", crit=True)) and not hit_points._crit(roll(db, cid, kind="check", kept=20))


def test_only_a_top_roll_of_the_characters_campaign_is_taken(db, sheet):
    cole = char(db, "Cole")
    mine = roll(db, cole.campaign_id, kind="damage")
    kid = roll(db, cole.campaign_id, kind="damage", parent_id=mine.id)
    elsewhere = Campaign(name="Elsewhere", slug="elsewhere")
    db.add(elsewhere)
    db.flush()
    theirs = roll(db, elsewhere.id, kind="damage")
    assert hit_points._roll(db, mine.id, cole) is mine
    assert hit_points._roll(db, kid.id, cole) is None and hit_points._roll(db, theirs.id, cole) is None
    assert hit_points._roll(db, 0, cole) is None
    db.add(TableRoll(campaign_id=cole.campaign_id, parent_id=mine.id, character_id=cole.id, label="x", kind="applied", formula="", dice=[], total=1))
    db.flush()
    assert list(hit_points.applied(db, mine)) == [cole.id]  # (its damage row isn't an application)


def form(*pairs) -> FormData:
    return FormData(list(pairs))


def test_the_windows_form_is_read_safely():
    assert hit_points._read(form(("mode", "heal"), ("amount", "5"), ("amount", "x"), ("amount", "5000"), ("amount", "-3"), ("amount", ""),
                                 ("type", "FIRE"), ("type", "fire"), ("type", "nonsense"), ("off", "own:resistance:fire"), ("off", "death"))) == (
        "heal", [{"amount": 5, "type": "fire"}, {"amount": 0, "type": "fire"}, {"amount": 999, "type": ""}, {"amount": 0, "type": ""},
                 {"amount": 0, "type": ""}], {"own:resistance:fire", "death"}, None)
    assert hit_points._read(form(("mode", "bogus"))) == ("damage", [{"amount": 0, "type": ""}], set(), None)
    # keep or take holds only for the amount it was chosen on
    assert hit_points._read(form(("amount", "5"), ("take", "1"), ("take_for", "5")))[3] is True
    assert hit_points._read(form(("amount", "5"), ("take", "0"), ("take_for", "5")))[3] is False
    assert hit_points._read(form(("amount", "5"), ("take", "1"), ("take_for", "4")))[3] is None
    assert hit_points._read(form(("amount", "5"), ("take", ""), ("take_for", "5")))[3] is None


# ------------------------------------------------------------------ making it


class Made:
    """What make() asks of the bridge, the death saves and the table, without a database."""

    def __init__(self, monkeypatch, user=None):
        self.calls, self.rows = [], []
        for mod, name in ((ddb_bridge, "add"), (death_saves, "hit"), (death_saves, "down"), (death_saves, "up"),
                          (death_saves, "tell"), (realtime, "announce")):
            monkeypatch.setattr(mod, name, lambda *a, _n=name: self.calls.append((_n, *a[1:])))
        monkeypatch.setattr(hit_points.picks, "user_row", lambda db, u: user)
        self.db = SimpleNamespace(add=self.rows.append)


CH = SimpleNamespace(id=4, name="Cole")


def test_making_a_hit_sends_it_and_its_steps(monkeypatch):
    m = Made(monkeypatch)
    w = hit_points.work({"current": 5, "max": 20, "temp": 0}, "damage", [{"amount": 12}], [], set())
    hit_points.make(m.db, CH, {}, None, "damage", w)
    assert [c[:3] for c in m.calls] == [("add", CH, "hp"), ("down", CH), ("tell", CH, "down")]
    assert m.calls[0][3] == {"amount": -12} and not m.rows  # (no roll: nothing in Table rolls)

    m = Made(monkeypatch)
    w = hit_points.work({"current": 5, "max": 20, "temp": 0}, "damage", [{"amount": 12}], [], {"unconscious"})
    hit_points.make(m.db, CH, {}, None, "damage", w)
    assert [c[:3] for c in m.calls] == [("add", CH, "hp"), ("tell", CH, "down")]

    m = Made(monkeypatch)
    w = hit_points.work({"current": 5, "max": 20, "temp": 0}, "damage", [{"amount": 30}], [], set())
    hit_points.make(m.db, CH, {}, None, "damage", w)
    assert [c[:3] for c in m.calls] == [("add", CH, "hp"), ("down", CH), ("tell", CH, "massive")]
    assert [int(n) for n in re.findall(r"\d+", m.calls[-1][3])] == [25, 20]  # (left over, the maximum)

    m = Made(monkeypatch)
    w = hit_points.work({"current": 0, "max": 20, "temp": 0}, "damage", [{"amount": 3}], [], set(), crit=True)
    hit_points.make(m.db, CH, {}, None, "damage", w)
    assert [c[:3] for c in m.calls] == [("add", CH, "hp"), ("hit", CH, 2)]


def test_making_healing_and_temporary_hit_points(monkeypatch):
    m = Made(monkeypatch)
    w = hit_points.work({"current": 0, "max": 20, "temp": 0}, "heal", [{"amount": 7}], [], set())
    hit_points.make(m.db, CH, {}, None, "heal", w)
    assert [c[:4] for c in m.calls] == [("add", CH, "hp", {"amount": 7}), ("up", CH, 0, m.calls[1][3])]
    assert m.calls[1][3] == m.calls[0][4]  # (the healing is made once; up() only ends Unconscious)
    m = Made(monkeypatch)
    w = hit_points.work({"current": 18, "max": 20, "temp": 0}, "heal", [{"amount": 7}], [], set())
    text = hit_points.make(m.db, CH, {}, None, "heal", w)
    assert [c[:4] for c in m.calls] == [("add", CH, "hp", {"amount": 7})] and "2" in text.split()  # (says what it really healed)
    m = Made(monkeypatch)
    hit_points.make(m.db, CH, {}, None, "temp", hit_points.work(HP, "temp", [{"amount": 6}], [], set()))
    assert [c[:4] for c in m.calls] == [("add", CH, "temp", {"value": 6})]


@pytest.mark.parametrize("mode, w", [
    ("damage", hit_points.work(HP, "damage", [{"amount": 0}], [], set())),
    ("heal", hit_points.work(HP, "heal", [{"amount": 0}], [], set())),
    ("temp", hit_points.work({**HP, "temp": 9}, "temp", [{"amount": 4}], [], set())),
])
def test_nothing_to_make_sends_nothing(monkeypatch, mode, w):
    m = Made(monkeypatch)
    hit_points.make(m.db, CH, {}, None, mode, w)
    assert m.calls == []


def test_a_roll_it_came_from_says_so_once_in_table_rolls(monkeypatch):
    me = SimpleNamespace(id=12, name="", email="player@example.com")
    r = SimpleNamespace(id=30, campaign_id=2, visibility="dm")
    m = Made(monkeypatch, me)
    w = hit_points.work(HP, "damage", [{"amount": 8}], [], set(), None, "Moonbeam", SAVE)
    text = hit_points.make(m.db, CH, {"email": me.email}, r, "damage", w)
    [row] = m.rows
    assert (row.campaign_id, row.parent_id, row.character_id, row.user_id, row.who, row.label, row.kind, row.formula,
            row.dice, row.total, row.visibility, row.spec) == (2, 30, 4, 12, "player@example.com", text, "applied", "", [], 8, "dm",
                                                               {"mode": "damage", "conc": w["conc"]})
    assert m.calls[-1] == ("announce", 2, "rolls")
    m = Made(monkeypatch, None)  # (someone with no row of their own)
    hit_points.make(m.db, CH, {}, r, "heal", hit_points.work(HP, "heal", [{"amount": 3}], [], set()))
    assert (m.rows[0].user_id, m.rows[0].who, m.rows[0].total) == (None, "", 3)
    me.name = "N" * 100
    m = Made(monkeypatch, me)
    hit_points.make(m.db, SimpleNamespace(id=4, name="C" * 200), {}, r, "damage", hit_points.work(HP, "damage", [{"amount": 1}], [], set()))
    assert (len(m.rows[0].who), len(m.rows[0].label)) == (80, 120)


# ------------------------------------------------------------------ the character's own working, and who may apply


def test_the_characters_working_has_their_save_their_types_and_what_keeps_them_up(db, sheet, monkeypatch):
    cole = char(db, "Cole")
    cole.concentration = {"spell": "Moonbeam"}
    asked = []
    monkeypatch.setattr("app.rules_book.reminded", lambda summary, when: asked.append((summary["hit_points"]["max"], when)) or ["Last Stand"])
    w = hit_points.working(db, cole, "damage", [{"amount": 5, "type": "cold"}])
    assert (w["conc"]["spell"], w["conc"]["label"], w["conc"]["adv"]) == ("Moonbeam", "+2", True)  # (Cole's own save)
    assert w["defs"] == [] and w["first"] == [] and w["types"] == list(hit_points.TYPES) and w["form"] is None and w["keeps"] == []
    w = hit_points.working(db, cole, "damage", [{"amount": 60}])  # (37 of 51: down)
    assert w["keeps"] == ["Last Stand"] and asked == [(51, "zero")]
    cole.concentration = None
    assert hit_points.working(db, cole, "damage", [{"amount": 5}])["conc"] is None
    cole.wild_shape = "Polar Bear"
    w = hit_points.working(db, cole, "damage", [{"amount": 22, "type": "cold"}])
    assert w["form"]["beast"]["name"] == "Polar Bear" and w["first"] == ["cold"]
    assert w["types"][0] == "cold" and sorted(w["types"]) == sorted(hit_points.TYPES) and w["taken"] == 11


def test_the_characters_marks_at_zero_count(db, sheet):
    sheet["removedHitPoints"] = 51
    sheet["deathSaves"] = {"failCount": 2, "successCount": 0, "isStabilized": False}
    cole = char(db, "Cole")
    from app import characters

    characters.refresh(db, cole)
    w = hit_points.working(db, cole, "damage", [{"amount": 3}])
    assert w["hp_before"] == 0 and w["death_fail"] == 1 and "3" in w["steps"][-1]["why"]  # (2 before, so this makes 3)


def test_who_may_apply_and_to_whom(db, sheet):
    cole = char(db, "Cole")
    others = [c for c in db.scalars(select(Character)) if c.campaign_id == cole.campaign_id and c.id != cole.id]
    player = {"email": "player@example.com"}
    assert [c.id for c in hit_points.targets(db, player, cole.campaign_id)] == [cole.id]
    set_role(db, "dm@example.com")
    dm = {"email": "dm@example.com"}
    names = [c.name for c in hit_points.targets(db, dm, cole.campaign_id)]
    assert names == sorted(names) and "Cole" in names and len(names) == 1 + len(others)
    assert hit_points.targets(db, dm, cole.campaign_id + 1000) == []  # (only that campaign's)
    assert hit_points.can_apply(db, dm, cole) and not hit_points.can_apply(db, {"email": "someone@example.com"}, cole)


def test_the_window_is_the_owners_and_only_while_the_bridge_is_on(player, db, sheet):
    cole = char(db, "Cole")
    assert player.get(f"/characters/{cole.id}/hp").status_code == 200
    db.get(Campaign, cole.campaign_id).vtt_pieces = []  # (Sync with D&D Beyond off)
    db.commit()
    assert player.get(f"/characters/{cole.id}/hp").status_code == 404
    assert player.get("/characters/999999/hp").status_code == 404


# ------------------------------------------------------------------ Table rolls: Apply to whom


def test_apply_to_offers_the_dms_hits_and_anyones_healing(db, sheet, monkeypatch):
    cole = char(db, "Cole")
    cid = cole.campaign_id
    set_role(db, "dm@example.com")
    monkeypatch.setattr(hit_points, "targets", lambda db, user, campaign_id: [cole])
    dm = {"email": "dm@example.com"}
    lone = roll(db, cid, kind="attack", visibility="table")  # (no damage with it: nothing to apply)
    own = roll(db, cid, kind="damage", character_id=cole.id, visibility="table")  # (a character's own: goes to enemies)
    hit = roll(db, cid, kind="damage", visibility="dm")
    temp = roll(db, cid, kind="temp", character_id=cole.id, visibility="table", total=5)
    attack = roll(db, cid, kind="attack", visibility="table")
    dmg = roll(db, cid, kind="damage", parent_id=attack.id, visibility="table")
    done = TableRoll(campaign_id=cid, parent_id=hit.id, character_id=cole.id, label="Cole took 13", kind="applied", formula="", dice=[], total=13,
                     spec={"mode": "damage", "conc": {"spell": "Moonbeam", "dc": 10}})
    db.add(done)
    db.flush()
    info = hit_points.apply_info(db, dm, [lone, own, hit, temp, attack], [dmg, done])
    assert set(info) == {hit.id, temp.id, attack.id}
    assert info[hit.id]["to"] == [] and info[hit.id]["done"] == ["Cole took 13"] and info[hit.id]["dm"] is True
    assert info[hit.id]["conc"] == []  # (the save is the player's, not the DM's)
    assert [t["id"] for t in info[temp.id]["to"]] == [cole.id] and "waiting" not in info[temp.id]
    assert hit_points.apply_info(db, None, [temp], []) == {} and hit_points.apply_info(db, dm, [], []) == {}

    player = {"email": "player@example.com"}
    info = hit_points.apply_info(db, player, [hit, temp], [done])
    assert hit.id not in info  # (the DM's hidden roll: the player sees only that it happened)
    hit.visibility = "table"
    info = hit_points.apply_info(db, player, [hit, temp], [done])
    assert info[hit.id]["conc"] == [{"cid": cole.id, "name": "Cole", "spell": "Moonbeam", "dc": 10}] and info[hit.id]["dm"] is False
    from app import picks

    me = picks.user_row(db, player)
    mine = roll(db, cid, kind="heal", character_id=cole.id, visibility="self", user_id=me.id, total=3)  # (a just-me roll: its roller's)
    assert mine.id in hit_points.apply_info(db, player, [mine], []) and mine.id not in hit_points.apply_info(db, dm, [mine], [])


def test_healing_given_to_someone_waits_for_them(db, sheet, monkeypatch):
    cole = char(db, "Cole")
    other = next(c for c in db.scalars(select(Character)) if c.campaign_id == cole.campaign_id and c.id != cole.id)
    monkeypatch.setattr(hit_points, "targets", lambda db, user, campaign_id: [cole, other])
    set_role(db, "dm@example.com")
    dm = {"email": "dm@example.com"}
    given = roll(db, cole.campaign_id, kind="heal", character_id=cole.id, visibility="table", total=4, spec={"for": other.id})
    info = hit_points.apply_info(db, dm, [given], [])[given.id]
    assert [t["id"] for t in info["to"]] == [other.id] and info["waiting"] == other.name
    gone = roll(db, cole.campaign_id, kind="heal", character_id=cole.id, visibility="table", total=4, spec={"for": 999999})
    assert hit_points.apply_info(db, dm, [gone], [])[gone.id]["waiting"] == "them"  # (someone no longer at the table)
    taken_back = roll(db, cole.campaign_id, kind="heal", character_id=cole.id, visibility="table", total=0, spec={"for": other.id})
    info = hit_points.apply_info(db, dm, [taken_back], [])[taken_back.id]
    assert info["to"] == [] and "waiting" not in info
    applied = TableRoll(campaign_id=cole.campaign_id, parent_id=given.id, character_id=other.id, label="x", kind="applied", formula="", dice=[], total=4)
    db.add(applied)
    db.flush()
    assert "waiting" not in hit_points.apply_info(db, dm, [given], [applied])[given.id]
