"""Swap a Wild Shape form (app/form_swap.py; roadmap step 5, Brett's pick 1, Nov 13): one known form let go of and one
learned, through the bridge with D&D Beyond's own requests for a known form (a creature in group 13, recorded on Levi's
test seat, Nov 14), the rule said and never enforced, and Undo putting both back."""

from sqlalchemy import select

from app import characters, ddb_bridge, ddb_fields, form_swap
from app.models import BridgeIntent
from tests.roles import set_role
from tests.table_setup import char

SPIDER, POLAR_BEAR = "4775844", "5195167"  # (two of Cole's six known forms, by D&D Beyond's monster id)
DIRE_WOLF = form_swap._ids()["dire-wolf"]


def url(db):
    return f"/characters/{char(db, 'Cole').id}/wild-shape/forms"


def sets(db):
    return [(i.data["field"], i.data["value"]) for i in db.scalars(select(BridgeIntent).order_by(BridgeIntent.id))]


def test_the_window_lists_the_forms_you_know_and_the_ones_you_could_learn(player, db, sheet):
    page = player.get(url(db)).text
    assert "you know 6 of 6 forms" in page and "After a Long Rest" in page
    assert f'name="out" value="{SPIDER}"' in page and f'name="out" value="{POLAR_BEAR}"' in page
    assert f'<option value="{DIRE_WOLF}"' in page  # (CR 1 and no flying: Cole can learn it)
    assert f'<option value="{POLAR_BEAR}"' not in page  # (known already)
    eagle = form_swap._ids()["eagle"]
    assert f'<option value="{eagle}"' not in page  # (a Fly Speed: not until Druid 8)
    assert "data-swap-forms" in player.get(f"/characters/{char(db, 'Cole').id}").text.split('id="t-forms"')[1]  # (on Sheet › Wild Shape)


def test_a_known_form_shows_its_challenge_rating_as_the_sheet_gives_it(player, db, sheet):
    """ASKDND-V2-T (Nov 15, the live test on Levi's seat): a known form of CR 1/2 broke the window, its label read as a
    number. Each known form shows the sheet's own label."""
    for c in sheet["creatures"]:
        if str(c["definition"]["id"]) == SPIDER:
            c["definition"]["challengeRatingId"] = 4  # (D&D Beyond's id for CR 1/2)
    characters.refresh(db, char(db, "Cole"))
    r = player.get(url(db))
    assert r.status_code == 200, r.text
    spider = r.text.split(f'value="{SPIDER}"')[1].split("</label>")[0]
    assert "CR 1/2" in spider


def test_a_swap_lets_one_go_and_learns_another_and_undo_puts_both_back(player, db, sheet):
    r = player.post(url(db), data={"out": SPIDER, "in": DIRE_WOLF})
    assert r.status_code == 200, r.text
    j = r.json()
    assert "Spider let go" in j["text"] and "Dire Wolf learned" in j["text"]
    assert sets(db) == [(f"wildshape:{SPIDER}", 0), (f"wildshape:{DIRE_WOLF}", 1)]
    # what's on its way is shown at once: the Spider gone from the known forms, the Dire Wolf marked on its way
    page = player.get(url(db)).text
    assert f'name="out" value="{SPIDER}"' not in page and f'<option value="{DIRE_WOLF}" data-form="Dire Wolf" disabled' in page
    # Undo: exactly what askdnd handed back
    u = player.post(j["undoUrl"], data=j["undo"])
    assert u.status_code == 200, u.text
    assert sets(db)[2:] == [(f"wildshape:{DIRE_WOLF}", 0), (f"wildshape:{SPIDER}", 1)]
    cole = char(db, "Cole")
    assert ddb_bridge.as_shown(db, cole, characters.character_summary(cole)).get("sync", {}).get(f"wildshape:{SPIDER}") is None  # (back as it was: nothing to send)
    forged = {**j["undo"], "in": POLAR_BEAR}
    assert player.post(j["undoUrl"], data=forged).status_code == 409  # (an Undo the page changed)


def test_learning_with_a_form_free_or_letting_one_go_alone(player, db, sheet):
    assert player.post(url(db), data={"in": DIRE_WOLF}).status_code == 200
    assert player.post(url(db), data={"out": POLAR_BEAR}).status_code == 200
    assert sets(db) == [(f"wildshape:{DIRE_WOLF}", 1), (f"wildshape:{POLAR_BEAR}", 0)]


def test_what_cant_be_swapped_is_refused(player, db, sheet):
    for bad in ({}, {"out": "999"}, {"in": POLAR_BEAR}, {"in": form_swap._ids()["eagle"]}, {"out": SPIDER, "in": SPIDER}):
        assert player.post(url(db), data=bad).status_code == 409, bad
    assert sets(db) == []


def test_only_a_druid_and_its_own_player(player, dm, db, sheet, monkeypatch):
    """As Prepare spells (app/inventory.py `_guard`): the character's own player changes its sheet's choices."""
    from tests.table_setup import sign_in

    other = sign_in(monkeypatch, db, "someone@example.com")
    assert other.get(url(db)).status_code == 404 and other.post(url(db), data={"in": DIRE_WOLF}).status_code == 404
    set_role(db, "dm@example.com")
    assert dm.get(url(db)).status_code == 404
    trah = char(db, "Trah")  # (no Wild Shape)
    assert player.get(f"/characters/{trah.id}/wild-shape/forms").status_code == 404


def test_a_closed_sheet_says_so_and_changes_nothing(player, db, sheet):
    cole = char(db, "Cole")
    cole.sheet_heard_at = None
    db.commit()
    assert "can't be reached" in player.get(url(db)).text
    assert player.post(url(db), data={"in": DIRE_WOLF}).status_code == 409
    assert sets(db) == []


def test_d_and_d_beyonds_own_requests_for_a_known_form():
    """Recorded on Levi's test seat, Nov 14: learned with POST creature (group 13, the monster), let go of with DELETE
    creature (its id on the sheet); the extension checks it as the sum of the matching creatures' groups."""
    raw = {"creatures": [{"id": 7, "groupId": 13, "definition": {"id": 4775844, "name": "Spider"}},
                         {"id": 8, "groupId": 2, "definition": {"id": 4775844, "name": "Spider"}}]}
    assert ddb_fields.write(1, f"wildshape:{DIRE_WOLF}", 1, raw) == {
        "method": "POST", "path": "/character/v5/creature", "body": {"characterId": 1, "groupId": 13, "monsterId": int(DIRE_WOLF), "names": [None]}}
    assert ddb_fields.write(1, "wildshape:4775844", 0, raw) == {"method": "DELETE", "path": "/character/v5/creature", "body": {"characterId": 1, "id": 7}}
    assert ddb_fields.value(raw, "wildshape:4775844") == 1  # (the familiar Spider isn't a known form)
    read, frm, to = ddb_fields.wire("wildshape:4775844", raw, 1, 0)
    assert ddb_fields.pick(raw, read) == frm == 15 and to == 2  # (13 + 2, then the familiar's 2 alone)
    shown = {"creatures": list(raw["creatures"])}
    ddb_fields.put(shown, "wildshape:4775844", 0)
    assert [c["id"] for c in shown["creatures"]] == [8]
    assert ddb_fields.name(raw, "wildshape:4775844") == "Wild Shape form Spider" and ddb_fields.text(raw, "wildshape:1", 1) == "known"


def test_the_long_rest_window_offers_it(player, db, sheet):
    cole = char(db, "Cole")
    assert "data-swap-forms" in player.get(f"/characters/{cole.id}/rest?kind=long").text
    assert "data-swap-forms" not in player.get(f"/characters/{cole.id}/rest?kind=short").text
