"""The D&D Beyond bridge, a local proof (app/ddb_bridge.py): middleware that repairs itself. D&D Beyond is never called:
a fake sheet stands in, and each test changes it the way the extension, a player or a misbehaving D&D Beyond would."""

import copy

import pytest
from sqlalchemy import select

from app import characters, config, ddb, ddb_bridge, ddb_fields, ddb_sheet
from app.importer import import_bundle
from tests.roles import set_role
from tests.table_setup import BUNDLE, COLE, char, owned_by

POTION = 758022089  # Cole's Potion of Healing (×2 in the fixture)


@pytest.fixture
def sheet(monkeypatch, db):
    """Cole's D&D Beyond sheet as a dict the test edits; askdnd reads it whenever it refreshes."""
    data = copy.deepcopy(COLE)
    data["removedHitPoints"] = 14  # 37 of 51
    monkeypatch.setattr(characters.refresh, "__defaults__", (lambda _id: copy.deepcopy(data),))
    monkeypatch.setattr(ddb_bridge.time, "sleep", lambda s: None)  # the read-back's waits
    monkeypatch.setattr(config, "DDB_BRIDGE", True)
    ddb_bridge._health.update(extension_at=0.0, sheets=[], heard_at=0.0, read_check=None, round_trip=None)
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    characters.refresh(db, cole)
    ddb_bridge.active(db)  # someone is using askdnd (the tests from test_asleep_… on cover waking and sleeping)
    return data


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


def test_a_change_is_built_on_what_d_and_d_beyond_has_when_it_goes(db, sheet):
    """An intent, not a number: hit points changed on D&D Beyond after the drink was asked for are built on, not lost."""
    cole = char(db, "Cole")
    drink(db, cole, heal=4)
    sheet["removedHitPoints"] = 20  # the player took 6 more on D&D Beyond meanwhile
    batch = ddb_bridge.outbox(db, cole)
    assert batch["ops"][0]["body"]["removedHitPoints"] == 16 and batch["ops"][0]["from"]["removedHitPoints"] == 20


def test_several_changes_go_as_one_end_state(player, db, sheet):
    """Brett, 2026-10-27: not 12 → 10 → 15 → 45 → 34, just the end state."""
    cole = char(db, "Cole")
    for amount in (-2, 5, -10):
        ddb_bridge.add(db, cole, "hp", {"amount": amount}, f"Cole {amount}")
    batch = ddb_bridge.outbox(db, cole)
    assert len(batch["ops"]) == 1 and batch["ops"][0]["body"]["removedHitPoints"] == 21  # 14 + 2 - 5 + 10


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
    assert st["changes"][0]["state"] == "not_yet" and "Tried 3 times" in st["changes"][0]["error"]
    assert st["to_make"] == ["Hit points 42 (D&D Beyond has 45)"]


def test_a_value_askdnd_cant_explain_is_never_written_over(player, db, sheet):
    cole = char(db, "Cole")
    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)
    make(sheet, batch)
    sheet["removedHitPoints"] = 30  # someone else changed it right after askdnd wrote
    ddb_bridge.delivered(db, batch["id"], ok=True)
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "not_yet" and "Nothing was written over" in st["changes"][0]["error"]
    assert ddb_bridge.outbox(db, cole) is None  # and nothing more is sent


def test_a_change_on_d_and_d_beyond_in_the_moment_before_writing_is_worked_out_again(db, sheet):
    """The extension checks each total against D&D Beyond just before writing; on a mismatch it writes nothing and
    askdnd builds the batch again from the new numbers."""
    cole = char(db, "Cole")
    drink(db, cole, heal=4)
    first = ddb_bridge.outbox(db, cole)
    sheet["removedHitPoints"] = 18
    ddb_bridge.delivered(db, first["id"], ok=False, conflicts=["hp"])
    second = ddb_bridge.outbox(db, cole)
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
    next(i for i in sheet["inventory"] if i["id"] == POTION)["quantity"] = 0
    drink(db, cole)
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


def test_a_change_on_d_and_d_beyond_is_logged_whichever_read_sees_it_first(player, db, sheet):
    """Game Mode's refresh (or a page opening) can read D&D Beyond before the bridge does: the change is still logged
    as made on D&D Beyond, once, and what askdnd is writing never is."""
    cole = char(db, "Cole")
    sheet["temporaryHitPoints"] = 5
    characters.refresh(db, cole)  # Game Mode's refresh, not the bridge
    player.post("/bridge/heard/75423618")  # the bridge reads it again: nothing new
    log = player.get(f"/bridge/state/{cole.id}").json()["log"]
    assert [entry["text"] for entry in log if entry["state"] == "seen"] == ["Cole (on D&D Beyond): temporary hit points 0 → 5"]

    drink(db, cole)
    batch = ddb_bridge.outbox(db, cole)
    make(sheet, batch)
    characters.refresh(db, cole)  # Game Mode's refresh sees askdnd's own write first
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
    assert player.get("/bridge/health").json()["text"].startswith("D&D Beyond · working (checked ")


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
    assert dm.post(f"/bridge/drink/{cole.id}/{POTION}").status_code == 403
    assert dm.post("/bridge/outbox/75423618").json() == {"batch": None}  # only the player's own browser writes the sheet
    assert player.post(f"/bridge/drink/{cole.id}/12345").status_code == 400
    assert "with D&amp;D Beyond" in player.get(f"/characters/{cole.id}/bridge").text
    monkeypatch.setattr(config, "DDB_BRIDGE", False)  # off unless DDB_BRIDGE=1, and never in production (app/config.py)
    assert player.get(f"/bridge/state/{cole.id}").status_code == 404
    assert player.get(f"/characters/{cole.id}/bridge").status_code == 404


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
        player.post(f"/bridge/hp/{cole.id}", json=ask)
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
    monkeypatch.setattr(characters.refresh, "__defaults__", (lambda _id: reads.append(_id) or copy.deepcopy(sheet),))
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
    player.post(f"/bridge/hp/{char(db, 'Cole').id}", json={"amount": -1})  # making a change wakes it too
    assert ddb_bridge.awake(db)["awake"]


def test_a_character_page_shows_what_d_and_d_beyond_has_now(player, db, sheet, monkeypatch):
    """Planning in askdnd never starts from an old number: opening a character's page (or their D&D Beyond sheet)
    reads D&D Beyond when askdnd's copy is older than Game Mode's refresh, and not otherwise."""
    from datetime import timedelta
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


def test_game_mode_keeps_it_awake_however_quiet_then_it_follows_what_people_do(player, db, sheet, monkeypatch):
    now = [ddb_bridge.time.time()]
    monkeypatch.setattr(ddb_bridge.time, "time", lambda: now[0])
    h = player.post("/bridge/game", json={"on": True}).json()
    assert h["awake"]["game_until"] == pytest.approx(now[0] + 6 * 3600)
    now[0] += 5 * 3600  # five quiet hours
    assert ddb_bridge.awake(db)["awake"]
    now[0] += 3600 + 60
    assert not ddb_bridge.awake(db)["awake"]  # its time is up, and no one has been here for half an hour
    player.post("/bridge/game", json={"on": True})  # Keep going
    player.post("/bridge/game", json={"on": False})  # Game Mode off: awake while people use it, as without it
    a = ddb_bridge.awake(db)
    assert a["awake"] and a["game_until"] is None


def test_a_change_still_waiting_keeps_it_awake_then_is_listed_to_make_by_hand(player, db, sheet, monkeypatch):
    now = [ddb_bridge.time.time()]
    monkeypatch.setattr(ddb_bridge.time, "time", lambda: now[0])
    cole = char(db, "Cole")
    ddb_bridge.add(db, cole, "hp", {"amount": -3}, "Cole took 3")  # no sheet open to deliver it
    now[0] += ddb_bridge.timers(db)["idle"] + 60
    assert ddb_bridge.awake(db)["awake"]  # still on its way
    now[0] += ddb_bridge.timers(db)["wait"]
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert not ddb_bridge.awake(db)["awake"]
    assert st["changes"][0]["state"] == "not_yet" and st["to_make"] == ["Hit points 34 (D&D Beyond has 37)"]


def test_admins_set_the_timers(admin, player, db, sheet):
    assert admin.get("/manage/bridge").status_code == 200
    admin.post("/manage/bridge", data={"idle": "45", "game": "99", "warn": "5", "wait": "x"}, follow_redirects=False)
    assert ddb_bridge.timers(db) == {"idle": 45 * 60, "game": 12 * 3600, "warn": 5 * 60, "wait": 6 * 3600}  # (kept in range)
    admin.post("/manage/bridge", data={"reset": "1"})
    assert ddb_bridge.timers(db)["idle"] == 30 * 60
    player.post("/manage/bridge", data={"idle": "5"})
    assert ddb_bridge.timers(db)["idle"] == 30 * 60  # only admins


def test_a_batch_no_sheet_ever_answers_for_stops_after_three_tries(player, db, sheet, monkeypatch):
    """A tab left from before the extension was reloaded takes nothing: the offer counts as a try, and after
    MAX_ATTEMPTS the change is listed to make by hand instead of being offered forever."""
    monkeypatch.setattr(ddb_bridge, "SENDING_SECONDS", -1)
    cole = char(db, "Cole")
    drink(db, cole)
    for _ in range(ddb_bridge.MAX_ATTEMPTS + 1):
        ddb_bridge.outbox(db, cole)  # offered, never answered
    st = player.get(f"/bridge/state/{cole.id}").json()
    assert st["changes"][0]["state"] == "not_yet" and "No D&D Beyond sheet answered" in st["changes"][0]["error"]


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
            "equipped", "attuned", "container"} <= kinds
    make(sheet, out)
    ddb_bridge.delivered(db, out["id"], ok=True)
    back = ddb_bridge.outbox(db, cole)
    make(sheet, back)
    ddb_bridge.delivered(db, back["id"], ok=True)
    assert ddb_fields.tracked(sheet) == before
    assert admin.get("/bridge/health").json()["text"].startswith("D&D Beyond · working (checked ")


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


def ddb_roll(rid="r-1", scope="gameId", kind="check", how="", values=(14,), constant=5, total=19, action="Stealth", target=None):
    """A finished roll as the sheet sends it to D&D Beyond's game log (seen on Vi's sheet, 2026-10-27). D&D Beyond's
    user 101 is the roller; rolled to one person, `target` is who."""
    return {"id": rid, "action": action, "scope": scope, "user": 101, "target": target, "rolls": [{
        "diceNotation": {"constant": constant, "set": [{"count": len(values), "dieType": "d20", "operation": 0,
                                                        "dice": [{"dieType": "d20", "dieValue": v} for v in values]}]},
        "rollKind": how, "rollType": kind, "result": {"constant": constant, "text": "", "total": total, "values": list(values)}}]}


def test_a_roll_made_on_d_and_d_beyond_comes_into_table_rolls_once(player, dm, db, sheet):
    """Roadmap step 3e (Brett, 2026-10-27): a roll made on D&D Beyond by habit still reaches the table, marked "on
    D&D Beyond"; it's only heard (askdnd never writes into D&D Beyond's game log)."""
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
