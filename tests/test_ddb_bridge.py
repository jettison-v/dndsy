"""The D&D Beyond bridge, a local proof (app/ddb_bridge.py): middleware that repairs itself. D&D Beyond is never called:
a fake sheet stands in, and each test changes it the way the extension, a player or a misbehaving D&D Beyond would."""

import copy
import json
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import characters, config, ddb, ddb_bridge, ddb_fields, ddb_sheet
from app.importer import import_bundle
from app.models import BridgeIntent, Campaign, Character
from tests.roles import set_role
from tests.table_setup import BUNDLE, COLE, char, owned_by

POTION = 758022089  # Cole's Potion of Healing (×2 in the fixture)


def make(data, batch):
    """What the extension's requests do to the sheet: each field ends at its new value."""
    for op in batch["ops"]:
        put(data, op["field"], op["to"])


def put(data, field, v):
    """A field set on the fake sheet, as D&D Beyond keeps it."""
    kind, _, arg = field.partition(":")
    row = next((i for i in data["inventory"] if str(i["id"]) == arg), None)
    if kind == "hp":
        data.update(v)
    elif kind == "death":
        data["deathSaves"].update(v)
    elif kind == "inspiration":
        data["inspiration"] = v
    elif kind in ("exhaustion", "condition"):
        cid = 4 if kind == "exhaustion" else int(arg)
        data["conditions"] = [c for c in data["conditions"] if c["id"] != cid] + ([{"id": cid, "level": v if kind == "exhaustion" else None}] if v else [])
    elif kind == "hitdice":
        next(c for c in data["classes"] if str(c["id"]) == arg)["hitDiceUsed"] = v
    elif kind in ("slot", "pact"):
        next(x for x in data["spellSlots" if kind == "slot" else "pactMagic"] if str(x["level"]) == arg)["used"] = v
    elif kind == "uses":
        next(a for group in data["actions"].values() for a in group or [] if str(a["id"]) == arg)["limitedUse"]["numberUsed"] = v
    elif kind == "item" and v is None:
        data["inventory"].remove(row)
    elif kind in ("item", "equipped", "attuned", "container"):
        row[{"item": "quantity", "attuned": "isAttuned", "container": "containerEntityId"}.get(kind, kind)] = v
    elif kind == "charges":
        row["limitedUse"]["numberUsed"] = v
    elif kind == "coin":
        data["currencies"][arg] = v
    elif kind == "bagcoin":  # (a container's own coins, as D&D Beyond keeps them)
        ddb_fields.put(data, field, v)
    elif kind == "add":
        like = next(i for i in data["inventory"] if str(i["definition"]["id"]) == arg)
        have = sum(i["quantity"] for i in data["inventory"] if i["definition"] is like["definition"])
        data["inventory"].append({**copy.deepcopy(like), "id": 999000 + len(data["inventory"]), "quantity": v - have})


def potions(data):
    return next(i for i in data["inventory"] if i["id"] == POTION)["quantity"]


def drink(db, cole, heal=8):
    return ddb_bridge.add(db, cole, "drink", {"item": POTION, "name": "Potion of Healing", "heal": heal}, "Cole drank a Potion of Healing")


def test_a_change_counts_only_once_d_and_d_beyond_has_it(player, db, sheet):
    """A standing rule (Brett, 2026-10-27: no partial sync; correct in both places or the difference shown): askdnd
    shows a change as made only after reading it back from D&D Beyond."""
    cole = char(db, "Cole")
    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)
    assert [op["body"] for op in batch["ops"]] == [{"characterId": 75423618, "removedHitPoints": 6, "temporaryHitPoints": 0},
                                                   {"characterId": 75423618, "id": POTION, "quantity": 1}]
    assert player.get(f"/bridge/state/{cole.id}").json()["hp"]["current"] == 37  # nothing changes in askdnd yet
    assert ddb_bridge.outbox(db, cole) is None  # one batch at a time

    make(sheet, batch)
    ddb_bridge.delivered(db, batch["id"], ok=True)
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["hp"]["current"] == 45 and st["items"][0]["quantity"] == 1 and st["changes"] == []
    assert st["log"][0] == {**st["log"][0], "state": "live", "text": "Cole drank a Potion of Healing"}


def test_only_a_browser_the_change_went_to_settles_it(player, db, sheet, monkeypatch):
    """The outside review's C3 (Nov 10): another player at the table can't mark Cole's change made or failed; his own
    player can."""
    from tests.table_setup import sign_in

    cole = char(db, "Cole")
    owned_by(db, char(db, "Trah"), "other@example.com")
    set_role(db, "other@example.com", "player", campaign=db.get(Campaign, cole.campaign_id))
    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)
    other = sign_in(monkeypatch, db, "other@example.com")
    assert other.post(f"/bridge/delivered/{batch['id']}", json={"ok": False, "error": "no"}).status_code == 404
    assert {i.state for i in db.scalars(select(BridgeIntent).where(BridgeIntent.character_id == cole.id))} == {"sending"}
    make(sheet, batch)
    assert player.post(f"/bridge/delivered/{batch['id']}", json={"ok": True}).status_code == 200


def test_a_change_is_built_on_what_d_and_d_beyond_has_when_it_goes(db, sheet, monkeypatch):
    """An intent, not a number: hit points changed on D&D Beyond after the drink was asked for are built on, not lost.
    askdnd's copy of the sheet is read again first when it's more than a minute old (ddb_bridge.COPY_SECONDS)."""
    cole = char(db, "Cole")
    drink(db, cole, heal=4)
    sheet["removedHitPoints"] = 20  # the player took 6 more on D&D Beyond meanwhile
    later = ddb_bridge.time.time() + ddb_bridge.COPY_SECONDS + 1
    monkeypatch.setattr(ddb_bridge.time, "time", lambda: later)
    batch = ddb_bridge.outbox(db, cole)
    assert batch["ops"][0]["body"]["removedHitPoints"] == 16 and batch["ops"][0]["from"]["removedHitPoints"] == 20


def test_a_recent_copy_of_the_sheet_is_built_on_without_reading_it_first(db, sheet, monkeypatch):
    """Brett, 2026-10-29 (a second faster): a batch builds on askdnd's copy when it's under a minute old; what the
    extension's check right before writing doesn't cover is read fresh first: a hit down to 0 (from maximum hit points)."""
    reads, read = [], characters.read_released
    monkeypatch.setattr(characters, "read_released", lambda db, ch, *a, **k: reads.append(ch.id) or read(db, ch, *a, **k))
    cole = char(db, "Cole")
    ddb_bridge.add(db, cole, "hp", {"amount": -5}, "Cole took 5")
    batch = ddb_bridge.outbox(db, cole)
    assert reads == [] and batch["ops"][0]["body"]["removedHitPoints"] == 19  # 14 + 5, from the copy
    make(sheet, batch)
    ddb_bridge.delivered(db, batch["id"], ok=True)
    reads.clear()
    ddb_bridge.add(db, cole, "hp", {"amount": -80}, "Cole took 80")
    batch = ddb_bridge.outbox(db, cole)
    assert len(reads) == 1 and batch["ops"][0]["body"]["removedHitPoints"] == 51  # down to 0: read fresh first


def test_a_change_the_copy_says_is_made_already_is_read_fresh_first(db, sheet, monkeypatch):
    """The live test, Nov 2: healing from 0 clears the death save marks, but askdnd's copy (under a minute old) didn't
    have the mark D&D Beyond had just kept, so clearing looked made already, wasn't sent, and the extension's check
    (only what's written) couldn't notice. A field left out because the copy has it already is read fresh first."""
    reads, read = [], characters.read_released
    monkeypatch.setattr(characters, "read_released", lambda db, ch, *a, **k: reads.append(ch.id) or read(db, ch, *a, **k))
    cole = char(db, "Cole")
    sheet["deathSaves"].update(failCount=1)  # on D&D Beyond, not yet in askdnd's copy
    ddb_bridge.add(db, cole, "set", {"field": "death", "value": {"successCount": 0, "failCount": 0}}, "Cole: death saves cleared")
    batch = ddb_bridge.outbox(db, cole)
    assert reads == [cole.id] and [op["field"] for op in batch["ops"]] == ["death"]
    assert batch["ops"][0]["to"] == {"successCount": 0, "failCount": 0}


def test_several_changes_go_as_one_end_state(player, db, sheet):
    """Brett, 2026-10-27: not 12 → 10 → 15 → 45 → 34, just the end state."""
    cole = char(db, "Cole")
    for amount in (-2, 5, -10):
        ddb_bridge.add(db, cole, "hp", {"amount": amount}, f"Cole {amount}")
    batch = ddb_bridge.outbox(db, cole)
    assert len(batch["ops"]) == 1 and batch["ops"][0]["body"]["removedHitPoints"] == 21  # 14 + 2 - 5 + 10


def test_an_extension_too_old_for_a_change_says_so_at_once(player, db, sheet):
    """Nov 3 (Brett preparing a spell from a Chrome still on extension 0.9.5): an extension refuses a request it doesn't
    know. Trying again can't help, and it isn't one to make by hand: askdnd stops at once and says to update it."""
    cole = char(db, "Cole")
    ddb_bridge.add(db, cole, "hp", {"amount": -1}, "Cole took 1")
    batch = ddb_bridge.outbox(db, cole)
    ddb_bridge.delivered(db, batch["id"], ok=False, error="That isn't a change askdnd may make.")
    it = db.scalar(select(BridgeIntent))
    assert it.state == "not_yet" and "older than this change needs" in it.error and "Update it" in it.error
    assert ddb_bridge.outbox(db, cole) is None  # not sent again on its own


def test_a_dropped_write_is_sent_again_on_its_own(player, db, sheet, monkeypatch):
    """D&D Beyond can answer OK and not keep a write (DDB Importer's experience): askdnd notices on read-back and sends
    the batch again, and after MAX_ATTEMPTS it stops and lists the end state to make by hand."""
    monkeypatch.setattr(ddb_bridge, "RETRY_SECONDS", (0, 0, 0))
    cole = char(db, "Cole")
    drink(db, cole)
    first = ddb_bridge.outbox(db, cole)
    ddb_bridge.delivered(db, first["id"], ok=True)  # D&D Beyond said OK but kept nothing
    again = ddb_bridge.outbox(db, cole)
    assert again["id"] == first["id"] and again["ops"] == first["ops"]  # the same totals, not a second drink
    make(sheet, again)
    ddb_bridge.delivered(db, again["id"], ok=True)
    assert player.get(f"/bridge/state/{cole.id}").json()["hp"]["current"] == 45

    ddb_bridge.add(db, cole, "hp", {"amount": -3}, "Cole took 3")
    batch = ddb_bridge.outbox(db, cole)
    for _ in range(ddb_bridge.MAX_ATTEMPTS):
        ddb_bridge.delivered(db, batch["id"], ok=True)  # dropped every time
        batch = ddb_bridge.outbox(db, cole) or batch
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "not_yet" and "(3 tries)" in st["changes"][0]["error"]
    assert st["to_make"] == ["Hit points 42 (D&D Beyond has 45)"]


def test_a_change_d_and_d_beyond_was_slow_to_show_is_offered_again_at_once(player, db, sheet):
    """Oct 30, the live test: D&D Beyond showed a Short Rest's Hit Point Die after the read-back gave up, and the batch
    waited 5 seconds and then the extension's next check, over 30 in all. The first retry is offered at once; the
    extension finds D&D Beyond has it now, writes nothing again, and the read-back settles it."""
    cole = char(db, "Cole")
    cls = sheet["classes"][0]["id"]
    ddb_bridge.add(db, cole, "short_rest", {"spend": {str(cls): 1}}, "Cole: Hit Point Dice spent")
    batch = ddb_bridge.outbox(db, cole)
    ddb_bridge.delivered(db, batch["id"], ok=True)  # written, but not shown yet
    again = ddb_bridge.outbox(db, cole)
    assert again and again["id"] == batch["id"]  # at once, not in 5 seconds
    make(sheet, again)  # (D&D Beyond shows it now: the extension's check finds it there)
    ddb_bridge.delivered(db, again["id"], ok=True)
    assert ddb_bridge.outbox(db, cole) is None
    assert player.get(f"/bridge/state/{cole.id}").json()["log"][0]["state"] == "live"


def test_a_value_askdnd_cant_explain_is_never_written_over(player, db, sheet):
    cole = char(db, "Cole")
    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)
    make(sheet, batch)
    sheet["removedHitPoints"] = 30  # someone else changed it right after askdnd wrote
    ddb_bridge.delivered(db, batch["id"], ok=True)
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "not_yet" and "Nothing on the sheet changed" in st["changes"][0]["error"]
    assert ddb_bridge.outbox(db, cole) is None  # and nothing more is sent


def test_a_change_on_d_and_d_beyond_in_the_moment_before_writing_is_worked_out_again(db, sheet):
    """The extension checks each total against D&D Beyond just before writing; on a mismatch it writes nothing and
    askdnd builds the batch again from the new numbers."""
    cole = char(db, "Cole")
    drink(db, cole, heal=4)
    first = ddb_bridge.outbox(db, cole)
    sheet["removedHitPoints"] = 18
    ddb_bridge.delivered(db, first["id"], ok=False, conflicts=["hp"])
    second = ddb_bridge.outbox(db, cole)  # (askdnd read the sheet again on the mismatch: not built on the old copy)
    assert second["id"] != first["id"] and second["ops"][0]["body"]["removedHitPoints"] == 14  # 18 - 4


def test_a_sheet_that_cant_be_reached_is_tried_again_later(db, sheet, monkeypatch):
    cole = char(db, "Cole")
    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)
    ddb_bridge.delivered(db, batch["id"], ok=False, error="D&D Beyond answered 503.")
    assert ddb_bridge.outbox(db, cole) is None  # it waits a moment first
    later = ddb_bridge.time.time() + 60
    monkeypatch.setattr(ddb_bridge.time, "time", lambda: later)
    assert ddb_bridge.outbox(db, cole)["id"] == batch["id"]


def test_a_batch_the_extension_never_answered_for_is_offered_again(db, sheet, monkeypatch):
    cole = char(db, "Cole")
    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)
    monkeypatch.setattr(ddb_bridge, "SENDING_SECONDS", -1)
    assert ddb_bridge.outbox(db, cole)["id"] == batch["id"]  # the extension skips a field already at its new value


def test_a_change_that_cant_happen_any_more_says_why(player, db, sheet):
    cole = char(db, "Cole")
    next(i for i in sheet["inventory"] if i["id"] == POTION)["quantity"] = 0  # drunk on D&D Beyond: askdnd's copy still has two
    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)  # built on the copy; the extension finds D&D Beyond changed and writes nothing
    ddb_bridge.delivered(db, batch["id"], ok=False, conflicts=[f"item:{POTION}"])
    assert ddb_bridge.outbox(db, cole) is None
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "not_yet" and "No Potion of Healing left" in st["changes"][0]["error"]


def test_changes_made_on_d_and_d_beyond_itself_are_logged(player, db, sheet):
    cole = char(db, "Cole")
    player.get(f"/bridge/state/{cole.id}")  # askdnd has seen 37 and two potions
    sheet["removedHitPoints"], sheet["temporaryHitPoints"] = 20, 0
    next(i for i in sheet["inventory"] if i["id"] == POTION)["quantity"] = 3
    st = player.post("/bridge/heard/75423618").json()
    assert st["hp"]["current"] == 31
    assert st["log"][0]["state"] == "seen" and st["log"][0]["text"] == "Cole (on D&D Beyond): hit points 37 → 31, Potion of Healing ×2 → ×3"


def test_a_save_the_bridge_hears_tells_the_pages_showing_that_character(player, db, sheet, monkeypatch):
    """Pages showing the character update themselves (app.js "live connection"); nothing is sent
    when the sheet saved without changing anything askdnd shows."""
    from app import realtime

    cole = char(db, "Cole")
    player.get(f"/bridge/state/{cole.id}")
    sent = []
    monkeypatch.setattr(realtime, "publish", lambda campaign_id, kind, **data: sent.append((campaign_id, kind, data)))
    player.post("/bridge/heard/75423618")
    assert sent == []
    sheet["removedHitPoints"] = 20
    player.post("/bridge/heard/75423618")
    assert sent == [(cole.campaign_id, "character", {"id": cole.id})]


def test_a_change_on_d_and_d_beyond_is_logged_whichever_read_sees_it_first(player, db, sheet):
    """The party's refresh (or a page opening) can read D&D Beyond before the bridge does: the change is still logged
    as made on D&D Beyond, once, and what askdnd is writing never is."""
    cole = char(db, "Cole")
    sheet["temporaryHitPoints"] = 5
    characters.refresh(db, cole)  # the party's refresh, not the bridge
    player.post("/bridge/heard/75423618")  # the bridge reads it again: nothing new
    log = player.get(f"/bridge/state/{cole.id}").json()["log"]
    assert [entry["text"] for entry in log if entry["state"] == "seen"] == ["Cole (on D&D Beyond): temporary hit points 0 → 5"]

    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)
    make(sheet, batch)
    characters.refresh(db, cole)  # the party's refresh sees askdnd's own write first
    ddb_bridge.delivered(db, batch["id"], ok=True)
    log = player.get(f"/bridge/state/{cole.id}").json()["log"]
    assert [entry["state"] for entry in log] == ["live", "seen"]


def test_askdnd_and_the_extension_read_a_field_the_same_way():
    """The extension follows the same steps (ddb-page.js `pick`): a value D&D Beyond leaves out reads as its stand-in,
    a missing item as None."""
    data = {"removedHitPoints": 3, "inventory": [{"id": 7, "quantity": 2}]}
    assert ddb_fields.value(data, "hp") == {"removedHitPoints": 3, "temporaryHitPoints": 0}
    assert ddb_fields.value(data, "item:7") == 2 and ddb_fields.value(data, "item:8") is None


def test_the_round_trip_check_and_the_status(player, db, sheet, monkeypatch):
    """The pre-game check takes 1 hit point and one item out and puts them back, each confirmed by read-back."""
    monkeypatch.setattr(ddb_bridge, "TEST_DDB_ID", "75423618")  # Cole stands in for the test character
    monkeypatch.setattr(ddb_bridge, "TEST_ITEM", "Potion of Healing")
    monkeypatch.setattr(ddb, "fetch_character_json", lambda _id, timeout=None: copy.deepcopy(sheet))
    cole = char(db, "Cole")
    assert player.get("/bridge/health").json()["text"] == "D&D Beyond · extension not connected"
    player.post("/bridge/hello", json={"sheets": ["75423618"]})
    assert player.post("/bridge/check").json()["text"] == "D&D Beyond · checking…"
    out = ddb_bridge.outbox(db, cole)
    make(sheet, out)
    ddb_bridge.delivered(db, out["id"], ok=True)
    back = ddb_bridge.outbox(db, cole)
    assert {op["field"]: op["body"] for op in back["ops"]}["hp"]["removedHitPoints"] == 14
    make(sheet, back)
    ddb_bridge.delivered(db, back["id"], ok=True)
    assert sheet["removedHitPoints"] == 14 and potions(sheet) == 2  # as it was
    assert player.get("/bridge/health").json()["text"] == "D&D Beyond · working"


def test_a_failed_read_shows_as_a_problem(player, db, sheet, monkeypatch):
    def gone(_id, timeout=None):
        raise ddb.DdbError("D&D Beyond says this character is private.")
    monkeypatch.setattr(ddb, "fetch_character_json", gone)
    assert player.get("/bridge/health").json() == {**player.get("/bridge/health").json(), "state": "off"}


def test_the_extension_signs_in_with_its_own_key(player, db, sheet):
    """A browser that blocks third-party cookies sends the extension none, so it uses a key from a signed-in page."""
    from fastapi.testclient import TestClient

    from app.main import app

    key = player.post("/bridge/connect").json()["key"]
    assert player.post("/bridge/connect").json()["key"] != key  # a new one each time (only a hash is kept)
    stranger = TestClient(app)
    assert stranger.get("/bridge/by-ddb/75423618").status_code == 401
    got = stranger.get("/bridge/by-ddb/75423618", headers={"X-Askdnd-Bridge": key}).json()
    assert got["character"]["name"] == "Cole" and got["can_act"] is True


def test_only_the_player_changes_and_only_where_switched_on(player, dm, db, sheet, monkeypatch):
    cole = char(db, "Cole")
    assert dm.post("/bridge/outbox/75423618").json() == {"batch": None}  # only the player's own browser writes the sheet
    assert player.get(f"/characters/{cole.id}/bridge", follow_redirects=False).headers["location"] == f"/characters/{cole.id}/battle?live=1"
    db.get(Campaign, cole.campaign_id).vtt_pieces = []  # its campaign switched it off (Manage › Settings)
    db.flush()
    assert player.get(f"/bridge/state/{cole.id}").status_code == 404 and player.post("/bridge/heard/75423618").status_code == 404
    assert "data-bridge-health" not in player.get(f"/characters/{cole.id}").text  # no pill in that campaign
    db.get(Campaign, cole.campaign_id).vtt_pieces = ["ddb_bridge"]
    db.flush()
    monkeypatch.setattr(config, "DDB_BRIDGE", False)  # off unless DDB_BRIDGE=1 (app/config.py)
    assert player.get(f"/bridge/state/{cole.id}").status_code == 404
    assert player.get(f"/characters/{cole.id}/bridge").status_code == 404


def test_a_test_copy_never_reaches_d_and_d_beyond(admin, db, sheet):
    """A standing rule (Brett, 2026-10-27: test only on Vi, never a table character's real sheet): a test copy shares
    the real character's D&D Beyond sheet, so the bridge never works on one, even in a campaign with Sync on."""
    cole = char(db, "Cole")
    test = Campaign(slug="vtt-test", name="VTT test", is_test=True, vtt_pieces=["sync"])
    db.add(test)
    db.flush()
    copy_ = characters.test_copy(db, cole, test.id)
    db.flush()
    assert ddb_bridge.on_for(db, cole) and not ddb_bridge.on_for(db, copy_)
    assert admin.post(f"/bridge/hp/{copy_.id}", data={"amount": -1}).status_code == 404
    assert db.scalar(select(BridgeIntent.id)) is None


def test_a_pull_of_d_and_d_beyond_settles_a_change_even_if_the_extension_never_said_so(player, db, sheet):
    """Redundant: the extension's every-30-seconds pull confirms a change whose "done" never reached askdnd."""
    cole = char(db, "Cole")
    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)
    make(sheet, batch)  # made on D&D Beyond, but the answer was lost
    st = player.post("/bridge/heard/75423618?pull=1").json()
    assert st["changes"] == [] and st["log"][0]["state"] == "live" and st["hp"]["current"] == 45


def restart():
    """What a restart forgets: only the extension's heartbeat (everything else is in the database)."""
    ddb_bridge._health.update(extension_at=0.0, sheets=[], heard_at=0.0, read_check=None, round_trip=None)


def test_a_waiting_change_survives_a_restart(db, sheet):
    cole = char(db, "Cole")
    drink(db, cole)
    restart()
    assert ddb_bridge.outbox(db, cole)["ops"][1]["body"]["quantity"] == 1


def test_a_check_cut_short_by_a_restart_still_puts_everything_back(player, db, sheet, monkeypatch):
    monkeypatch.setattr(ddb_bridge, "TEST_DDB_ID", "75423618")
    monkeypatch.setattr(ddb_bridge, "TEST_ITEM", "Potion of Healing")
    cole = char(db, "Cole")
    ddb_bridge.round_trip(db, cole)
    out = ddb_bridge.outbox(db, cole)
    make(sheet, out)
    ddb_bridge.delivered(db, out["id"], ok=True)
    restart()
    back = ddb_bridge.outbox(db, cole)
    make(sheet, back)
    ddb_bridge.delivered(db, back["id"], ok=True)
    assert sheet["removedHitPoints"] == 14 and potions(sheet) == 2


def test_two_of_the_same_drink_are_two_drinks(db, sheet):
    cole = char(db, "Cole")
    drink(db, cole, heal=3)
    drink(db, cole, heal=3)
    ops = {op["field"]: op["body"] for op in ddb_bridge.outbox(db, cole)["ops"]}
    assert ops[f"item:{POTION}"]["quantity"] == 0 and ops["hp"]["removedHitPoints"] == 8


def test_a_sheet_that_keeps_changing_under_askdnd_stops_instead_of_looping(player, db, sheet):
    cole = char(db, "Cole")
    drink(db, cole)
    for _ in range(ddb_bridge.MAX_ATTEMPTS + 1):
        batch = ddb_bridge.outbox(db, cole)
        if not batch:
            break
        ddb_bridge.delivered(db, batch["id"], ok=False, conflicts=["hp"])
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "not_yet" and st["to_make"]



def test_a_change_that_only_counts_with_the_others_isnt_marked_made_when_they_stop(player, db, sheet):
    """At full hit points a heal alone changes nothing, but after damage in the same batch it does: when D&D Beyond
    ends up with other hit points, the heal waits with the damage instead of counting as made."""
    sheet["removedHitPoints"] = 0
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    for ask in ({"amount": -10}, {"amount": 5}):
        player.post(f"/bridge/hp/{cole.id}", data=ask)
    player.post(f"/bridge/change/{cole.id}", json={"kind": "use", "field": "coin:gp", "delta": 1})
    batch = ddb_bridge.outbox(db, cole)
    make(sheet, batch)
    sheet["removedHitPoints"] = 7  # neither what askdnd wrote nor what it had
    ddb_bridge.delivered(db, batch["id"], ok=True)
    states = {c["label"]: c["state"] for c in player.get(f"/bridge/state/{cole.id}").json()["changes"]}
    assert [s for label, s in states.items() if "gold" not in label] == ["not_yet", "not_yet"], states

def asleep(db):
    """No one has used askdnd or a sheet for a long time."""
    row, _ = ddb_bridge._wake_row(db)
    row.value = '{"last": 0}'


def counting_reads(monkeypatch, sheet):
    reads = []
    monkeypatch.setattr(characters, "FETCH", lambda _id: reads.append(_id) or copy.deepcopy(sheet))
    monkeypatch.setattr(ddb, "fetch_character_json", lambda _id, timeout=None: reads.append(_id) or copy.deepcopy(sheet))
    return reads


def test_asleep_it_reads_nothing_in_the_background_but_a_save_is_always_recorded(player, db, sheet, monkeypatch):
    """Brett, 2026-10-27: no wasting D&D Beyond's resources when no one is playing, but always active when it needs to
    be. Asleep, the background pull and the hourly check read nothing; a player's save on D&D Beyond is still read,
    recorded, and wakes it."""
    reads = counting_reads(monkeypatch, sheet)
    cole = char(db, "Cole")
    asleep(db)
    player.post("/bridge/heard/75423618?pull=1")
    health = player.get("/bridge/health").json()
    assert reads == [] and health["state"] == "asleep" and health["text"] == "D&D Beyond bridge · asleep"
    assert ddb_bridge.outbox(db, cole) is None

    sheet["removedHitPoints"] = 20  # someone took 6 on D&D Beyond, with no askdnd page open
    player.post("/bridge/heard/75423618")
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert reads and st["hp"]["current"] == 31 and "hit points 37 → 31" in st["log"][0]["text"]
    assert ddb_bridge.awake(db)["awake"]


def test_opening_or_using_askdnd_or_a_sheet_keeps_it_awake_half_an_hour(player, db, sheet, monkeypatch):
    now = [ddb_bridge.time.time()]
    monkeypatch.setattr(ddb_bridge.time, "time", lambda: now[0])
    asleep(db)
    player.post("/bridge/active", json={})  # an askdnd page opened, or someone clicked on one
    assert ddb_bridge.awake(db)["awake"]
    now[0] += ddb_bridge.timers(db)["idle"] - 60
    player.post("/bridge/active", json={"sheet": "75423618"})  # a D&D Beyond sheet opened, or someone used it
    now[0] += ddb_bridge.timers(db)["idle"] - 60
    assert ddb_bridge.awake(db)["awake"]
    now[0] += 120
    assert not ddb_bridge.awake(db)["awake"] and "30 minutes" in ddb_bridge.awake(db)["why"]
    player.post("/bridge/heard/75423618?pull=1")  # (Cole's sheet is open: asleep, the pull reads nothing)
    assert not ddb_bridge.awake(db)["awake"]
    assert player.post(f"/bridge/hp/{char(db, 'Cole').id}", data={"amount": -1}).status_code == 200  # making a change wakes it too
    assert ddb_bridge.awake(db)["awake"]


def test_a_character_page_shows_what_d_and_d_beyond_has_now(player, db, sheet, monkeypatch):
    """Planning in askdnd never starts from an old number: opening a character's page (or their D&D Beyond sheet)
    reads D&D Beyond when askdnd's copy is older than the party's refresh, and not otherwise."""
    from datetime import UTC, datetime, timedelta
    reads = counting_reads(monkeypatch, sheet)
    cole = char(db, "Cole")
    player.get(f"/characters/{cole.id}")
    assert reads == []  # read a moment ago
    sheet["removedHitPoints"] = 20
    cole.snapshot.attempted_at -= timedelta(minutes=3)
    db.commit()
    player.get(f"/characters/{cole.id}")
    assert len(reads) == 1 and ddb_bridge.numbers(char(db, "Cole"))["removed"] == 20
    cole = char(db, "Cole")
    cole.snapshot.attempted_at -= timedelta(minutes=3)
    db.commit()
    player.post("/bridge/active", json={"sheet": "75423618"})
    assert reads.count("75423618") == 2  # (besides the hourly check of the test character)


def test_a_fight_keeps_it_awake_however_quiet_then_it_follows_what_people_do(player, db, sheet, monkeypatch):
    from app import fight
    from app.models import Campaign

    now = [ddb_bridge.time.time()]
    monkeypatch.setattr(ddb_bridge.time, "time", lambda: now[0])
    ddb_bridge.active(db)
    now[0] += 3600  # an hour with no one around
    assert not ddb_bridge.awake(db)["awake"]
    campaign = db.get(Campaign, char(db, "Cole").campaign_id)
    fight.heard(db, campaign, {"round": 1, "turn": 1, "order": [{"key": "t-e1", "name": "Enemy 1", "kind": "monster", "initiative": 15, "active": True}]})
    db.commit()
    assert ddb_bridge.awake(db)["awake"]
    fight.heard(db, campaign, None)
    db.commit()
    assert not ddb_bridge.awake(db)["awake"]


def test_a_change_still_waiting_gives_up_once_its_sheet_goes_quiet(player, db, sheet, monkeypatch):
    """Decided 2026-10-28: a waiting change gives up a few minutes after its sheet was last heard (not hours after
    anyone was around), and is listed to make by hand, so nothing waits all evening at a busy table."""
    now = [ddb_bridge.time.time()]
    monkeypatch.setattr(ddb_bridge.time, "time", lambda: now[0])
    cole = char(db, "Cole")
    ddb_bridge.add(db, cole, "hp", {"amount": -3}, "Cole took 3")  # then the sheet closed before it was made
    now[0] += 2 * 60
    assert ddb_bridge.awake(db)["awake"] and player.get(f"/bridge/state/{cole.id}").json()["changes"][0]["state"] == "waiting"
    now[0] += 2 * 60  # quiet for longer than the wait timer (3 minutes)
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "waiting" and "wasn't heard for 3 minutes" in st["changes"][0]["error"]  # (for its sheet)
    assert db.scalar(select(BridgeIntent)).state == "not_yet" and st["to_make"] == []


def test_a_change_needs_its_sheet_open_with_the_extension(player, db, sheet):
    """Decided 2026-10-28: askdnd takes a change for D&D Beyond only while that character's sheet can be reached; otherwise
    it says how, and nothing is queued."""
    cole = char(db, "Cole")
    cole.sheet_heard_at = datetime.now(UTC) - timedelta(minutes=5)  # closed a while ago
    db.flush()
    r = player.post(f"/bridge/hp/{cole.id}", data={"amount": -1})
    assert r.status_code == 409 and "can't be reached" in r.json()["detail"] and "make the change on D&D Beyond" in r.json()["detail"]
    assert db.scalar(select(BridgeIntent)) is None  # nothing waits
    player.post("/bridge/heard/75423618?pull=1")  # the extension's pull: open again
    assert player.post(f"/bridge/hp/{cole.id}", data={"amount": -1}).status_code == 200


def test_admins_set_the_timers(admin, player, db, sheet):
    assert admin.get("/manage/bridge").status_code == 200
    admin.post("/manage/bridge", data={"idle": "45", "wait": "x"}, follow_redirects=False)
    assert ddb_bridge.timers(db) == {"idle": 45 * 60, "wait": 3 * 60}  # (kept in range)
    admin.post("/manage/bridge", data={"reset": "1"})
    assert ddb_bridge.timers(db)["idle"] == 30 * 60
    player.post("/manage/bridge", data={"idle": "5"})
    assert ddb_bridge.timers(db)["idle"] == 30 * 60  # only admins


def test_the_bridge_page_says_what_each_connection_can_change(admin, sheet):
    """Brett, 2026-11-04: Manage › askdnd › D&D Beyond bridge has a matrix of what the player's own sheet and the DM can
    each change, and how each comes about. Every kind of change the bridge makes (ddb_fields) is in one row, and every
    run it names is a live test run (each run again --via-dm every night)."""
    import os
    import re

    here = os.path.dirname(__file__)
    fields = open(os.path.join(here, "..", "app", "ddb_fields.py")).read()
    made = set(re.findall(r'kind == "(\w+)"', fields)) | {k for pair in re.findall(r'kind in \("(\w+)", "(\w+)"\)', fields) for k in pair}
    rows = [k for _, kinds, *_ in ddb_bridge.CONNECTIONS for k in kinds]
    assert sorted(rows) == sorted(set(rows)) and set(rows) == made
    runs = set(re.findall(r'"([a-z-]+)": [a-z_]+', open(os.path.join(here, "..", "scripts", "real_table.py")).read().split("RUNS = {")[1].split("}")[0]))
    assert {r for _, _, own, _ in ddb_bridge.CONNECTIONS for r in own} <= runs and "dm-backup" in runs
    page = admin.get("/manage/bridge").text
    assert "What each connection can change" in page and page.count("<tr><td>") >= len(ddb_bridge.CONNECTIONS)
    assert "Rolls into D&amp;D Beyond's Game Log" in page and "Through the DM" in page and "Neither" in page


def test_a_batch_no_sheet_ever_answers_for_stops_after_three_tries(player, db, sheet, monkeypatch):
    """A tab left from before the extension was reloaded takes nothing: the offer counts as a try, and after
    MAX_ATTEMPTS the change is listed to make by hand instead of being offered forever."""
    monkeypatch.setattr(ddb_bridge, "SENDING_SECONDS", -1)
    cole = char(db, "Cole")
    drink(db, cole)
    for _ in range(ddb_bridge.MAX_ATTEMPTS + 1):
        ddb_bridge.outbox(db, cole)  # offered, never answered
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "not_yet" and "The sheet didn't answer" in st["changes"][0]["error"]


# ------------------------------------------------------------------ everything a player changes in play


def cole_field(db, field):
    return ddb_fields.value(char(db, "Cole").snapshot.raw, field)


SOUL_COIN, BAG, QUIVER, LUCKSTONE, ROD = 992695540, 340867412, 358545286, 819724150, 758020411
CHANGES = [  # what a page asks for, the sheet's own request it becomes (seen on Vi's sheet, 2026-10-27), the field after
    ({"kind": "death", "fail": 1}, "PUT", "life/death-saves", {"failCount": 1, "successCount": 0}, "death", {"failCount": 1, "successCount": 0}),
    ({"kind": "set", "field": "inspiration", "value": False}, "PUT", "character/inspiration", {"inspiration": False}, "inspiration", False),
    ({"kind": "set", "field": "condition:1", "value": True}, "PUT", "condition", {"id": 1, "level": None, "totalHp": 51}, "condition:1", True),
    ({"kind": "set", "field": "exhaustion", "value": 2}, "PUT", "condition", {"id": 4, "level": 2, "totalHp": 51}, "exhaustion", 2),
    ({"kind": "short_rest", "spend": {"184968818": 2}}, "POST", "character/rest/short",
     {"classHitDiceUsed": {"184968818": 2}, "resetMaxHpModifier": False}, "hitdice:184968818", 2),
    ({"kind": "use", "field": "slot:2", "delta": 1}, "PUT", "spell/slots", {"level2": 1}, "slot:2", 1),
    ({"kind": "use", "field": "pact:1", "delta": 1}, "PUT", "spell/pact-magic", {"level1": 1}, "pact:1", 1),
    ({"kind": "use", "field": "uses:9414013", "delta": 1}, "PUT", "action/limited-use", {"id": "9414013", "uses": 1}, "uses:9414013", 1),
    ({"kind": "set", "field": f"equipped:{ROD}", "value": False}, "PUT", "inventory/item/equipped", {"id": ROD, "value": False}, f"equipped:{ROD}", False),
    ({"kind": "set", "field": f"attuned:{LUCKSTONE}", "value": False}, "PUT", "inventory/item/attuned", {"id": LUCKSTONE, "value": False}, f"attuned:{LUCKSTONE}", False),
    ({"kind": "use", "field": f"charges:{SOUL_COIN}", "delta": 2}, "PUT", "inventory/item/charge", {"id": SOUL_COIN, "uses": 2, "charges": 2}, f"charges:{SOUL_COIN}", 2),
    ({"kind": "use", "field": "coin:gp", "delta": -54}, "PUT", "inventory/currency/gold", {"amount": 600}, "coin:gp", 600),
    ({"kind": "set", "field": f"container:{ROD}", "value": BAG}, "PUT", "inventory/item/move",
     {"id": ROD, "containerEntityId": BAG, "containerEntityTypeId": 1439493548}, f"container:{ROD}", BAG),
    ({"kind": "remove_item", "item": QUIVER}, "DELETE", "inventory/item", {"id": QUIVER}, f"item:{QUIVER}", None),
    ({"kind": "add_item", "item": POTION, "quantity": 1}, "POST", "inventory/item", {}, "add:8960641", 3),
]


@pytest.mark.parametrize("ask,method,path,body,field,after", CHANGES, ids=[c[0]["kind"] + " " + c[4] for c in CHANGES])
def test_every_change_a_player_makes_goes_as_the_sheets_own_request(player, db, sheet, monkeypatch, ask, method, path, body, field, after):
    """Roadmap step 3 (Brett, 2026-10-27: everything a player changes in play, checked against DDB Importer's list):
    each change is the sheet's own request, read back from D&D Beyond before askdnd counts it."""
    sheet["pactMagic"] = [{"level": 1, "used": 0, "available": 1}]
    most = ddb_sheet.most  # (Cole isn't a Warlock: give him one Pact Magic slot)
    monkeypatch.setattr(ddb_sheet, "most", lambda data, kind, ref: 1 if kind == "pact" else most(data, kind, ref))
    sheet["classes"][0]["hitDiceUsed"] = 0
    characters.refresh(db, char(db, "Cole"))
    cole = char(db, "Cole")
    st = player.post(f"/bridge/change/{cole.id}", json=ask)
    assert st.status_code == 200, st.text
    assert st.json()["changes"][0]["state"] == "waiting" and st.json()["changes"][0]["label"].startswith("Cole: ")
    batch = ddb_bridge.outbox(db, cole)
    op = batch["ops"][0]
    assert (op["method"], op["path"]) == (method, f"/character/v5/{path}") and (method, op["path"]) in ddb_fields.WRITES
    assert op["body"]["characterId"] == 75423618 and body.items() <= op["body"].items()
    assert op["read"] == ddb_fields.steps(field) and op["to"] == after
    make(sheet, batch)
    ddb_bridge.delivered(db, batch["id"], ok=True)
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"] == [] and st["log"][0]["state"] == "live" and cole_field(db, field) == after


def test_an_added_item_is_d_and_d_beyonds_own(player, db, sheet):
    """Another of an item the character has: D&D Beyond's own definition, carried by the character."""
    cole = char(db, "Cole")
    player.post(f"/bridge/change/{cole.id}", json={"kind": "add_item", "item": POTION, "quantity": 2})
    op = ddb_bridge.outbox(db, cole)["ops"][0]
    assert op["body"]["equipment"] == [{"containerEntityId": 75423618, "containerEntityTypeId": 1581111423, "entityId": 8960641,
                                        "entityTypeId": 112130694, "quantity": 2}]
    assert (op["from"], op["to"]) == (2, 4)  # how many Potions of Healing in all: a repeat never adds twice


def test_hit_dice_are_spent_as_a_short_rest_that_goes_first(player, db, sheet):
    """D&D Beyond spends Hit Dice only in a Short Rest, which restores what a Short Rest restores: it's written first,
    so a use in the same batch lands after it, and what the rest restored isn't logged as D&D Beyond's own change."""
    cole = char(db, "Cole")
    next(a for a in sheet["actions"]["class"] if a["id"] == "9414030")["limitedUse"]["numberUsed"] = 2  # Focus Points spent
    characters.refresh(db, cole)
    player.post(f"/bridge/change/{cole.id}", json={"kind": "use", "field": "uses:9414013", "delta": 1})
    player.post(f"/bridge/change/{cole.id}", json={"kind": "short_rest", "spend": {"194083739": 1}})
    batch = ddb_bridge.outbox(db, cole)
    assert [op["field"] for op in batch["ops"]] == ["hitdice:194083739", "uses:9414013"]
    make(sheet, batch)
    next(a for a in sheet["actions"]["class"] if a["id"] == "9414030")["limitedUse"]["numberUsed"] = 0  # the rest restored them
    ddb_bridge.delivered(db, batch["id"], ok=True)
    log = player.get(f"/bridge/state/{cole.id}").json()["log"]
    assert [entry["state"] for entry in log] == ["live", "live", "seen"]  # (the seen one: the Focus Points spent above)
    assert "a Short Rest, spending 1 Hit Die" in log[0]["text"] + log[1]["text"] and "2 used → 0 used" not in log[2]["text"]


def test_a_change_with_no_room_left_says_why_and_lists_nothing_to_write(player, db, sheet):
    """How many a slot, a use or a charge can be is worked out from the sheet, never taken from the page."""
    cole = char(db, "Cole")
    player.post(f"/bridge/change/{cole.id}", json={"kind": "use", "field": "slot:1", "delta": 5, "max": 99})  # Cole has 4
    assert ddb_bridge.outbox(db, cole) is None
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "not_yet" and "no room" in st["changes"][0]["error"]
    player.post(f"/bridge/dismiss/{st['changes'][0]['id']}")
    player.post(f"/bridge/change/{cole.id}", json={"kind": "use", "field": "uses:9414015", "delta": 2})  # 1 use
    assert ddb_bridge.outbox(db, cole) is None
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "not_yet" and "no room" in st["changes"][0]["error"]
    player.post(f"/bridge/dismiss/{st['changes'][0]['id']}")
    # a change and its undo before D&D Beyond had it: nothing to write, done
    player.post(f"/bridge/change/{cole.id}", json={"kind": "use", "field": "coin:gp", "delta": 5})
    player.post(f"/bridge/change/{cole.id}", json={"kind": "set", "field": "inspiration", "value": False})
    player.post(f"/bridge/change/{cole.id}", json={"kind": "use", "field": "coin:gp", "delta": -5})
    player.post(f"/bridge/change/{cole.id}", json={"kind": "set", "field": "inspiration", "value": True})
    assert ddb_bridge.outbox(db, cole) is None
    assert player.get(f"/bridge/state/{cole.id}").json()["changes"] == []


@pytest.mark.parametrize("ask", [
    {"kind": "set", "field": "hp", "value": 3}, {"kind": "set", "field": "condition:99", "value": True},
    {"kind": "set", "field": "exhaustion", "value": 7}, {"kind": "set", "field": "inspiration", "value": "yes"},
    {"kind": "use", "field": "coin:gp", "delta": 1.5}, {"kind": "use", "field": "xp", "delta": 100},
    {"kind": "set", "field": f"container:{ROD}", "value": POTION}, {"kind": "remove_item", "item": 1},
    {"kind": "short_rest", "spend": {"1": 1}}, {"kind": "rename", "value": "Sarkas"},
    {"kind": "set", "field": "prepared:21171650", "value": False}, {"kind": "use", "field": "slot:4", "delta": 1}])
def test_only_changes_the_bridge_can_make_are_taken(player, db, sheet, ask):
    """Left out on purpose (Brett, 2026-10-27): experience points, custom names and custom items."""
    assert player.post(f"/bridge/change/{char(db, 'Cole').id}", json=ask).status_code == 400


def test_what_changed_on_d_and_d_beyond_is_said_in_words(player, db, sheet):
    sheet["deathSaves"]["failCount"] = 1
    sheet["conditions"] = [{"id": 12, "level": None}]
    sheet["currencies"]["gp"] = 650
    sheet["inventory"] = [i for i in sheet["inventory"] if i["id"] != QUIVER]
    sheet["inventory"].append({**copy.deepcopy(sheet["inventory"][5]), "id": 4242, "quantity": 1})
    st = player.post("/bridge/heard/75423618").json()
    text = st["log"][0]["text"]
    for said in ("Death Saving Throws 0 successes, 0 failures → 0 successes, 1 failures", "Prone off → on", "gold 654 → 650",
                 "Potion of Healing added (×1)", "Quiver removed"):
        assert said in text


def test_the_full_check_takes_one_of_each_out_and_puts_everything_back(admin, db, sheet, monkeypatch):
    """Manage › askdnd › D&D Beyond bridge › Check everything: every kind of change the test character can take, out
    and back, each confirmed by read-back; the test character ends as it began."""
    monkeypatch.setattr(ddb_bridge, "TEST_DDB_ID", "75423618")
    monkeypatch.setattr(ddb_bridge, "TEST_ITEM", "Potion of Healing")
    monkeypatch.setattr(ddb, "fetch_character_json", lambda _id, timeout=None: copy.deepcopy(sheet))
    cole = char(db, "Cole")
    owned_by(db, cole, "admin@example.com")
    before = ddb_fields.tracked(copy.deepcopy(sheet))
    admin.post("/bridge/hello", json={"sheets": ["75423618"]})
    assert admin.post("/bridge/check?full=1").json()["text"] == "D&D Beyond · checking…"
    out = ddb_bridge.outbox(db, cole)
    kinds = {op["field"].split(":")[0] for op in out["ops"]}
    assert {"hp", "item", "death", "inspiration", "condition", "exhaustion", "coin", "hitdice", "uses", "charges",
            "equipped", "attuned", "container", "bagcoin"} <= kinds
    make(sheet, out)
    ddb_bridge.delivered(db, out["id"], ok=True)
    back = ddb_bridge.outbox(db, cole)
    make(sheet, back)
    ddb_bridge.delivered(db, back["id"], ok=True)
    assert ddb_fields.tracked(sheet) == before
    assert admin.get("/bridge/health").json()["text"] == "D&D Beyond · working"


def test_a_check_stopped_part_way_settles_what_landed_and_puts_it_back(admin, db, sheet, monkeypatch):
    """Seen on Vi (2026-10-27): one field D&D Beyond held at a value askdnd couldn't explain stopped the whole batch, and
    the rest, which had landed, was listed to make again (a hit point taken twice). Now what landed is made, only the
    unexplained field is listed to make by hand, and the check puts back what it changed."""
    monkeypatch.setattr(ddb_bridge, "TEST_DDB_ID", "75423618")
    monkeypatch.setattr(ddb_bridge, "TEST_ITEM", "Potion of Healing")
    monkeypatch.setattr(ddb, "fetch_character_json", lambda _id, timeout=None: copy.deepcopy(sheet))
    cole = char(db, "Cole")
    owned_by(db, cole, "admin@example.com")
    before = ddb_fields.tracked(copy.deepcopy(sheet))
    admin.post("/bridge/hello", json={"sheets": ["75423618"]})
    admin.post("/bridge/check?full=1")
    out = ddb_bridge.outbox(db, cole)
    make(sheet, out)
    sheet["conditions"] = [c for c in sheet["conditions"] if c["id"] != ddb_fields.EXHAUSTION] + [{"id": ddb_fields.EXHAUSTION, "level": 3}]
    ddb_bridge.delivered(db, out["id"], ok=True)
    st = admin.get(f"/bridge/state/{cole.id}").json()
    assert [c["label"] for c in st["changes"] if c["state"] == "not_yet"] == ["Check: Exhaustion level 1"]
    assert st["to_make"] == ["Exhaustion level 1 (D&D Beyond has level 3)"]
    back = ddb_bridge.outbox(db, cole)
    assert {op["field"] for op in back["ops"]} >= {"hp", "death", "inspiration"} and "exhaustion" not in {op["field"] for op in back["ops"]}
    make(sheet, back)
    ddb_bridge.delivered(db, back["id"], ok=True)
    assert {f: v for f, v in ddb_fields.tracked(sheet).items() if f != "exhaustion"} == {f: v for f, v in before.items() if f != "exhaustion"}
    assert admin.get("/bridge/health").json()["text"] == "D&D Beyond · check failed"


def test_askdnd_and_the_extension_read_every_kind_of_field_the_same_way():
    """The steps ddb-page.js `pick` follows too: a list picked by id or level (as text), a dict's lists joined, a sum, presence."""
    data = {"actions": {"race": [], "class": [{"id": "9", "limitedUse": {"numberUsed": 2}}], "item": None},
            "conditions": [{"id": 12, "level": None}],
            "spellSlots": [{"level": 1, "used": 1}], "inventory": [{"id": 1, "quantity": 2, "definition": {"id": 7}},
                                                                    {"id": 2, "quantity": 3, "definition": {"id": 7}}]}
    assert [ddb_fields.value(data, f) for f in ("uses:9", "condition:12", "condition:1", "exhaustion", "slot:1", "add:7", "add:8")] \
        == [2, True, False, 0, 1, 5, 0]


def test_every_check_askdnd_sends_the_extension_is_one_it_can_read():
    """Nov 5 (feedback 17): the server's reader learned `count` for a new familiar form, the extension's never did, and
    every Find Familiar with a new form was refused as "changed". Every field's check is sent in steps the extension's
    `pick` follows (ddb_fields.wire), and the extension still follows each of those."""
    import os
    import re

    here = os.path.dirname(__file__)
    src = open(os.path.join(here, "..", "app", "ddb_fields.py")).read()
    kinds = set(re.findall(r'^        "(\w+)": \[', src.split("def steps")[1].split("}[kind]")[0], re.M))
    page = open(os.path.join(here, "..", "extension", "askdnd-bridge", "ddb-page.js")).read().split("function pick")[1].split("const same")[0]
    assert all(f"'{k}' in s" in page for k in ddb_fields.EXTENSION_READS)
    special = {"or", "present", "read", "sum", "count"}  # (every step app/ddb_fields.py `pick` treats specially)

    def unread(st):
        for x in st:
            if isinstance(x, dict):
                if "read" in x:
                    yield from (y for v in x["read"].values() for y in unread(v))
                elif set(x) & special - set(ddb_fields.EXTENSION_READS):
                    yield x

    for k in sorted(kinds):
        field = k if k in ("hp", "death", "inspiration", "exhaustion") else f"{k}:1" if k != "prep" else "prep:1:2"
        read, _, _ = ddb_fields.wire(field, {}, 0, 1)
        assert not list(unread(read)), (k, read)


def test_a_new_familiar_form_is_checked_so_the_extension_can_tell():
    """Adding one to the Familiar group (2) adds 2 to the sum of that monster's group ids, whatever else of it is there
    (here: a Wild Shape form, group 13)."""
    before = {"creatures": [{"groupId": 13, "definition": {"id": 99}}, {"groupId": 2, "definition": {"id": 5}}]}
    after = {"creatures": before["creatures"] + [{"groupId": 2, "definition": {"id": 99}}]}
    read, frm, to = ddb_fields.wire("familiar_add:99", before, 0, 1)
    assert (frm, to) == (13, 15) and ddb_fields.pick(before, read) == frm and ddb_fields.pick(after, read) == to
    assert ddb_fields.value(after, "familiar_add:99") == 1  # (askdnd's own reading, as before)
    assert ddb_fields.name({}, "familiar_add:99") == "familiar forms on Extras"


def ddb_roll(rid="r-1", scope="gameId", kind="check", how="", values=(14,), constant=5, total=19, action="Stealth", target=None):
    """A finished roll as the sheet sends it to D&D Beyond's game log (seen on Vi's sheet, 2026-10-27). D&D Beyond's
    user 101 is the roller; rolled to one person, `target` is who."""
    return {"id": rid, "action": action, "scope": scope, "user": 101, "target": target, "rolls": [{
        "diceNotation": {"constant": constant, "set": [{"count": len(values), "dieType": "d20", "operation": 0,
                                                        "dice": [{"dieType": "d20", "dieValue": v} for v in values]}]},
        "rollKind": how, "rollType": kind, "result": {"constant": constant, "text": "", "total": total, "values": list(values)}}]}


def test_a_roll_made_on_d_and_d_beyond_comes_into_table_rolls_once(player, dm, db, sheet):
    """Roadmap step 3e (Brett, 2026-10-27): a roll made on D&D Beyond by habit still reaches the table, marked "on
    D&D Beyond"; heard, and kept once (askdnd's own rolls go the other way, app/gamelog.py)."""
    from app.models import TableRoll
    player.post("/bridge/roll/75423618", json=ddb_roll(how="advantage", values=(4, 14)))
    player.post("/bridge/roll/75423618", json=ddb_roll(how="advantage", values=(4, 14)))  # heard twice, recorded once
    rows = db.scalars(select(TableRoll)).all()
    assert len(rows) == 1 and (rows[0].kind, rows[0].mode, rows[0].kept, rows[0].total, rows[0].formula) == ("check", "adv", 14, 19, "2d20+5")
    html = dm.get("/rolls").text
    assert "Stealth" in html and "on D&amp;D Beyond" in html
    assert "roll-follow" not in player.get("/rolls").text  # only shown: no reroll or added die on D&D Beyond's dice

    player.post("/bridge/roll/75423618", json=ddb_roll(rid="r-2", scope="userId", target=101, action="Perception"))  # to self
    assert "Perception" not in dm.get("/rolls").text
    player.post("/bridge/roll/75423618", json=ddb_roll(rid="r-4", scope="userId", target=202, action="Insight"))  # to the DM
    assert db.scalar(select(TableRoll.visibility).where(TableRoll.ddb_roll_id == "r-4")) == "dm"
    set_role(db, "dm@example.com")
    assert "Insight" in dm.get("/rolls").text
    assert dm.post("/bridge/roll/75423618", json=ddb_roll(rid="r-3")).json() == {"ok": False}  # only the player's own browser


def test_the_extension_makes_only_the_requests_askdnd_knows():
    """The extension's own list of requests (ddb-page.js WRITES) is askdnd's (ddb_fields.WRITES): a page can't ask it for
    anything else, and nothing askdnd writes is refused there."""
    import re
    from pathlib import Path
    js = (Path(__file__).parent.parent / "extension/askdnd-bridge/ddb-page.js").read_text()
    listed = js[js.index("const WRITES"):js.index("]);", js.index("const WRITES"))]
    assert {tuple(w.split(" ", 1)) for w in re.findall(r"'([A-Z]+ /[^']+)'", listed)} == ddb_fields.WRITES


def test_the_store_copy_of_the_extension_is_for_askdnds_own_sites(tmp_path, monkeypatch):
    """The Chrome Web Store's copy (scripts/build_extension.py) leaves out localhost, holds every file its manifest
    names, and the extension takes a key only from the askdnd sites its manifest lists."""
    import json
    import re
    import zipfile
    from pathlib import Path

    from scripts import build_extension

    monkeypatch.setattr(build_extension, "OUT", tmp_path)
    with zipfile.ZipFile(build_extension.build()) as z:
        store = json.loads(z.read("manifest.json"))
        names = set(z.namelist())
    assert "localhost" not in json.dumps(store) and "README.md" not in names
    assert len(store["description"]) <= 132  # the Chrome Web Store's limit (it refuses the upload)
    assert {"icons/icon-128.png", "background.js", "ddb.js", "ddb-page.js", "askdnd.js", "vtt.js", "vtt-page.js"} <= names
    src = Path(__file__).parent.parent / "extension/askdnd-bridge"
    manifest = json.loads((src / "manifest.json").read_text())
    sites = re.search(r"const SITES = \[([^\]]*)\]", (src / "background.js").read_text()).group(1)
    on_askdnd = next(c for c in manifest["content_scripts"] if c["js"] == ["askdnd.js"])
    assert {s.strip(" '") for s in sites.split(",")} == {p.removesuffix("/*") for p in on_askdnd["matches"]}


def test_the_pages_tick_draws_the_pill_while_your_sheet_isnt_connected(player, db, sheet):
    """The tick draws the pill with no page around it; beta's failed here for a player waiting to connect (ASKDND-V2-6)."""
    cole = char(db, "Cole")
    cole.sheet_heard_at = None
    db.flush()
    assert "Open your sheet to connect" in player.post(f"/live/sync?c={cole.id}").text


def test_the_live_pill_says_whether_your_sheet_is_connected_or_has_something_to_make_by_hand(player, db, sheet):
    """The Live pill answers one question (docs/mockups/table-without-modes.html): connected while the bridge hears your
    sheet, something to make by hand when a change couldn't be made, else what to do to connect."""
    cole = char(db, "Cole")
    pill = lambda: player.get(f"/characters/{cole.id}").text.split('id="live-pill"')[1].split("</button>")[0]  # noqa: E731
    cole.sheet_heard_at = None  # no extension yet
    db.flush()
    assert "Open your sheet to connect" in pill() and ">Connected<" not in pill()
    player.post("/bridge/heard/75423618?pull=1")  # the extension's pull: the sheet can be reached
    assert 'live-ago">Connected<' in pill() and " step" in pill().split(">")[0]
    drink(db, cole)
    db.scalar(select(BridgeIntent)).state = "not_yet"
    db.flush()
    assert "1 didn't go through" in pill()
    cole.sheet_heard_at -= timedelta(minutes=5)  # the sheet was closed a while ago
    db.scalar(select(BridgeIntent)).state = "dismissed"
    db.flush()
    assert "Connected to" not in pill()


def _gave_up(db, player, cole, monkeypatch, now):
    """Cole took 3 in askdnd, then his sheet closed before it was made: after the wait timer it's listed to make."""
    monkeypatch.setattr(ddb_bridge.time, "time", lambda: now[0])
    ddb_bridge.add(db, cole, "hp", {"amount": -3}, "Cole took 3")
    now[0] += 4 * 60
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "waiting" and "as soon as the sheet is open again" in st["changes"][0]["error"]
    assert st["to_make"] == []  # it waits for the sheet, not for a person (making it by hand too would make it twice)
    cole.sheet_heard_at = datetime.fromtimestamp(now[0], UTC)  # (the sheet is open again from here)
    db.flush()


def test_a_change_that_gave_up_is_made_by_itself_once_its_sheet_is_open_again(player, db, sheet, monkeypatch):
    """Decided 2026-10-28: no button and no making it by hand: the sheet's next read sends it."""
    cole, now = char(db, "Cole"), [ddb_bridge.time.time()]
    _gave_up(db, player, cole, monkeypatch, now)
    st = player.post("/bridge/heard/75423618?pull=1").json()  # the extension's pull, D&D Beyond still at 37
    assert st["changes"][0]["state"] == "waiting" and st["to_make"] == []
    batch = ddb_bridge.outbox(db, cole)
    assert [op["body"]["removedHitPoints"] for op in batch["ops"]] == [17]  # 37 → 34


def test_a_change_made_by_hand_on_d_and_d_beyond_is_ticked_off(player, db, sheet, monkeypatch):
    cole, now = char(db, "Cole"), [ddb_bridge.time.time()]
    _gave_up(db, player, cole, monkeypatch, now)
    sheet["removedHitPoints"] = 17  # the player made it on D&D Beyond: 34
    st = player.post("/bridge/heard/75423618").json()
    assert st["changes"] == [] and st["to_make"] == []  # never asked twice
    assert st["log"][0]["text"] == "Cole took 3 (made on D&D Beyond)"


def test_if_d_and_d_beyond_changed_meanwhile_askdnd_doesnt_guess_and_never_asks_twice(player, db, sheet, monkeypatch):
    cole, now = char(db, "Cole"), [ddb_bridge.time.time()]
    _gave_up(db, player, cole, monkeypatch, now)
    sheet["removedHitPoints"] = 21  # something else happened on D&D Beyond: 30
    st = player.post("/bridge/heard/75423618").json()
    assert st["changes"][0]["state"] == "not_yet" and "D&D Beyond changed since" in st["changes"][0]["error"]
    assert st["to_make"] == ["Hit points 34 (D&D Beyond has 30)"]  # now one for a person: the end result it wanted, not 3 more off


def test_marking_askdnd_awake_never_waits_for_another_request(db_engine):
    """Sentry ASKDND-V2-4 (2026-10-29): ending a condition and the extension's check-in deadlocked over the bridge's
    awake timer, each holding what the other wanted. A request that finds another one marking it right now skips it."""
    import time

    from sqlalchemy import delete, text
    from sqlalchemy.orm import Session

    from app.models import ToolSetting

    with Session(db_engine) as setup:
        setup.merge(ToolSetting(key=ddb_bridge.AWAKE_KEY, value='{"last": 0}'))
        setup.commit()
    try:
        with Session(db_engine) as holder, Session(db_engine) as other:
            holder.execute(select(ToolSetting).where(ToolSetting.key == ddb_bridge.AWAKE_KEY).with_for_update())  # marking it now
            other.execute(text("SET lock_timeout = '2s'"))  # (waiting would fail here instead of hanging)
            start = time.monotonic()
            ddb_bridge.active(other)
            other.commit()
            assert time.monotonic() - start < 1
            holder.rollback()
        with Session(db_engine) as s:  # nobody else marking it: it's marked
            ddb_bridge.active(s)
            s.commit()
            assert ddb_bridge._wake_row(s)[1]["last"] > time.time() - 5
            ddb_bridge.active(s)  # again at once: not written again (15 seconds)
            assert not s.dirty
    finally:
        with Session(db_engine) as s:
            s.execute(delete(ToolSetting).where(ToolSetting.key == ddb_bridge.AWAKE_KEY))
            s.commit()


def test_the_batch_lock_never_waits_on_a_new_changes_character_link():
    """Sentry ASKDND-V2-5 (2026-10-29): the batch lock is FOR NO KEY UPDATE. FOR UPDATE waited on the light hold a new
    bridge change takes on its character's row, while that request waited on the lock's own update, and they deadlocked."""
    from sqlalchemy.dialects import postgresql

    seen = []

    class Db:
        def execute(self, stmt):
            seen.append(str(stmt.compile(dialect=postgresql.dialect())))

    ddb_bridge._lock(Db(), 9)
    assert seen and seen[0].endswith("FOR NO KEY UPDATE")


def test_a_closed_sheet_tells_open_pages_at_once(player, db, sheet, monkeypatch):
    """Brett, 2026-10-30: the sheet closed and pages kept saying Connected: askdnd noted it and told nobody."""
    from app import realtime

    sent = []
    monkeypatch.setattr(realtime, "publish", lambda campaign_id, kind, **data: sent.append((kind, data)))
    cole = char(db, "Cole")
    player.post("/bridge/heard/75423618?pull=1")
    sent.clear()
    player.post("/bridge/closed/75423618")
    assert ("character", {"id": cole.id}) in sent and not ddb_bridge.reachable(cole)
    pill = player.get(f"/characters/{cole.id}").text.split('id="live-pill"')[1].split("</button>")[0]
    assert "Open your sheet to connect" in pill
    sent.clear()
    player.post("/bridge/heard/75423618?pull=1")  # back: said once
    assert ("character", {"id": cole.id}) in sent
    sent.clear()
    player.post("/bridge/heard/75423618?pull=1")  # still there: not news
    assert ("character", {"id": cole.id}) not in sent


def test_someone_with_no_character_sees_how_many_sheets_are_connected(player, dm, db, sheet):
    """Brett, 2026-10-30: the DM's pill said Connected to D&D Beyond from someone else's sheet, with no extension."""
    from tests.roles import set_role

    set_role(db, "dm@example.com", "dm")
    player.post("/bridge/closed/75423618")
    pill = lambda: dm.get("/c/main/").text.split('id="live-pill"')[1].split("</button>")[0]  # noqa: E731
    assert "1 of 2 sheets connected" in pill() and 'live-ago">Connected<' not in pill() and " step" not in pill().split(">")[0]
    player.post("/bridge/heard/75423618?pull=1")
    assert "2 of 2 sheets connected" in pill() and " step" in pill().split(">")[0]


def test_the_pill_says_how_long_a_sheet_counts_as_open_and_the_window_links_the_extension(player, db, sheet):
    cole = char(db, "Cole")
    sheet["campaign"] = {"id": 8224496, "name": "VTT test"}
    characters.refresh(db, cole)
    player.post("/bridge/heard/75423618?pull=1")
    pill = player.get(f"/characters/{cole.id}").text.split('id="live-pill"')[1].split(">")[0]
    assert 'data-log="on"' in pill and 'data-log-until="0"' not in pill and "data-wants-bridge" in pill
    assert "chromewebstore.google.com" in player.get("/live", params={"c": cole.id}).text



def test_d_and_d_beyond_is_read_with_the_database_let_go(db, sheet, monkeypatch):
    """Architecture review, 2026-11-02: a request held its database connection and the character's lock while D&D Beyond
    took up to 15 seconds (Sentry ASKDND-V2-7 ran beta out of connections). The bridge's reads now happen with no
    transaction open, and the lock is taken again after."""
    cole = char(db, "Cole")
    open_while_reading = []

    def fetch(_id):
        open_while_reading.append(db.in_transaction())
        return copy.deepcopy(sheet)

    monkeypatch.setattr(characters, "FETCH", fetch)
    ddb_bridge.heard(db, cole)  # the extension heard the sheet save
    assert open_while_reading == [False] and ddb_bridge.numbers(cole)["max"] == 51


def test_an_older_read_never_replaces_a_newer_copy(db, sheet):
    """Two requests can read the same sheet at once now that neither holds the lock while D&D Beyond answers: whichever
    finishes last, the copy kept is the one read last."""
    cole = char(db, "Cole")
    older = characters.read(cole.ddb_id)
    sheet["removedHitPoints"] = 20
    characters.store(db, cole, characters.read(cole.ddb_id))  # a later read, kept first
    characters.store(db, cole, older)  # the earlier one arrives late
    assert characters.character_summary(cole)["hit_points"]["current"] == 31


def test_admins_read_the_log_further_back_with_its_batches(admin, player, db, sheet, monkeypatch):
    """Brett, 2026-11-02 (the live test's death save miss was past the 30 lines a page shows): Manage's log goes back
    further and says, per batch, how old askdnd's copy was when it was built (null: read fresh)."""
    cole = char(db, "Cole")
    for n in range(35):
        ddb_bridge._log(db, cole.id, f"line {n}", "seen")
    ddb_bridge.add(db, cole, "hp", {"amount": -5}, "Cole took 5")
    copy_built = ddb_bridge.outbox(db, cole)  # on askdnd's copy, read moments ago
    make(sheet, copy_built)
    ddb_bridge.delivered(db, copy_built["id"], ok=True)
    ddb_bridge.add(db, cole, "hp", {"amount": -80}, "Cole took 80")  # down to 0: read fresh first
    ddb_bridge.outbox(db, cole)
    db.flush()
    got = admin.get(f"/manage/bridge/log/{cole.id}?limit=50").json()
    assert len(got["log"]) > 30
    newest, older = got["batches"][0], got["batches"][1]
    assert newest["intents"] == ["Cole took 80"] and newest["copy_age"] is None and newest["state"] == "sending"
    assert older["intents"] == ["Cole took 5"] and older["copy_age"] is not None and older["state"] == "done"
    assert player.get(f"/manage/bridge/log/{cole.id}").status_code == 403  # admins only


def test_a_stopped_change_offers_try_again_and_undo_in_the_live_window(player, dm, db, sheet):
    """Nov 3 (Brett): the bridge's panel says "Try again or undo it in askdnd", but only a page nothing linked to had
    the buttons. The Live window lists each stopped change under its character, for its player and the DM; no one else
    may press them (they were open to anyone signed in)."""
    cole, trah = char(db, "Cole"), char(db, "Trah")
    set_role(db, "dm@example.com", "dm")
    ddb_bridge.add(db, cole, "hp", {"amount": -1}, "Cole took 1")
    batch = ddb_bridge.outbox(db, cole)
    ddb_bridge.delivered(db, batch["id"], ok=False, error="That isn't a change askdnd may make.")
    db.commit()
    it = db.scalar(select(BridgeIntent).where(BridgeIntent.character_id == cole.id))
    page = player.get("/live", params={"c": cole.id}).text
    assert "Cole took 1" in page and f'hx-post="/bridge/retry/{it.id}?live=1"' in page and f'hx-post="/bridge/dismiss/{it.id}?live=1"' in page
    assert f"/bridge/retry/{it.id}" in dm.get("/live", params={"c": cole.id}).text  # the DM too
    r = player.post(f"/bridge/retry/{it.id}?live=1")
    assert r.status_code == 200 and "How each sheet is connected" in r.text and json.loads(r.headers["HX-Trigger"])["characterChanged"]
    db.refresh(it)
    assert it.state == "waiting"
    ddb_bridge.add(db, trah, "hp", {"amount": -1}, "Trah took 1")
    db.commit()
    theirs = db.scalar(select(BridgeIntent).where(BridgeIntent.character_id == trah.id))
    assert player.post(f"/bridge/dismiss/{theirs.id}").status_code == 404  # not their character
    db.refresh(theirs)
    assert theirs.state == "waiting"


# ------------------------------------------------------------------ the sheet as it reads itself (extension 0.9.9)
SOUL_COIN = 992695540  # Cole's Soul Coin: 3 charges


def coin_left(cole) -> int:
    return next(i for i in characters.character_summary(cole)["inventory"] if i["key"] == f"item:{SOUL_COIN}")["charges"]["left"]


def as_read(sheet, used, at="2026-11-03T20:06:58.000Z"):
    """The sheet as the extension reads it, signed in: newer than D&D Beyond's public copy (the fake `sheet`)."""
    data = copy.deepcopy(sheet)
    data.pop("askdnd", None)  # (what askdnd adds to a public read: the sheet itself never has it)
    next(i for i in data["inventory"] if i["id"] == SOUL_COIN)["limitedUse"]["numberUsed"] = used
    data["dateModified"] = at
    return data


def test_a_fresh_read_keeps_the_class_spell_lists(player, db, sheet):
    """Live test, Nov 3: since 0.9.9 askdnd kept the sheet as the extension read it, which has no class spell lists, so
    Prepare spells listed only the spells already prepared. A fresh read keeps the last read's lists; a new class level
    needs new lists, so that one is left to the public read."""
    cole = char(db, "Cole")
    aid = next(s for s in sheet["askdnd"]["availableSpells"]["2190878"] if s["definition"]["name"] == "Aid")
    aid.update(id=21170801, entityTypeId=435869154)  # (a spell from the class list, ready to prepare)
    characters.refresh(db, cole)
    assert 'data-name="Aid"' in player.get(f"/characters/{cole.id}/spells/prepare").text
    player.post("/bridge/heard/75423618", json={"data": as_read(sheet, 0)})
    db.refresh(cole.snapshot)
    assert cole.snapshot.raw["askdnd"]["availableSpells"] == sheet["askdnd"]["availableSpells"]
    assert 'data-name="Aid"' in player.get(f"/characters/{cole.id}/spells/prepare").text
    leveled = as_read(sheet, 0)
    leveled["classes"][0]["level"] += 1
    assert ddb_bridge.fresh_read(db, {"email": "player@example.com"}, cole, leveled) is None


def test_a_save_is_read_from_the_sheet_itself_not_the_public_copy(player, db, sheet):
    """Brett, Nov 3: a Soul Coin's use given back on D&D Beyond stayed spent in askdnd for minutes. D&D Beyond's public
    copy can trail a save; the extension's own signed-in read can't, so askdnd keeps that one, and logs the change."""
    cole = char(db, "Cole")
    player.post("/bridge/heard/75423618")
    next(i for i in sheet["inventory"] if i["id"] == SOUL_COIN)["limitedUse"]["numberUsed"] = 1  # the public copy, stale
    st = player.post("/bridge/heard/75423618", json={"data": as_read(sheet, 0)}).json()
    db.refresh(cole.snapshot)
    assert coin_left(cole) == 3
    assert not any("Soul Coin" in entry["text"] for entry in st["log"])  # (0 → 0 as askdnd last saw it: nothing to log)


def test_a_read_is_kept_whatever_d_and_d_beyonds_stamp_says(player, db, sheet):
    """The live runs, Nov 3: D&D Beyond's dateModified goes back and forth between reads seconds apart (its servers
    disagree for a moment), so a read with an earlier-looking stamp can hold the newer sheet. It's kept."""
    cole = char(db, "Cole")
    player.post("/bridge/heard/75423618", json={"data": as_read(sheet, 0, at="2026-11-03T22:55:11.616Z")})
    player.post("/bridge/heard/75423618", json={"data": as_read(sheet, 2, at="2026-11-03T22:54:40.000Z")})
    db.refresh(cole.snapshot)
    assert coin_left(cole) == 1


def test_a_read_back_that_lags_is_read_again_not_taken_as_lost(player, db, sheet):
    """The live runs, Nov 3: right after writing, the extension's own read can still show the old value for a few
    seconds. askdnd reads D&D Beyond again, as before 0.9.9, and confirms it, instead of retrying at once and giving up."""
    cole = char(db, "Cole")
    player.post("/bridge/heard/75423618")
    player.post(f"/characters/{cole.id}/count?field=charges:{SOUL_COIN}", data={"to": "use"})
    batch = ddb_bridge.outbox(db, cole)
    make(sheet, batch)  # D&D Beyond has it (what askdnd reads next)…
    lagging = as_read(sheet, 0)  # …but the extension's read just after writing doesn't show it yet
    player.post(f"/bridge/delivered/{batch['id']}", json={"ok": True, "wrote": True, "data": lagging})
    assert [i.state for i in db.scalars(select(BridgeIntent))] == ["live"]
    assert ddb_bridge.outbox(db, cole) is None


def test_a_use_given_back_right_after_askdnd_spent_it_is_the_players(player, db, sheet):
    """Brett, Nov 3: askdnd spent a Soul Coin's use, he un-clicked it on D&D Beyond seconds later, and askdnd took that
    for its own write lost: it kept 2/3, logged nothing and would have written the use back. Confirmed from the
    extension's read right after writing, askdnd's change settles; the un-click after it is logged as his and stays."""
    cole = char(db, "Cole")
    player.post("/bridge/heard/75423618")
    player.post(f"/characters/{cole.id}/count?field=charges:{SOUL_COIN}", data={"to": "use"})
    batch = ddb_bridge.outbox(db, cole)
    r = player.post(f"/bridge/delivered/{batch['id']}", json={"ok": True, "wrote": True, "data": as_read(sheet, 1, "2026-11-03T20:06:48.000Z")})
    assert r.status_code == 200  # (the public copy, `sheet`, still says 0 used: never read here)
    assert [i.state for i in db.scalars(select(BridgeIntent))] == ["live"]
    st = player.post("/bridge/heard/75423618", json={"data": as_read(sheet, 0)}).json()
    assert st["log"][0]["text"] == "Cole (on D&D Beyond): Soul Coin 1 used → 0 used"
    assert ddb_bridge.outbox(db, cole) is None
    db.refresh(cole.snapshot)
    assert coin_left(cole) == 3


def test_only_the_player_or_the_dm_sends_the_sheet(player, dm, db, sheet):
    """A read from anyone else at the table is ignored (askdnd reads the public copy): only the character's player's
    browser, or the DM's (which makes a closed sheet's changes), reads it signed in."""
    cole = char(db, "Cole")
    set_role(db, "dm@example.com", "dm")
    player.post("/bridge/heard/75423618")
    other = copy.deepcopy(as_read(sheet, 2))
    from app import picks

    user = {"email": "someone@example.com", "name": "Someone"}
    assert ddb_bridge.fresh_read(db, user, cole, other) is None
    assert ddb_bridge.fresh_read(db, {"email": "player@example.com"}, cole, {**other, "id": 1}) is None  # another character's
    assert picks.can_edit(db, {"email": "player@example.com"}, cole)
    assert ddb_bridge.fresh_read(db, {"email": "player@example.com"}, cole, other) is not None
    dm.post("/bridge/heard/75423618", json={"data": other})
    db.refresh(cole.snapshot)
    assert coin_left(cole) == 1


# ------------------------------------------------------------------ how a change stands, in one set of words (Bridge Review)


def test_a_change_says_how_it_stands_the_same_everywhere(player, db, sheet, monkeypatch):
    """Bridge Review, Nov 3: one set of words in every place: On its way, Trying again (2 of 3), Waits for the change
    before it, Didn't go through (with Try again and Undo), then On D&D Beyond. The corner card follows its change by
    web.deliver_now's `upto`."""
    from app import web

    monkeypatch.setattr(ddb_bridge, "RETRY_SECONDS", (0, 0, 0))  # (each try offered again at once)
    cole = char(db, "Cole")
    drink(db, cole)
    db.commit()
    upto = web.deliver_now(cole)["upto"]
    follow = lambda: player.get(f"/bridge/follow/{cole.id}?upto={upto}").json()  # noqa: E731
    assert follow()["says"] == "On its way"
    batch = ddb_bridge.outbox(db, cole)
    ddb_bridge.delivered(db, batch["id"], False, "D&D Beyond answered 500.")
    db.commit()
    assert follow()["says"] == "Trying again (2 of 3)"
    ddb_bridge.add(db, cole, "set", {"field": "inspiration", "value": True}, "Cole: Heroic Inspiration")
    db.commit()
    later = web.deliver_now(cole)["upto"]
    assert player.get(f"/bridge/follow/{cole.id}?upto={later}").json()["says"] == "Trying again (2 of 3)"  # (the furthest behind)
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert [c["says"] for c in st["changes"]] == ["Waits for the change before it", "Trying again (2 of 3)"]
    for _ in range(2):
        b = ddb_bridge.outbox(db, cole)
        if b:
            ddb_bridge.delivered(db, b["id"], False, "D&D Beyond answered 500.")
    db.commit()
    f = follow()
    assert f["state"] == "failed" and f["says"] == "Didn't go through" and "(3 tries)" in f["error"]
    live_window = player.get(f"/live?c={cole.id}").text
    assert "Didn&#39;t go through" in live_window and f"/bridge/retry/{f['failed'][0]['id']}?live=1" in live_window
    assert "Cole: Heroic Inspiration" in live_window and "On its way" in live_window  # (the one after it, now on its way, without buttons)
    assert "1 didn't go through" in player.get(f"/characters/{cole.id}/battle").text  # the pill


def test_the_corner_card_follows_only_a_change_just_made(player, db, sheet):
    """A route that changes nothing on D&D Beyond (a sheet that can't be reached) still sends the extension its word, but
    names no change: there's nothing for its card to follow."""
    from datetime import UTC, datetime, timedelta

    from app import web

    cole = char(db, "Cole")
    drink(db, cole)
    db.commit()
    assert "upto" in web.deliver_now(cole)
    it = db.scalar(select(BridgeIntent))
    it.created_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert web.deliver_now(cole) == {"ddbId": "75423618"}


def test_the_bridges_icon_says_how_each_sheet_stands(player, db, sheet):
    """Bridge Review, Nov 3: the popup said Connected even with the sheet closed and a change stuck. It now says, per
    character, whether its sheet is open, what's on its way and what didn't go through, and the newest extension."""
    import json as js
    from pathlib import Path

    cole = char(db, "Cole")
    drink(db, cole)
    db.commit()
    j = player.get("/bridge/links").json()
    me = next(c for c in j["characters"] if c["name"] == "Cole")
    assert me["how"] == "sheet" and me["on_way"] == 1 and me["failed"] == 0
    assert j["version"] == js.loads((Path(__file__).parent.parent / "extension" / "askdnd-bridge" / "manifest.json").read_text())["version"]
    cole.sheet_heard_at = None
    db.commit()
    assert next(c for c in player.get("/bridge/links").json()["characters"] if c["name"] == "Cole")["how"] is None
