"""Shifting into a Wild Shape form and leaving it (app/shifting.py; Brett, 2026-11-03, docs/mockups/wild-shape-play/):
the form is askdnd's, and what D&D Beyond keeps goes through the bridge: one Wild Shape use and the Temporary Hit Points.
Undo puts back all of it."""

import html

from sqlalchemy import select

from app import characters
from app.models import BridgeIntent
from tests.table_setup import char

USE = "uses:9414013"  # Cole's Wild Shape (the fixture's sheet)


def intents(db):
    return list(db.scalars(select(BridgeIntent).order_by(BridgeIntent.id)))


def test_shifting_spends_a_use_and_gives_the_temporary_hit_points(player, db, sheet):
    cole = char(db, "Cole")
    w = player.get(f"/characters/{cole.id}/wild-shape?form=Polar Bear").text
    assert "3 left → 2, on D&amp;D Beyond" in w and "can't be reached" not in w
    r = player.post(f"/characters/{cole.id}/wild-shape", data={"form": "Polar Bear", "to": "shift"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["text"] == "Cole is a Polar Bear: 1 Wild Shape use spent, 18 Temporary Hit Points"
    use, temp = intents(db)
    assert (use.kind, use.data["field"], use.data["delta"]) == ("use", USE, 1)
    assert (temp.kind, temp.data["value"]) == ("temp", 18)
    assert j["undo"] == {"to": "undo", "was": "", "spent": "1", "temp_was": "0"}
    db.refresh(cole)
    assert cole.wild_shape == "Polar Bear"
    player.post(f"/characters/{cole.id}/wild-shape", data=j["undo"])  # Undo: the form, the use and the Temporary HP back
    db.refresh(cole)
    back = intents(db)[2:]
    assert cole.wild_shape is None and [(i.kind, i.data.get("delta"), i.data.get("value")) for i in back] == [("use", -1, None), ("temp", None, 0)]


def test_temporary_hit_points_dont_add_up_so_you_can_keep_yours(player, db, sheet):
    """They don't add up (the 2024 rules): the window offers to keep the ones you have, and keeping them changes none."""
    cole = char(db, "Cole")
    sheet["temporaryHitPoints"] = 25
    characters.refresh(db, cole)  # (askdnd reads the sheet again)
    w = player.get(f"/characters/{cole.id}/wild-shape?form=Polar Bear").text
    assert 'value="keep" selected' in w and "You have 25" in w
    r = player.post(f"/characters/{cole.id}/wild-shape", data={"form": "Polar Bear", "to": "shift", "temp": "keep"})
    assert "kept 25 Temporary Hit Points" in r.json()["text"]
    assert [i.kind for i in intents(db)] == ["use"]


def test_leaving_is_a_bonus_action_and_your_temporary_hit_points_stay(player, db, sheet):
    cole = char(db, "Cole")
    cole.wild_shape = "Polar Bear"
    db.flush()
    w = player.get(f"/characters/{cole.id}/wild-shape").text
    assert "Leave the Polar Bear form" in w and "Bonus Action" in w and "nothing changes on D&amp;D Beyond" in w
    player.post(f"/characters/{cole.id}/wild-shape", data={"to": "leave"})
    db.refresh(cole)
    assert cole.wild_shape is None and intents(db) == []


def test_no_uses_left_and_no_sheet_to_reach(player, db, sheet):
    """No uses left: the window says when they come back and Shift is refused. A sheet that can't be reached: the form
    still changes in askdnd, and the card says to mark the use and the Temporary Hit Points on D&D Beyond."""
    cole = char(db, "Cole")
    cole.sheet_heard_at = None  # its sheet is closed
    db.flush()
    w = player.get(f"/characters/{cole.id}/wild-shape?form=Polar Bear").text
    assert "can't be reached: Shift changes the form in askdnd" in w
    r = player.post(f"/characters/{cole.id}/wild-shape", data={"form": "Polar Bear", "to": "shift"})
    assert "mark 1 Wild Shape use and 18 Temporary Hit Points on D&D Beyond" in r.json()["text"] and intents(db) == []
    db.refresh(cole)
    assert cole.wild_shape == "Polar Bear"


def test_everyone_sees_the_form_and_rolls_keep_it(player, dm, db, sheet):
    """Brett, Nov 3 (docs/mockups/wild-shape-play/ Elsewhere): Party, the fight's rows and band say "Cole (Polar Bear)"
    with the bear's picture and AC; a roll keeps the form it was made in, so later ones don't rename earlier ones."""
    from datetime import UTC, datetime

    from app.models import Campaign
    from tests.roles import set_role

    cole = char(db, "Cole")
    set_role(db, "dm@example.com", "dm")
    set_role(db, "player@example.com", "player")
    campaign = db.get(Campaign, cole.campaign_id)
    before = player.post("/rolls", data={"character": cole.id, "kind": "check", "label": "Perception", "mod": "+8", "mode": "normal", "to": "table"}).json()
    player.post(f"/characters/{cole.id}/wild-shape", data={"form": "Polar Bear", "to": "shift"})
    campaign.fight = {"id": "f1", "round": 1, "turn": 1, "reminders": [], "order": [
        {"key": "c", "name": "Cole", "kind": "character", "character": cole.id, "monster": None, "initiative": 17, "hidden": False,
         "active": True, "image": None}]}
    campaign.fight_at = datetime.now(UTC)
    db.flush()
    party = dm.get("/party").text
    assert '<span class="tag pt-form" title="In Wild Shape">Polar Bear</span>' in party
    assert '<span class="tag ft-form" title="In Wild Shape">Polar Bear</span>' in party and "<small>(Polar Bear)</small>" in party
    assert 'class="nt in-form"' in party  # the bear's AC and Speed
    after = player.post("/rolls", data={"character": cole.id, "kind": "check", "label": "Perception", "mod": "+8", "mode": "normal", "to": "table"}).json()
    log = player.get("/rolls").text
    assert log.count("Cole (Polar Bear)") >= 1 and after["roll"]["id"] != before["roll"]["id"]
    from app.models import TableRoll

    assert db.get(TableRoll, before["roll"]["id"]).who == "" and db.get(TableRoll, after["roll"]["id"]).who == "Polar Bear"


def test_sheet_in_a_form_says_so_and_greys_what_the_form_cant_do(player, db, sheet):
    """Brett, Nov 3 (Sheet warns, never hides): a band, a spell the form can't cast and a species trait greyed with the
    reason, an item's note that the DM decides; Cast says so for that spell and still offers it."""
    cole = char(db, "Cole")
    player.post(f"/characters/{cole.id}/wild-shape", data={"form": "Polar Bear", "to": "shift"})
    page = player.get(f"/characters/{cole.id}").text
    assert "In Wild Shape: Polar Bear." in page and 'class="ri form-no"' in page
    assert "Not in this form: only Circle of the Moon spells" in page
    assert "Not in this form: a Wild Shape form replaces your species traits" in page
    assert "In a form: the DM decides whether you can use it" in page
    w = html.unescape(player.get(f"/characters/{cole.id}/cast?key=spell:Healing Word").text)
    assert "can cast only Circle of the Moon spells: Healing Word isn't one. The DM rules." in w and "data-use-go" in w
    assert "Circle of the Moon spells" not in player.get(f"/characters/{cole.id}/cast?key=spell:Moonbeam").text


def test_battle_shows_the_forms_numbers(player, db, sheet):
    """Battle's top row is the form's (Circle Forms' AC, its speeds); its other speeds are a note, not markup (Nov 3: the
    bear's swim speed showed as "<span class=…>")."""
    cole = char(db, "Cole")
    player.post(f"/characters/{cole.id}/wild-shape", data={"form": "Polar Bear", "to": "shift"})
    page = player.get(f"/characters/{cole.id}/battle").text
    assert 'class="nt in-form"' in page and '<span class="note ph-hide">swim' in page and "&lt;span" not in page


def test_the_window_posts_to_its_own_address(player, db, sheet):
    """As app.js does (useItem): the window's Shift posts to the address it was opened from, with only `to` and what
    it shows (Nov 3: the form was read from the body only, so the real window answered Not found)."""
    cole = char(db, "Cole")
    r = player.post(f"/characters/{cole.id}/wild-shape?form=Polar%20Bear", data={"to": "shift", "temp": "take"})
    assert r.status_code == 200, r.text
    db.refresh(cole)
    assert cole.wild_shape == "Polar Bear"
