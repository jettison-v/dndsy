"""Drops to 0 Hit Points and deaths, recorded from Nov 10 as askdnd reads sheets (app/downs.py; Brett: for Trophy Case)."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app import characters, downs
from app.importer import import_bundle
from app.models import CharacterDown
from tests.table_setup import BUNDLE, char, fake_fetch

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)

T0 = datetime(2026, 11, 10, 20, 0, tzinfo=UTC)


def sheet(hp, fails=0):
    return {"hit_points": {"current": hp, "max": 40}, "death_saves": {"success": 0, "fail": fails, "stable": False}}


def kept(db, ch):
    return [d.kind for d in db.scalars(select(CharacterDown).where(CharacterDown.character_id == ch.id).order_by(CharacterDown.at))]


def test_a_drop_to_zero_and_a_death_are_kept_once(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    assert downs.seen(db, cole, None, sheet(0), T0) == []  # (a first read: nothing to compare)
    assert downs.seen(db, cole, sheet(12), sheet(30), T0) == []
    assert downs.seen(db, cole, sheet(12), sheet(0), T0) == ["down"]
    db.flush()
    # D&D Beyond serving the copy from before the drop for a moment, then the new one again: the same drop
    assert downs.seen(db, cole, sheet(0), sheet(12), T0 + timedelta(seconds=20)) == []
    assert downs.seen(db, cole, sheet(12), sheet(0), T0 + timedelta(seconds=40)) == []
    assert downs.seen(db, cole, sheet(0, 2), sheet(0, 3), T0 + timedelta(minutes=1)) == ["dead"]
    db.flush()
    assert downs.seen(db, cole, sheet(5), sheet(0), T0 + timedelta(minutes=30)) == ["down"]  # (a later drop counts)
    db.flush()
    assert kept(db, cole) == ["down", "dead", "down"]


def test_a_read_that_shows_the_drop_records_it(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    first = characters.read(cole.ddb_id, fake_fetch)
    first.sheet = True
    characters.store(db, cole, first)
    db.flush()
    later = characters.read(cole.ddb_id, lambda i: {**fake_fetch(i), "removedHitPoints": 999})  # (every Hit Point gone)
    later.sheet, later.at = True, first.at + timedelta(minutes=5)
    assert later.summary["hit_points"]["current"] == 0
    characters.store(db, cole, later)
    db.flush()
    assert kept(db, cole) == ["down"]
