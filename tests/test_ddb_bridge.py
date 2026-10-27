"""The D&D Beyond bridge, a local proof (app/ddb_bridge.py): middleware that repairs itself. D&D Beyond is never called:
a fake sheet stands in, and each test changes it the way the extension, a player or a misbehaving D&D Beyond would."""

import copy

import pytest

from app import characters, config, ddb, ddb_bridge
from app.importer import import_bundle
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
    """What the extension's requests do to the sheet (it skips a field already at its new value)."""
    for op in batch["ops"]:
        if op["path"] == ddb_bridge.HP_PATH:
            data["removedHitPoints"], data["temporaryHitPoints"] = op["body"]["removedHitPoints"], op["body"]["temporaryHitPoints"]
        else:
            next(i for i in data["inventory"] if i["id"] == op["body"]["id"])["quantity"] = op["body"]["quantity"]


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
