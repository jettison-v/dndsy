"""Version history (app/history.py): changes are recorded with who and how, can be
restored, a whole import can be undone, and players' notes stay private."""

import pytest
from sqlalchemy import select

from app import history
from app.importer import import_bundle
from app.models import Entity, PlayerNote, Revision
from tests.test_characters import BUNDLE, admin, char, characters, dm, no_network, owned_by, player  # noqa: F401

STORY = {"campaign": {"slug": "main", "name": "Main"},
         "entities": [{"kind": "place", "name": "Star Mounts", "summary": "Peaks in the High Forest."},
                      {"kind": "quest", "name": "Find Terra", "quest_open": True}]}


def entity(db, name) -> Entity:
    return db.scalar(select(Entity).where(Entity.name == name))


def test_edits_are_recorded_and_can_be_restored(db):
    import_bundle(db, STORY)
    mounts = entity(db, "Star Mounts")
    history.set_actor("dm@example.com")
    mounts.summary = "Cole's home region."
    db.flush()
    rev = db.scalar(select(Revision).where(Revision.field == "summary", Revision.source == "edit"))
    assert (rev.old, rev.new, rev.actor, rev.label) == ("Peaks in the High Forest.", "Cole's home region.", "dm@example.com", "Star Mounts (place)")
    history.restore(db, rev)
    assert mounts.summary == "Peaks in the High Forest."
    assert db.scalar(select(Revision).where(Revision.source == "restore")).new == "Peaks in the High Forest."


def test_a_whole_import_can_be_undone_except_what_changed_since(db):
    import_bundle(db, STORY)
    mounts, terra = entity(db, "Star Mounts"), entity(db, "Find Terra")
    mounts.summary, terra.quest_open = "Edited on beta.", False
    db.flush()
    batch = history.new_batch()
    import_bundle(db, STORY, batch=batch)  # the old file again: reverts both
    assert mounts.summary == "Peaks in the High Forest." and terra.quest_open is True
    terra.quest_open = None  # changed again after the import
    db.flush()
    done, skipped = history.undo_import(db, batch)
    assert (done, skipped) == (1, 1) and mounts.summary == "Edited on beta." and terra.quest_open is None


@pytest.fixture
def cole(db, player):
    import_bundle(db, BUNDLE)
    c = char(db, "Cole")
    characters.refresh(db, c)
    owned_by(db, c, "player@example.com")
    owned_by(db, char(db, "Trah"), "dm@example.com", is_dm=True)
    return c


def test_deleted_player_notes_come_back_and_stay_hidden_from_the_dm(db, cole, player, dm, admin):
    url = f"/characters/{cole.id}"
    player.post(f"{url}/notes", data={"kind": "general", "title": "Secret plan", "body": "Steal the egg."})
    note = db.scalar(select(PlayerNote))
    player.post(f"{url}/notes/{note.id}/delete")
    assert db.scalar(select(PlayerNote)) is None
    rev = db.scalar(select(Revision).where(Revision.field == "deleted"))
    assert rev.old["data"] == {"body": "Steal the egg."} and rev.character_id == cole.id
    assert "Secret plan" not in dm.get("/admin/history").text  # the DM never sees players' notes, even in history
    assert "Secret plan" in admin.get("/admin/history?show=notes").text
    assert player.get("/admin/history").status_code == 403  # players don't open Manage
    admin.post(f"/admin/history/{rev.id}/restore")
    assert db.scalar(select(PlayerNote)).data == {"body": "Steal the egg."}


def test_import_page_lists_imports_with_undo(db, admin):
    batch = history.new_batch()
    import_bundle(db, STORY)
    entity(db, "Star Mounts").summary = "Changed."
    db.flush()
    import_bundle(db, STORY, batch=batch)
    page = admin.get("/admin/import").text
    assert "Recent imports" in page and f'value="{batch}"' in page
    admin.post("/admin/history/undo-import", data={"batch": batch})
    assert entity(db, "Star Mounts").summary == "Changed."
