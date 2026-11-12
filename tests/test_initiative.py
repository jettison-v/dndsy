"""Initiative from askdnd (app/initiative.py; Brett, Nov 4: docs/mockups/initiative/, DECISIONS): everyone rolls their own
before Start Combat and the number fills D&D Beyond's VTT, a familiar with its character, a Homunculus right after its
master; after Start Combat the order is the DM's, changed by dragging a row. Numbers go through the DM's open VTT page
(extension 0.12.0), which asks for them; what's asked for shows at once, on its way, until the VTT shows it."""

import copy
import json
from datetime import UTC, datetime, timedelta

import pytest

from app import fight, initiative
from app.models import Campaign, TableRoll
from tests.roles import set_role
from tests.table_setup import char

GAME = "9001"


def entry(key, name, ini, kind="monster", character=None, group="Enemy", gkey=None, active=False, **more):
    return {"key": key, "name": name, "kind": kind, "character": character, "initiative": ini, "hidden": False,
            "active": active, "image": None, "monster": None, "group": group, "gkey": gkey or key, **more}


def heard(cole_ini=None, waiting=True, active=None):
    """What extension 0.12.0 says (vtt-page.js `told()`): before Start Combat, everyone the DM added; each with where
    the combat sidebar keeps it."""
    order = [{"key": "t-cole", "name": "Cole", "kind": "character", "ddb_id": "75423618", "initiative": cole_ini,
              "group": "Party Member", "gkey": "t-cole"},
             {"key": "t-e1", "name": "Enemy 1", "kind": "monster", "initiative": 12, "group": "Enemy", "gkey": "4904825"},
             {"key": "t-owl", "name": "Owl", "kind": "companion", "initiative": None, "group": "Party Member", "gkey": "25982053"}]
    for x in order:
        x["active"] = x["key"] == active
    order.sort(key=lambda x: -x["initiative"] if x["initiative"] is not None else 99)  # (as the VTT orders them)
    return {"waiting": True, "round": 0, "turn": 0, "order": order} if waiting else {"round": 1, "turn": 1, "order": order}


@pytest.fixture
def table(db, sheet):
    """Cole's campaign follows D&D Beyond game 9001, with Initiative from askdnd on (Labs) and a DM."""
    c = db.get(Campaign, char(db, "Cole").campaign_id)
    c.ddb_campaign_id = GAME
    c.vtt_pieces = ["sync", "labs", "initiative"]
    set_role(db, "dm@example.com", "dm")
    set_role(db, "player@example.com", "player")
    db.flush()
    return c


# ---- the number a dragged row gets (board 5)

def order(*pairs):
    return [entry(f"k{i}", name, ini) for i, (name, ini) in enumerate(pairs)]


def test_a_dragged_row_takes_a_number_between_its_new_neighbours_and_moves_no_one_else():
    """Brett, Nov 4 (board 5): a whole number between when there's room, else half way (D&D Beyond keeps 11.5 and
    orders by it, tried on the Mac Mini); only between two that share a number does the one below change."""
    o = order(("Trah", 17), ("Big C", 15), ("Enemy 1", 12), ("Cole", 11), ("Enemy 2", 10))
    assert initiative.plan(o, "k0", 2) == {"initiative": 13, "moves": {"k0": 13}}  # between 15 and 12
    assert initiative.plan(o, "k0", 3) == {"initiative": 11.5, "moves": {"k0": 11.5}}  # between 12 and 11
    assert initiative.plan(o, "k4", 0) == {"initiative": 18, "moves": {"k4": 18}}  # to the top
    assert initiative.plan(o, "k0", 5) == {"initiative": 9, "moves": {"k0": 9}}  # to the bottom
    assert initiative.plan(o, "k0", 0) is None and initiative.plan(o, "k0", 1) is None  # (where it is)
    tie = order(("Trah", 17), ("Pip", 12), ("Enemy 1", 12), ("Cole", 11))
    assert initiative.plan(tie, "k0", 2) == {"initiative": 11.75, "moves": {"k2": 11.5, "k0": 11.75}}


def test_a_creature_that_acts_right_after_its_master_moves_with_it():
    vi = entry("t-vi", "Vi", 14, kind="character", character=7)
    hom = entry("t-hom", "Homunculus Servant", 13.5, kind="companion", creature={"master": 7, "own": False})
    o = [entry("t-a", "Big C", 15), vi, hom, entry("t-b", "Enemy 1", 12), entry("t-c", "Cole", 9)]
    assert initiative.plan(o, "t-vi", 3) == {"initiative": 10, "moves": {"t-vi": 10, "t-hom": 9.5}}  # between 12 and 9
    synthetic = {**hom, "key": "cr:7:3"}  # (one the VTT hasn't got: nothing to set there)
    assert initiative.plan([o[0], vi, synthetic, *o[3:]], "t-vi", 0)["moves"] == {"t-vi": 16}


# ---- before Start Combat: who's waiting

def test_before_start_combat_askdnd_hears_who_is_waiting_only_with_initiative_from_askdnd(player, db, table):
    r = player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    assert r.json()["changed"] is True and table.fight["waiting"] is True
    assert [(x["name"], x["group"], x["gkey"], x["active"]) for x in table.fight["order"]][:2] == \
        [("Enemy 1", "Enemy", "4904825", False), ("Cole", "Party Member", "t-cole", False)]
    shown = fight.shown(table, True)
    assert shown["waiting"] is True and shown["now"] is None and shown["next"] is None  # (no one's turn yet)
    table.vtt_pieces = ["sync"]
    assert fight.shown(table, True) is None  # (without it, as before: nothing until Start Combat)


# ---- numbers asked for, on their way, made

def test_a_number_shows_at_once_on_its_way_and_is_made_once_the_vtt_shows_it(player, db, table):
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    fight.lock(db, table)
    f = copy.deepcopy(table.fight)
    assert initiative.want(f, "t-owl", 14) is True
    owl = next(x for x in f["order"] if x["key"] == "t-owl")
    assert owl["initiative"] == 14 and owl["pending"] and [x["key"] for x in f["order"]][0] == "t-owl"
    assert initiative.due(f) == [{"id": f["sets"][0]["id"], "group": "Party Member", "key": "25982053", "initiative": 14}]
    assert initiative.due(f) == []  # (handed out: again only after RESEND)
    table.fight = f
    db.commit()
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})  # the VTT doesn't show it yet: still on its way
    assert table.fight["sets"] and next(x for x in table.fight["order"] if x["key"] == "t-owl")["initiative"] == 14
    told = heard()
    told["order"][2]["initiative"] = 14
    player.post(f"/bridge/fight/{GAME}", json={"fight": told})  # it does now: made
    assert table.fight["sets"] == [] and not next(x for x in table.fight["order"] if x["key"] == "t-owl").get("pending")


def test_one_the_vtt_never_shows_is_dropped_and_its_own_number_shows_again(player, db, table):
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    fight.lock(db, table)
    f = copy.deepcopy(table.fight)
    initiative.want(f, "t-owl", 14)
    f["sets"][0]["at"] = (datetime.now(UTC) - initiative.GIVE_UP - timedelta(seconds=1)).isoformat()
    table.fight = f
    db.commit()
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    assert table.fight["sets"] == [] and next(x for x in table.fight["order"] if x["key"] == "t-owl")["initiative"] is None


def test_an_entry_without_where_the_vtt_keeps_it_cannot_be_set(db, table):
    """An extension before 0.12.0 doesn't say (`group`, `gkey`): nothing is asked for that couldn't be made."""
    f = {"order": [entry("t1", "Cole", 10, group=None)]}
    assert initiative.want(f, "t1", 14) is False and "sets" not in f


def test_only_the_dms_vtt_page_is_given_numbers_to_set(player, dm, db, table):
    """A standing rule (Brett, Nov 4; D&D Beyond's own: only the DM changes the order): a player's VTT page is given
    nothing to send and asks once a minute; the DM's asks every few seconds and is given what's waiting."""
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    fight.lock(db, table)
    f = copy.deepcopy(table.fight)
    initiative.want(f, "t-owl", 14)
    table.fight = f
    db.commit()
    assert player.post(f"/bridge/vtt/{GAME}").json() == {"sets": [], "every": initiative.IDLE}
    got = dm.post(f"/bridge/vtt/{GAME}").json()
    assert got["every"] == initiative.TICK and [(s["key"], s["initiative"]) for s in got["sets"]] == [("25982053", 14)]
    db.refresh(table)
    assert initiative.dm_here(table)


# ---- the DM changes the order

def test_the_dm_drags_a_row_and_undo_puts_it_back(dm, player, db, table):
    """Board 5: the number it gets, shown at once and on its way; the corner card's Undo sends the numbers back."""
    told = heard(cole_ini=8, waiting=False, active="t-e1")
    player.post(f"/bridge/fight/{GAME}", json={"fight": told})
    r = dm.post("/fight/initiative", data={"key": "t-cole", "slot": 0})
    j = r.json()
    assert r.status_code == 200 and j["text"].startswith("Cole: 8 → 13") and j["back"] == [{"key": "t-cole", "initiative": 8}]
    db.refresh(table)
    assert [x["name"] for x in table.fight["order"]][:2] == ["Cole", "Enemy 1"] and table.fight["order"][0]["pending"]
    assert table.fight["order"][1]["active"]  # (whose turn it is stays theirs)
    assert dm.post("/fight/initiative", data={"key": "t-cole", "to": "16"}).json()["text"].startswith("Cole: 13 → 16")
    dm.post("/fight/initiative", data={"back": json.dumps([{"key": "t-cole", "initiative": 8}])})
    db.refresh(table)
    cole = next(x for x in table.fight["order"] if x["key"] == "t-cole")
    assert cole["initiative"] == 8 and not cole["pending"] and table.fight["sets"] == []  # (back to what the VTT has: nothing to send)


def test_only_the_dm_changes_the_order(player, db, table):
    """A standing rule (Brett, Nov 4; as in D&D Beyond): a player sees the order and can't change it."""
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard(cole_ini=8, waiting=False, active="t-e1")})
    r = player.post("/fight/initiative", data={"key": "t-cole", "slot": 0})
    assert r.status_code == 403
    db.refresh(table)
    assert not table.fight.get("sets")


def test_a_dm_whose_vtt_says_nothing_of_where_to_set_it_is_told_to_update_the_extension(dm, player, db, table):
    told = heard(cole_ini=8, waiting=False, active="t-e1")
    for x in told["order"]:
        x.pop("group"), x.pop("gkey")
    player.post(f"/bridge/fight/{GAME}", json={"fight": told})
    r = dm.post("/fight/initiative", data={"key": "t-cole", "slot": 0})
    assert r.status_code == 409 and "0.12.0" in r.json()["error"]


# ---- rolling in askdnd

def test_a_characters_initiative_before_start_combat_sets_its_number_and_rolls_its_familiar(player, db, table, monkeypatch):
    """Brett, Nov 4 (board 2): one press rolls the character's and its familiar's, each its own roll, as the rules have
    a familiar roll its own; each number goes to its token in the VTT's sidebar."""
    cole = char(db, "Cole")
    owl = {"master": cole, "k": {"id": 3, "name": "Owl", "kind": "Owl", "own_initiative": True, "initiative": "+3", "role": "familiar",
                                 "hp": {"current": 1, "max": 1}, "ac": 11, "turn_short": "Its own Initiative", "turn": "", "picture": None}}
    monkeypatch.setattr(fight, "creatures_here", lambda db, campaign: [owl])
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard()})
    r = player.post("/rolls", data={"character": cole.id, "kind": "check", "label": "Initiative", "mod": "+2"},
                    headers={"X-Requested-With": "fetch"})
    j = r.json()
    assert r.status_code == 200 and [a["who"] for a in j["also"]] == ["Owl"]
    rolls = db.query(TableRoll).filter(TableRoll.label == "Initiative").order_by(TableRoll.id).all()
    assert [x.who for x in rolls] == ["", "Owl"] and rolls[1].modifier == 3
    db.refresh(table)
    by = {x["key"]: x for x in table.fight["order"]}
    assert by["t-cole"]["initiative"] == rolls[0].total and by["t-owl"]["initiative"] == rolls[1].total
    assert {s["key"] for s in table.fight["sets"]} == {"t-cole", "t-owl"}


def test_a_test_copy_sharing_the_sheet_never_takes_the_characters_token(player, db, table, monkeypatch):
    """A test campaign can hold a test copy sharing its original's D&D Beyond id, and which one a token named came down
    to the database's order (found looking into the Mini's initiative run, Nov 12): the original's, and its own roll
    is queued for the VTT."""
    from app import characters

    cole = char(db, "Cole")
    characters.test_copy(db, cole, table.id)  # (a later id: the one a plain lookup by D&D Beyond id kept)
    monkeypatch.setattr(fight, "creatures_here", lambda db, campaign: [])
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard(cole_ini=11)})
    db.refresh(table)
    assert next(x for x in table.fight["order"] if x["key"] == "t-cole")["character"] == cole.id
    player.post("/rolls", data={"character": cole.id, "kind": "check", "label": "Initiative", "mod": "+2"}, headers={"X-Requested-With": "fetch"})
    db.refresh(table)
    assert [s["key"] for s in table.fight.get("sets") or []] in (["t-cole"], [])  # ([] only if it rolled the 11 it has)
    assert next(x for x in table.fight["order"] if x["key"] == "t-cole")["initiative"] == db.query(TableRoll).order_by(TableRoll.id.desc()).first().total


def test_after_start_combat_a_roll_changes_nothing(player, db, table, monkeypatch):
    """The table's way (Brett, Nov 4, board 4): after Start Combat the order is the DM's."""
    cole = char(db, "Cole")
    monkeypatch.setattr(fight, "creatures_here", lambda db, campaign: [])
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard(cole_ini=8, waiting=False, active="t-e1")})
    r = player.post("/rolls", data={"character": cole.id, "kind": "check", "label": "Initiative", "mod": "+2"},
                    headers={"X-Requested-With": "fetch"})
    assert r.status_code == 200 and "also" not in r.json()
    db.refresh(table)
    assert not table.fight.get("sets") and next(x for x in table.fight["order"] if x["key"] == "t-cole")["initiative"] == 8


def test_a_homunculus_goes_right_after_its_master(player, db, table, monkeypatch):
    """A creature that takes its turn right after its master's: its own token just below its master's number."""
    cole = char(db, "Cole")
    hom = {"master": cole, "k": {"id": 4, "name": "Owl", "kind": "Owl", "own_initiative": False, "initiative": "+2", "role": "Homunculus",
                                 "hp": {"current": 1, "max": 1}, "ac": 13, "turn_short": "Right after its master's turn", "turn": "", "picture": None}}
    monkeypatch.setattr(fight, "creatures_here", lambda db, campaign: [hom])
    player.post(f"/bridge/fight/{GAME}", json={"fight": heard(cole_ini=14)})
    owl = next(x for x in table.fight["order"] if x["key"] == "t-owl")
    assert owl["initiative"] == 13.5 and owl["pending"]
