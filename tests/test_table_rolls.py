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
    assert body["roll"]["total"] == 23 and body["roll"]["dice"] == [15] and body["roll"]["to"] == "table"
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
                {"kind": "damage", "label": "x", "dmg": "a lot"}):
        assert post(table["player"], character=cid, **bad).status_code == 400, bad


def test_advantage_that_always_applies_rolls_two_dice(table, db):
    r = post(table["player"], character=char(db, "Cole").id, kind="save", label="Wis save", mod="8", adv="1").json()["roll"]
    assert r["mode"] == "adv" and len(r["dice"]) == 2 and r["kept"] == max(r["dice"])
    r = post(table["player"], character=char(db, "Cole").id, kind="save", label="Wis save", mod="8", adv="1", mode="dis").json()["roll"]
    assert r["mode"] == "dis" and r["kept"] == min(r["dice"])  # the chosen Disadvantage wins


def test_damage_after_an_attack_comes_from_the_attack_and_doubles_on_a_natural_20(table, db, monkeypatch):
    cid = char(db, "Cole").id
    monkeypatch.setattr(tr, "die", lambda sides: 20 if sides == 20 else 3)
    attack = post(table["player"], character=cid, kind="attack", label="Rend", mod="6", dmg="2d6+4", to="dm").json()["roll"]
    assert attack["nat"] == 20 and attack["damage"] == "2d6+4"
    assert "Roll critical damage (2d6+4)" in table["player"].get("/rolls").text
    assert "roll-dmg" not in table["dm"].get("/rolls").text  # only the roller gets the button
    dmg = post(table["player"], after=attack["id"]).json()["roll"]
    assert dmg["kind"] == "damage" and dmg["crit"] and dmg["formula"] == "4d6+4" and dmg["total"] == 16
    assert dmg["label"] == "Rend" and dmg["to"] == "dm"  # same audience as the attack
    # nobody else rolls damage for someone's attack
    assert post(table["other"], after=attack["id"]).status_code == 403
    # once something newer is rolled, the old attack no longer offers damage
    assert "roll-dmg" not in table["player"].get("/rolls").text


def test_no_damage_button_after_a_natural_1(table, db, monkeypatch):
    monkeypatch.setattr(tr, "die", lambda sides: 1)
    r = post(table["player"], character=char(db, "Cole").id, kind="attack", label="Rend", mod="6", dmg="2d6+4").json()
    assert r["roll"]["nat"] == 1 and r["roll"]["damage"] == "" and "roll-dmg" not in r["html"]


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
