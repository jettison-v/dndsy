"""Reading sheets through the jobs queue (app/sheet_reads.py; Roadmap item 43, step 4, Brett's pick LB2, Nov 25): one
read per character waiting or running, a press first in line and answered while it waits, a failure tried again, and
D&D Beyond given a second between reads and a rest after it fails."""

import contextlib
import threading
from datetime import timedelta

from sqlalchemy import text

from app import characters, jobs, sheet_reads, worker
from app.importer import import_bundle
from tests.table_setup import BUNDLE, char, down, fake_fetch, run_reads


def _jobs(db):
    return db.execute(text("SELECT id, state, priority, error, payload FROM jobs WHERE kind = 'ddb_refresh' ORDER BY id")).all()


def test_one_read_per_character_however_many_ask(db, monkeypatch):
    import_bundle(db, BUNDLE)
    cole, trah = char(db, "Cole"), char(db, "Trah")
    a = sheet_reads.request_read(db, cole, min_age=timedelta(0))
    assert sheet_reads.request_read(db, cole, min_age=timedelta(0), priority=sheet_reads.PRESS) == a  # (moved up, not doubled)
    sheet_reads.request_read(db, trah, min_age=timedelta(0), priority=sheet_reads.UNWATCHED)
    rows = _jobs(db)
    assert [(r.payload["character_id"], r.priority) for r in rows] == [(cole.id, sheet_reads.PRESS), (trah.id, sheet_reads.UNWATCHED)]
    monkeypatch.setattr(characters, "FETCH", fake_fetch)
    run_reads(db)
    assert _jobs(db)[0].state == "done" and cole.snapshot.status == "ok"  # (the press first; Trah's stand-in sheet is private)
    assert sheet_reads.request_read(db, cole, min_age=timedelta(minutes=2)) is None  # (read a moment ago)


def test_a_press_is_answered_while_it_waits(db, monkeypatch):
    """Refresh now: first in line, and its message says what happened (here no lane serves the queue, so the request
    runs it, as tests and a copy started without lanes do)."""
    import_bundle(db, BUNDLE)
    cole, trah = char(db, "Cole"), char(db, "Trah")
    sheet_reads.request_read(db, trah, min_age=timedelta(0), priority=sheet_reads.UNWATCHED)
    monkeypatch.setattr(characters, "FETCH", fake_fetch)
    assert sheet_reads.read_now(db, [cole]) == {cole.id: "done"} and cole.snapshot.status == "ok"
    monkeypatch.setattr(characters, "FETCH", down)
    assert sheet_reads.read_now(db, [cole]) == {cole.id: "failed"}
    row = next(r for r in _jobs(db) if r.payload["character_id"] == cole.id and r.state != "done")
    assert row.state == "queued" and row.error  # (tried again by itself after its backoff; the last good copy stays)
    assert cole.snapshot.status == "error" and cole.snapshot.summary


def test_a_press_on_a_read_trying_again_asks_afresh_now(db, monkeypatch):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    monkeypatch.setattr(characters, "FETCH", down)
    sheet_reads.read_now(db, [cole])
    db.execute(text("UPDATE jobs SET run_at = now() + interval '1 minute' WHERE kind = 'ddb_refresh' AND state = 'queued'"))
    monkeypatch.setattr(characters, "FETCH", fake_fetch)
    assert sheet_reads.read_now(db, [cole]) == {cole.id: "done"}


def test_unlinked_characters_are_not_asked_for(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    cole.ddb_id = None
    db.flush()
    assert sheet_reads.request_read(db, cole, min_age=timedelta(0)) is None and sheet_reads.read_now(db, [cole]) == {cole.id: "skipped"}


def test_the_lane_gives_dnd_beyond_a_second_and_a_rest_after_it_fails(db, monkeypatch):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    lane = worker.Lane(sheet_reads.QUEUE, lambda: contextlib.nullcontext(db), threading.Event(), jobs.me())
    monkeypatch.setattr(characters, "FETCH", fake_fetch)
    sheet_reads.request_read(db, cole, min_age=timedelta(0))
    assert lane.run_once() and lane.pause() == 1.0
    monkeypatch.setattr(characters, "FETCH", down)
    sheet_reads.request_read(db, cole, min_age=timedelta(0))
    assert lane.run_once() and lane.pause() == 30.0
    assert "Traceback" not in _jobs(db)[-1].error  # (D&D Beyond's own words, no stack trace)


def test_a_lane_says_which_queue_this_copy_serves(monkeypatch):
    stop = threading.Event()
    stop.set()
    lane = worker.Lane("ddb", lambda: None, stop, "w")
    assert not worker.serving("ddb")
    seen = []
    monkeypatch.setattr(lane, "run_once", lambda: seen.append(worker.serving("ddb")) or False)
    stop.clear()
    lane.wake.set()
    t = threading.Thread(target=lambda: (lane.loop()))
    monkeypatch.setattr(worker, "POLL_SECONDS", 0.01)
    t.start()
    while not seen:
        pass
    stop.set()
    lane.wake.set()
    t.join(2)
    assert seen[0] is True and not worker.serving("ddb")
