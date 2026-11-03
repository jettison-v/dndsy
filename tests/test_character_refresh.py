"""Characters from D&D Beyond: the last good copy, refreshing and linking (who may), the party's sync.
D&D Beyond is never called: refreshes use a fake fetch built from fixtures (tests/table_setup.py)."""

import json
import re

import pytest
from sqlalchemy import select

from app import characters, ddb
from app.importer import import_bundle
from app.models import CharacterSnapshot
from tests.table_setup import BUNDLE, card_on, char, down, fake_fetch

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)


def test_refresh_stores_a_sanitized_copy_and_summary(db):
    """A standing rule (CLAUDE.md › Privacy): a refresh stores D&D Beyond's copy without the private parts of the Notes
    tab."""
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    snap = characters.refresh(db, cole)
    assert snap.status == "ok" and snap.error == "" and snap.fetched_at is not None
    assert snap.raw["notes"] == {"backstory": "Raised by wolves near Womford."} and "PRIVATE ALLY NOTE" not in json.dumps(snap.raw)
    summary = characters.character_summary(cole)
    assert summary["name"] == "Cole Lockhard" and summary["armor_class"] == 16
    story = summary["story"]
    assert story["backstory"] == "Raised by wolves near Womford." and story["background"] == "Wayfarer"
    assert story["traits"] == [("Personality traits", "Slow to trust."), ("Ideals", "Charity."), ("Flaws", "Greed.")]
    assert ("Alignment", "Chaotic Good") in story["characteristics"] and ("Size", "Medium") in story["characteristics"]


def test_failed_refresh_keeps_the_last_good_copy(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    good = characters.refresh(db, cole)
    fetched_at, raw = good.fetched_at, dict(good.raw)
    bad = characters.refresh(db, cole, fetch=down)
    assert bad.id == good.id and bad.status == "error" and "Couldn't reach" in bad.error
    assert bad.fetched_at == fetched_at and bad.raw == raw and characters.character_summary(cole)["name"] == "Cole Lockhard"
    # a format change (unparseable data) also keeps the old copy
    characters.refresh(db, cole, fetch=lambda _id: {"name": "Cole", "inventory": [None]})
    assert cole.snapshot.status == "error" and "format" in cole.snapshot.error and cole.snapshot.raw == raw
    assert characters.refresh(db, cole).status == "ok"  # and it recovers
    assert db.scalar(select(CharacterSnapshot).where(CharacterSnapshot.character_id == cole.id)).error == ""


def test_never_fetched_or_unlinked(db):
    import_bundle(db, BUNDLE)
    trah = characters.refresh(db, char(db, "Trah"))
    assert trah.status == "error" and "private" in trah.error and trah.raw is None
    assert characters.character_summary(char(db, "Trah")) is None
    assert "No D&D Beyond link" in characters.refresh(db, char(db, "Big C")).error


def test_old_parser_summaries_are_reparsed(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    cole.snapshot.summary = {"parser_version": 0, "name": "stale"}
    assert characters.character_summary(cole)["name"] == "Cole Lockhard"


def test_a_new_parser_is_stored_once_and_an_unreadable_copy_keeps_its_summary(db):
    """Review, 2026-10-29: a page shouldn't parse a whole sheet on every load until the next refresh."""
    import_bundle(db, BUNDLE)
    cole, trah = char(db, "Cole"), char(db, "Trah")
    characters.refresh(db, cole)
    characters.refresh(db, trah)
    cole.snapshot.summary = {"parser_version": 0, "name": "stale"}
    trah.snapshot.summary, trah.snapshot.raw = {"parser_version": 0, "name": "kept"}, {"not": "a sheet"}
    db.commit()
    characters.reparse_old(db)
    db.expire_all()
    assert cole.snapshot.summary["parser_version"] == ddb.PARSER_VERSION and cole.snapshot.summary["name"] == "Cole Lockhard"
    assert trah.snapshot.summary["name"] == "kept"


def test_set_link_accepts_urls_and_clears_old_copy(db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    characters.set_ddb_link(db, cole, "https://www.dndbeyond.com/characters/75423618")
    assert cole.snapshot is not None  # same character: keep it
    characters.set_ddb_link(db, cole, "https://www.dndbeyond.com/characters/999")
    assert cole.ddb_id == "999" and cole.snapshot is None
    with pytest.raises(ddb.DdbError):
        characters.set_ddb_link(db, cole, "not a link")


def test_sheet_shows_quiet_note_when_latest_refresh_failed(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    characters.refresh(db, cole, fetch=down)
    page = player.get(f"/characters/{cole.id}").text
    assert "Heat Metal" in page and "last good copy" in page
    assert "showing the copy from" in player.get(f"/characters/{cole.id}/battle").text


def test_the_sync_reads_the_character_on_screen_first_and_is_throttled(player, db, monkeypatch):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    calls = []

    def counting(ddb_id):
        calls.append(ddb_id)
        return fake_fetch(ddb_id)

    monkeypatch.setattr(characters, "FETCH", counting)
    pill = player.post(f"/live/sync?c={cole.id}").text
    assert 'id="live-pill"' in pill and "<html" not in pill and calls == [cole.ddb_id, "135831636"]  # then the party (Trah)
    player.post(f"/live/sync?c={cole.id}")
    assert len(calls) == 2  # a second viewer moments later doesn't fetch again
    from datetime import timedelta

    cole.snapshot.attempted_at -= timedelta(minutes=3)
    player.post(f"/live/sync?c={cole.id}")
    assert calls.count(cole.ddb_id) == 2


def test_only_reviewers_can_refresh_or_link(player, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    assert player.post(f"/characters/{cole.id}/refresh", follow_redirects=False).status_code == 403
    assert player.post("/characters/refresh", follow_redirects=False).status_code == 403
    assert player.post(f"/characters/{cole.id}/link", data={"ddb_link": "1"}, follow_redirects=False).status_code == 403
    assert cole.snapshot is None


def test_dm_refreshes_one_and_all(dm, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    r = dm.post(f"/characters/{cole.id}/refresh", follow_redirects=False)
    assert r.status_code == 303 and cole.snapshot.status == "ok"
    page = dm.get(f"/characters/{cole.id}").text
    assert card_on(page) == "Updated from D&D Beyond" and "Refresh from D&amp;D Beyond" not in page  # refresh from Live
    page = dm.post("/characters/refresh").text  # follows the redirect back to /party
    assert char(db, "Trah").snapshot.status == "error"
    assert card_on(page) == {"text": "Updated 1 from D&D Beyond; couldn't update Trah", "kind": "warn"}


def test_admin_links_a_character(admin, db):
    import_bundle(db, BUNDLE)
    big_c = char(db, "Big C")
    admin.post(f"/characters/{big_c.id}/link", data={"ddb_link": "https://www.dndbeyond.com/characters/75423618"})
    assert big_c.ddb_id == "75423618" and big_c.snapshot.status == "ok"
    page = admin.post(f"/characters/{big_c.id}/link", data={"ddb_link": "nope"}).text  # back on Manage › Characters
    assert "Paste the character" in page and big_c.ddb_id == "75423618"


def test_refresh_buttons_show_that_they_are_working(dm, db):
    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    panel = dm.get("/live", params={"c": cole.id}).text
    refresh = re.findall(r'hx-post="/live/refresh[^"]*"[^>]*>', panel)
    assert len(refresh) == 2 and all('hx-disabled-elt="this"' in b for b in refresh)  # Refresh Cole, Refresh everyone: disabled while working
