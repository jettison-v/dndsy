"""Table rolls (app/table_rolls.py): the server rolls, stores each roll, and shows it only to
whoever may see it. DM-only rolls tell everyone else that a roll happened, never the number."""

import re

import pytest
from sqlalchemy import select

from app import table_rolls as tr
from app.importer import import_bundle
from app.models import TableRoll
from tests.test_characters import BUNDLE, char, no_network, owned_by  # noqa: F401


def seq(*values):
    """A fake die that returns these values in order."""
    it = iter(values)
    return lambda sides: next(it)


# ------------------------------------------------------------------ rolling

def test_d20_keeps_the_higher_on_advantage_and_the_lower_on_disadvantage():
    assert tr.roll_d20(7, "normal", seq(12)) == {"dice": [12], "kept": 12, "modifier": 7, "total": 19, "formula": "d20+7"}
    assert tr.roll_d20(3, "adv", seq(4, 17))["kept"] == 17
    r = tr.roll_d20(-1, "dis", seq(4, 17))
    assert r["kept"] == 4 and r["total"] == 3 and r["dice"] == [4, 17] and r["formula"] == "d20−1"


def test_damage_doubles_the_dice_on_a_critical_hit_but_not_the_bonus():
    assert tr.roll_damage("2d6+3", roll=seq(1, 6)) == {"dice": [1, 6], "kept": None, "modifier": 3, "total": 10, "formula": "2d6+3"}
    crit = tr.roll_damage("2d6+3", crit=True, roll=seq(1, 2, 3, 4))
    assert crit["dice"] == [1, 2, 3, 4] and crit["total"] == 13 and crit["formula"] == "4d6+3"
    assert tr.roll_damage("1d4-5", roll=seq(1))["total"] == 0  # never below zero
    assert tr.roll_damage("lots") is None and tr.roll_damage("99d6") is None and tr.roll_damage("1d1") is None


def test_formulas_mix_dice():
    assert tr.parse_formula("2d6 + 1d8 - 1") == ([(2, 6), (1, 8)], -1)
    assert tr.parse_formula("d6") is None and tr.parse_formula("5") is None and tr.parse_formula("1d6-1d4") is None
    assert tr.parse_extras(["Bless:+1d4", "Other: -2"]) == [("Bless", 1, 1, 4), ("Other", -1, 2, 0)]
    assert tr.parse_extras(["Bless:1d4"]) is None


def test_real_dice_stay_in_range():
    for _ in range(300):
        r = tr.roll_d20(0, "adv")
        assert all(1 <= d <= 20 for d in r["dice"]) and r["kept"] == max(r["dice"])


# ------------------------------------------------------------------ visibility

def test_who_sees_what():
    def roll(to, user_id=1):
        return TableRoll(visibility=to, user_id=user_id)
    # (viewer id, viewer is the DM) -> what they get
    table, dm_only, mine = roll("table"), roll("dm"), roll("self")
    assert [tr.shown(table, v, d) for v, d in [(1, False), (2, False), (3, True)]] == ["full"] * 3
    assert tr.shown(dm_only, 1, False) == "full"  # the roller
    assert tr.shown(dm_only, 3, True) == "full"  # the DM
    assert tr.shown(dm_only, 2, False) == "hidden"  # another player: only that a roll happened
    assert tr.shown(mine, 1, False) == "full"
    assert tr.shown(mine, 2, False) is None and tr.shown(mine, 3, True) is None  # not even the DM


# ------------------------------------------------------------------ the API

@pytest.fixture
def table(db, monkeypatch):
    """Cole is played by player@, Trah by other@; dm@ is the DM and plays no one.
    A signed-in client per person."""
    from fastapi.testclient import TestClient

    from app import auth, config
    from app.config import parse_allowlist
    from app.db import get_db
    from app.main import app
    from app.models import User

    import_bundle(db, BUNDLE)
    owned_by(db, char(db, "Cole"), "player@example.com")
    owned_by(db, char(db, "Trah"), "other@example.com")
    db.add(User(email="dm@example.com", name="Dee", is_dm=True))
    db.flush()
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("dm@example.com,player@example.com,other@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    people = {}
    for who in ("player", "other", "dm"):
        async def token(request, email=f"{who}@example.com"):
            return {"userinfo": {"email": email, "email_verified": True, "name": who}}

        monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
        people[who] = TestClient(app)
        people[who].get("/auth/callback", follow_redirects=False)
    yield people
    app.dependency_overrides.clear()


def post(c, **data):
    return c.post("/rolls", data=data)


def numbers(html):
    return re.findall(r'class="roll-total">(\d+)<', html)


def test_a_player_rolls_for_their_own_character_on_the_server(table, db, monkeypatch):
    monkeypatch.setattr(tr, "die", lambda sides: 15)
    cole = char(db, "Cole")
    r = post(table["player"], character=cole.id, kind="save", label="Wis save", mod="+8", mode="normal", to="table")
    assert r.status_code == 200
    body = r.json()
    assert body["roll"]["total"] == 23 and body["roll"]["main"]["dice"] == [15] and body["roll"]["to"] == "table"
    assert 'data-mine="1"' in body["html"] and "Wis save" in body["html"]
    row = db.scalar(select(TableRoll))
    assert (row.character_id, row.kind, row.label, row.kept, row.modifier, row.total, row.mode, row.visibility) == \
        (cole.id, "save", "Wis save", 15, 8, 23, "normal", "table")
    assert row.user_id == cole.owner_id and row.campaign_id == cole.entity.campaign_id and row.created_at is not None


def test_the_browser_never_chooses_the_number(table, db):
    cole = char(db, "Cole")
    r = post(table["player"], character=cole.id, kind="check", label="Initiative", mod="3", total="99", dice="20", to="table")
    row = db.scalar(select(TableRoll))
    assert r.status_code == 200 and row.total == row.kept + 3 and 1 <= row.kept <= 20


def test_only_the_characters_player_rolls_for_it(table, db):
    cole = char(db, "Cole")
    for who in ("other", "dm"):
        r = post(table[who], character=cole.id, kind="save", label="Wis save", mod="8")
        assert r.status_code == 403 and "Cole's player" in r.json()["error"]
    assert db.scalar(select(TableRoll)) is None
    assert table["player"].post("/rolls", data={"character": 99999, "kind": "save", "label": "x"}).status_code == 404


def test_bad_rolls_are_refused(table, db):
    cid = char(db, "Cole").id
    for bad in ({"kind": "nonsense", "label": "x"}, {"kind": "save", "label": ""}, {"kind": "save", "label": "x", "mod": "+999"},
                {"kind": "save", "label": "x", "to": "everyone"}, {"kind": "save", "label": "x", "mode": "triple"},
                {"kind": "damage", "label": "x", "dmg": "a lot"}, {"kind": "save", "label": "x", "extra": "Bless:+1d4; drop table"},
                {"kind": "dice", "dmg": "99d6"}, {"kind": "save", "label": "x", "extra": ["Bless:+1d4"] * 7}):
        assert post(table["player"], character=cid, **bad).status_code == 400, bad


def test_advantage_that_always_applies_rolls_two_dice(table, db):
    r = post(table["player"], character=char(db, "Cole").id, kind="save", label="Wis save", mod="8", adv="1").json()["roll"]
    assert r["main"]["mode"] == "adv" and len(r["main"]["dice"]) == 2 and r["main"]["dice"][r["main"]["kept_at"]] == max(r["main"]["dice"])
    r = post(table["player"], character=char(db, "Cole").id, kind="save", label="Wis save", mod="8", adv="1", mode="dis").json()["roll"]
    assert r["main"]["mode"] == "dis" and r["main"]["dice"][r["main"]["kept_at"]] == min(r["main"]["dice"])  # the chosen Disadvantage wins


def test_situational_bonuses_are_rolled_and_added(table, db, monkeypatch):
    monkeypatch.setattr(tr, "die", lambda sides: {20: 10, 4: 3}[sides])
    r = post(table["player"], character=char(db, "Cole").id, kind="save", label="Wis save", mod="8",
             extra=["Bless:+1d4", "Bane:-1d4", "Other:+2", "Exhaustion 2:-4"]).json()
    assert r["roll"]["total"] == 10 + 8 + 3 - 3 + 2 - 4
    assert [x["label"] for x in r["roll"]["main"]["extras"]] == ["Bless", "Bane", "Other", "Exhaustion 2"]
    assert "Bless +3" in r["html"] and "Exhaustion 2 −4" in r["html"]


def test_damage_belongs_to_its_attack_and_doubles_on_a_natural_20(table, db, monkeypatch):
    cid = char(db, "Cole").id
    monkeypatch.setattr(tr, "die", lambda sides: 20 if sides == 20 else 3)
    attack = post(table["player"], character=cid, kind="attack", label="Rend", mod="6", dmg="2d6+4", to="dm").json()["roll"]
    assert attack["nat"] == 20 and attack["can"]["damage"] == "2d6+4"
    assert 'data-follow="damage"' in table["player"].get("/rolls").text
    assert "roll-follow" not in table["dm"].get("/rolls").text  # only the roller gets the button
    r = post(table["player"], parent=attack["id"], action="damage", extra="Hunter's Mark:+1d6").json()["roll"]
    assert r["id"] == attack["id"] and r["total"] == 26  # still the attack, now with its damage
    d = r["damage"]
    assert d["crit"] and d["formula"] == "4d6+4" and d["total"] == 4 * 3 + 4 + 2 * 3  # Hunter's Mark doubled too
    row = db.scalar(select(TableRoll).where(TableRoll.parent_id == attack["id"]))
    assert row.kind == "damage" and row.visibility == "dm" and row.label == "Rend"  # same audience as the attack
    assert post(table["player"], parent=attack["id"], action="damage").status_code == 409  # once
    assert post(table["other"], parent=attack["id"], action="damage").status_code == 403  # nobody else's
    log = table["player"].get("/rolls").text
    assert log.count('class="roll-item') == 1 and "Critical damage" in log and "roll-follow" not in log


def test_no_damage_after_a_natural_1(table, db, monkeypatch):
    monkeypatch.setattr(tr, "die", lambda sides: 1)
    r = post(table["player"], character=char(db, "Cole").id, kind="attack", label="Rend", mod="6", dmg="2d6+4").json()
    assert r["roll"]["nat"] == 1 and r["roll"]["can"]["damage"] == "" and 'data-follow="damage"' not in r["html"]
    assert post(table["player"], parent=r["roll"]["id"], action="damage").status_code == 409


def test_healing_is_its_own_kind(table, db, monkeypatch):
    monkeypatch.setattr(tr, "die", lambda sides: 4)
    r = post(table["player"], character=char(db, "Cole").id, kind="heal", label="Healing Word", dmg="2d4", extra="Other:+4").json()
    assert r["roll"]["kind"] == "heal" and r["roll"]["total"] == 12 and "healing" in r["html"] and "damage" not in r["html"]


def test_a_reroll_replaces_the_result_and_shows_the_old_one(table, db, monkeypatch):
    rolls = iter([3, 17])
    monkeypatch.setattr(tr, "die", lambda sides: next(rolls))
    first = post(table["player"], character=char(db, "Cole").id, kind="check", label="Stealth check", mod="6").json()["roll"]
    assert first["total"] == 9
    assert post(table["player"], parent=first["id"], action="reroll", label="Anything").status_code == 409  # a known reason only
    r = post(table["player"], parent=first["id"], action="reroll", label="Heroic Inspiration").json()
    assert r["roll"]["total"] == 23 and r["roll"]["rerolled"]["total"] == 9 and "was <s>9</s>" in r["html"]
    assert post(table["player"], parent=first["id"], action="reroll", label="Luck").status_code == 409  # once


def test_an_added_die_counts_toward_the_total(table, db, monkeypatch):
    monkeypatch.setattr(tr, "die", lambda sides: {20: 8, 8: 5}[sides])
    first = post(table["player"], character=char(db, "Cole").id, kind="save", label="Con save", mod="2").json()["roll"]
    r = post(table["player"], parent=first["id"], action="bonus", die="8").json()["roll"]
    assert r["total"] == 15 and r["bonus"] == {"label": "Bardic Inspiration", "formula": "1d8", "dice": [5], "total": 5}
    assert post(table["player"], parent=first["id"], action="bonus", die="7").status_code == 409


def test_death_saves_say_what_happened(table, db, monkeypatch):
    cid = char(db, "Cole").id
    for value, outcome in ((20, "regain 1 Hit Point"), (1, "two failures"), (12, "success"), (9, "failure")):
        monkeypatch.setattr(tr, "die", lambda sides, v=value: v)
        r = post(table["player"], character=cid, kind="death", label="Death save", mod="+5").json()["roll"]
        assert outcome in r["outcome"] and r["main"]["modifier"] == 0  # no bonus sneaks in


def test_plain_dice_for_anyone_and_the_dms_behind_the_screen(table, db, monkeypatch):
    monkeypatch.setattr(tr, "die", lambda sides: 2)
    r = post(table["player"], kind="dice", label="", dmg="2d6+1d8+3", character=char(db, "Cole").id).json()["roll"]
    assert r["label"] == "Dice" and r["total"] == 9 and r["name"] == "Cole"
    dm = post(table["dm"], kind="dice", label="Ambush", dmg="1d20", to="dm").json()["roll"]
    assert dm["name"] == "DM" and dm["total"] == 2
    other = table["other"].get("/rolls").text
    assert "Rolled behind the screen" in other and "Ambush" not in other
    assert post(table["dm"], kind="save", label="x", mod="1").status_code == 404  # the DM has no character


def test_quick_checks_for_your_character(table, db):
    from app import characters

    characters.refresh(db, char(db, "Cole"))
    page = table["player"].get("/rolls/checks").text
    assert 'data-roll="check" data-label="Perception check"' in page and 'data-roll="death"' in page and 'data-label="Hit Die"' in page
    assert "data-roll" not in table["dm"].get("/rolls/checks").text


def test_the_log_shows_each_viewer_only_what_they_may_see(table, db, monkeypatch):
    monkeypatch.setattr(tr, "die", lambda sides: 11)
    cid = char(db, "Cole").id
    post(table["player"], character=cid, kind="save", label="Con save", mod="2", to="table")  # 13
    post(table["player"], character=cid, kind="check", label="Stealth check", mod="6", to="dm")  # 17
    post(table["player"], character=cid, kind="check", label="Insight check", mod="9", to="self")  # 20

    mine = table["player"].get("/rolls").text
    assert numbers(mine) == ["20", "17", "13"] and "Insight check" in mine and "Stealth check" in mine

    dm_view = table["dm"].get("/rolls").text
    assert numbers(dm_view) == ["17", "13"] and "Stealth check" in dm_view
    assert "Insight check" not in dm_view and "20" not in numbers(dm_view)  # just-me: not even the DM

    other = table["other"].get("/rolls").text
    assert numbers(other) == ["13"] and "Rolled for the DM" in other
    hidden = other.split('class="roll-item')[1]  # newest first: the DM-only roll
    assert "hidden-roll" in hidden and "Cole" in hidden
    assert not re.search(r">\s*(17|11|6)\s*<", hidden) and "d20" not in hidden  # no total, die or bonus
    assert "Stealth" not in other and "Insight" not in other
    assert 'data-mine="1"' not in other


def test_a_hidden_roll_stays_hidden_with_its_damage(table, db, monkeypatch):
    monkeypatch.setattr(tr, "die", lambda sides: 12)
    attack = post(table["player"], character=char(db, "Cole").id, kind="attack", label="Rend", mod="6", dmg="2d6+4", to="dm").json()["roll"]
    post(table["player"], parent=attack["id"], action="damage")
    other = table["other"].get("/rolls").text
    assert "Rolled for the DM" in other and "Rend" not in other and "Damage" not in other and "roll-total" not in other


def test_polling_returns_only_new_rolls_and_nothing_when_quiet(table, db):
    cid = char(db, "Cole").id
    first = post(table["player"], character=cid, kind="save", label="Str save", mod="0").json()["roll"]["id"]
    assert table["other"].get(f"/rolls?since={first}").status_code == 204
    second = post(table["player"], character=cid, kind="save", label="Dex save", mod="0").json()["roll"]["id"]
    new = table["other"].get(f"/rolls?since={first}")
    assert new.status_code == 200 and f'data-id="{second}"' in new.text and f'data-id="{first}"' not in new.text
    # a just-me roll isn't news to anyone else
    post(table["player"], character=cid, kind="save", label="Int save", mod="0", to="self")
    assert table["other"].get(f"/rolls?since={second}").status_code == 204
    # a follow-up brings its roll back, whole, with the newest row as its place in the log
    bonus = post(table["player"], parent=second, action="bonus", die="6").json()["roll"]
    again = table["other"].get(f"/rolls?since={second + 1}")
    assert again.status_code == 200 and f'data-id="{second}"' in again.text and f'data-seq="{bonus["seq"]}"' in again.text


def test_an_empty_log_says_so(table):
    assert "No rolls yet" in table["other"].get("/rolls").text
    assert table["other"].get("/rolls?since=0").status_code == 204


def test_rolls_need_sign_in(db):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    app.dependency_overrides[get_db] = lambda: db
    try:
        c = TestClient(app)
        assert c.get("/rolls").status_code == 401
        assert c.post("/rolls", data={"kind": "save", "label": "x"}).status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_the_sidebar_is_on_every_page_and_knows_your_character(table, db):
    cole = char(db, "Cole")
    for path in ("/", f"/characters/{cole.id}/battle", "/party"):
        page = table["player"].get(path).text
        assert 'id="table-rolls"' in page and f'data-mine="{cole.id}"' in page, path
    assert 'data-play="1"' in table["player"].get(f"/characters/{cole.id}/battle").text
    assert 'data-play=""' in table["player"].get("/party").text
    assert 'data-mine=""' in table["dm"].get("/party").text  # the DM has no character to roll for
    assert "rs-checks" not in table["dm"].get("/party").text and "Manual roll" in table["dm"].get("/party").text


# ------------------------------------------------------------------ what can roll

def test_rollable_finds_dice_in_the_text():
    from app.character_views import rollable

    potion = rollable({"name": "Use an item: Potion of Healing", "kind": "item", "meta": "This potion is a magic item.",
                       "text": "The creature regains 2d4 + 2 Hit Points."})
    assert potion["dice"] == "2d4+2" and potion["heal"]
    wind = rollable({"name": "Second Wind", "kind": "feature", "meta": "", "summary": "You regain 1d10+1 HP."})
    assert wind["dice"] == "1d10+1" and wind["heal"]
    redirect = rollable({"name": "Redirect Attack", "kind": "feature", "meta": "", "text": "takes 2d8 + 4 Force damage"})
    assert redirect["dice"] == "2d8+4" and not redirect["heal"]
    beads = rollable({"name": "Necklace of Prayer Beads", "kind": "item", "meta": "", "text": "has 1d4 + 2 magic beads"})
    assert beads["dice"] == ""  # a count, not a roll
    flurry = rollable({"name": "Flurry of Blows", "kind": "feature", "hit": "", "meta": "", "text": "make two Unarmed Strikes"},
                      {"to_hit": "+6", "damage": "1d6+3 bludgeoning"})
    assert flurry["hit"] == "+6" and flurry["dice"] == "1d6+3"


def test_the_detail_panel_rolls(table, db):
    from app import characters

    cole = char(db, "Cole")
    characters.refresh(db, cole)
    panel = table["player"].get(f"/characters/{cole.id}/detail", params={"ref": "action:Flurry of Blows"}).text
    assert "<dt>Roll</dt>" in panel and 'data-roll="attack" data-label="Flurry of Blows"' in panel
    every = table["player"].get(f"/characters/{cole.id}/all/bonus").text  # Play's "See all"
    assert 'data-label="Flurry of Blows" data-mod="+' in every
