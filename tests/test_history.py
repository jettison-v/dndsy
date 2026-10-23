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
    assert "Secret plan" not in dm.get("/c/main/manage/history").text  # the DM never sees players' notes, even in history
    assert "Secret plan" in admin.get("/c/main/manage/history?show=notes").text
    assert player.get("/c/main/manage/history").status_code == 403  # players don't open Manage
    admin.post(f"/manage/history/{rev.id}/restore")
    assert db.scalar(select(PlayerNote)).data == {"body": "Steal the egg."}


def test_history_filters_and_restore_point_at_history(db, cole, admin):
    """Brett, 2026-10-23: the filter buttons were broken (the page's "here" was the campaign, from every page's context)."""
    import re

    for url in ("/manage/history", "/c/main/manage/history"):
        page = admin.get(url, follow_redirects=True).text
        hrefs = re.findall(r'class="btn small[^"]*" href="([^"]+)"', page)
        assert hrefs and all(h.startswith(("/manage/history", "/c/main/manage/history")) for h in hrefs), hrefs
    assert 'action="/c/main/manage/history/' in admin.get("/c/main/manage/history").text or "Restore" not in admin.get("/c/main/manage/history").text


def test_import_page_lists_imports_with_undo(db, admin):
    batch = history.new_batch()
    import_bundle(db, STORY)
    entity(db, "Star Mounts").summary = "Changed."
    db.flush()
    import_bundle(db, STORY, batch=batch)
    page = admin.get("/manage/backups").text
    assert "Recent imports" in page and f'value="{batch}"' in page
    admin.post("/manage/history/undo-import", data={"batch": batch})
    assert entity(db, "Star Mounts").summary == "Changed."


def test_key_moments_names_and_relationships_are_kept_when_deleted(db):
    from app import relations, review
    from app.models import EntityAlias, EntityRelation, EventKind, GameSession, StoryEvent

    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "entities": [{"kind": "npc", "name": "Myna", "aliases": ["Mina"]}, {"kind": "pc", "name": "Trah"}],
                       "sessions": [{"number": 19, "title": "Journey"}]})
    myna, trah = entity(db, "Myna"), entity(db, "Trah")
    gs = db.scalar(select(GameSession))
    ev = StoryEvent(session_id=gs.id, position=1, kind=EventKind("reveal") if "reveal" in EventKind._value2member_map_ else list(EventKind)[0],
                    text="Trah's holy water frees Myna.")
    ev.entities = [myna, trah]
    db.add(ev)
    relations.add(db, trah, "allied_with" if "allied_with" in relations.TYPES else list(relations.TYPES)[0], myna, "")
    db.flush()

    ev.text = "Trah's holy water frees Myna from the cult."
    db.flush()
    assert db.scalar(select(Revision).where(Revision.table == "story_events", Revision.field == "text")).old == "Trah's holy water frees Myna."
    review.delete_event(db, gs, ev.id)
    db.delete(db.scalar(select(EntityAlias)))
    db.delete(db.scalar(select(EntityRelation)))
    db.flush()
    gone = {r.table: r for r in db.scalars(select(Revision).where(Revision.field == "deleted"))}
    assert {"story_events", "entity_aliases", "relationships"} <= set(gone)
    assert gone["story_events"].label == "Key moment, Session 19" and gone["entity_aliases"].label == "Other name of Myna"
    for table in ("story_events", "entity_aliases", "relationships"):
        assert history.can_restore(db, gone[table])
        history.restore(db, gone[table])
    back = db.scalar(select(StoryEvent))
    assert back.text == "Trah's holy water frees Myna from the cult." and {e.name for e in back.entities} == {"Myna", "Trah"}
    assert db.scalar(select(EntityAlias)).alias == "Mina" and db.scalar(select(EntityRelation)) is not None
