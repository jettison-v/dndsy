"""Sheets no extension watches are read by the server every 30 seconds while the bridge is awake (app/unwatched.py;
roadmap, Brett Nov 6), never a watched sheet, never a test copy, never while the bridge sleeps."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import characters, config, ddb_bridge, unwatched
from app.models import Character, ToolSetting
from tests.table_setup import char


def _reads(monkeypatch, sheet):
    seen = []
    real = characters.FETCH
    monkeypatch.setattr(characters, "FETCH", lambda ddb_id: seen.append(ddb_id) or real(ddb_id))
    return seen


def _old(db):  # (every copy read long enough ago to read again)
    for ch in db.scalars(select(Character)):
        if ch.snapshot is not None:
            ch.snapshot.attempted_at = datetime.now(UTC) - timedelta(minutes=5)
    db.flush()


def test_an_unwatched_sheet_is_read_and_a_watched_one_is_left_to_its_extension(db, sheet, monkeypatch):
    cole, trah = char(db, "Cole"), char(db, "Trah")
    _old(db)
    seen = _reads(monkeypatch, sheet)
    assert unwatched.tick(db) == []  # every sheet open with the extension: nothing to read
    trah.sheet_heard_at = None  # (Trah's player is on the phone app)
    db.flush()
    assert unwatched.tick(db) == [trah.id] and seen == [trah.ddb_id]
    assert unwatched.tick(db) == []  # (read a moment ago: not again until MIN_AGE)
    cole.sheet_heard_at = datetime.now(UTC) - timedelta(minutes=5)  # Cole's sheet closed
    _old(db)
    assert sorted(unwatched.tick(db)) == sorted([cole.id, trah.id])


def test_nothing_is_read_while_the_bridge_sleeps_or_where_it_doesnt_run(db, sheet, monkeypatch):
    for ch in db.scalars(select(Character)):
        ch.sheet_heard_at = None
    _old(db)
    db.delete(db.get(ToolSetting, ddb_bridge.AWAKE_KEY))
    db.flush()
    assert not ddb_bridge.awake(db)["awake"] and unwatched.tick(db) == []
    ddb_bridge.active(db)
    monkeypatch.setattr(config, "DDB_BRIDGE", False)
    assert unwatched.tick(db) == []


def test_a_test_copy_and_a_campaign_without_sync_are_never_read(db, sheet):
    from app.models import Campaign

    cole = char(db, "Cole")
    for ch in db.scalars(select(Character)):
        ch.sheet_heard_at = None
    copy = Character(name="Cole (test)", ddb_id=cole.ddb_id, copy_of_id=cole.id)
    db.add(copy)
    db.flush()
    assert copy.id not in [c.id for c in unwatched.unwatched(db)]
    db.get(Campaign, cole.campaign_id).vtt_pieces = []
    db.flush()
    assert unwatched.unwatched(db) == []


def test_one_copy_of_the_app_reads_at_a_time(monkeypatch):
    """Another copy holding the lock: this one reads nothing this tick (two copies never double the reads)."""
    from sqlalchemy import func

    from app.db import engine

    monkeypatch.setattr(unwatched, "tick", lambda db: ["read"])
    with engine.connect() as other:
        assert other.execute(select(func.pg_try_advisory_lock(unwatched.LOCK))).scalar()
        try:
            assert unwatched.run_once() == []
        finally:
            other.execute(select(func.pg_advisory_unlock(unwatched.LOCK)))
            other.commit()
    assert unwatched.run_once() == ["read"]


def test_a_sheet_read_from_itself_a_moment_ago_is_left_alone(db, sheet):
    """Closed a moment ago (or reached through the DM's browser), its copy came from the sheet itself: D&D Beyond's
    public copy can be behind it for minutes, so it isn't read here until PUBLIC_TRAILS has passed (Nov 8)."""
    trah = char(db, "Trah")
    trah.sheet_heard_at = None
    characters.refresh(db, trah)  # (a copy to keep)
    _old(db)
    trah.snapshot.sheet_at = datetime.now(UTC) - timedelta(minutes=1)
    db.flush()
    assert trah.id not in [c.id for c in unwatched.unwatched(db)]
    trah.snapshot.sheet_at -= characters.PUBLIC_TRAILS
    db.flush()
    assert trah.id in [c.id for c in unwatched.unwatched(db)]
