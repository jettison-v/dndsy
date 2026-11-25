"""Version history (app/history.py): changes are recorded with who and how, can be
restored, a whole import can be undone, and players' notes stay private."""

import pytest
from sqlalchemy import select

from app import characters, history
from app.importer import import_bundle
from app.models import Entity, PlayerNote, Revision
from tests.table_setup import BUNDLE, char, owned_by

pytestmark = pytest.mark.usefixtures("no_network")  # D&D Beyond is never called (tests/conftest.py)

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
    """A standing rule (CLAUDE.md › Privacy): character notes are visible to players but never the DM. Restoring one
    from Manage › History keeps it that way."""
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
        hrefs = re.findall(r'<a [^>]*href="([^"]+)"[^>]*data-filter=', page)  # (each filter by its marker, whatever its look)
        assert hrefs and all(h.startswith(("/manage/history", "/c/main/manage/history")) for h in hrefs), hrefs
    page = admin.get("/c/main/manage/history").text  # (Restore is in a row's window now: HI2)
    for ids in re.findall(r'data-modal-url="/c/main/manage/history/window\?ids=([0-9,]+)"', page)[:3]:
        window = admin.get(f"/c/main/manage/history/window?ids={ids}").text
        assert 'action="/c/main/manage/history/' in window or "Restore" not in window


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
    ev = StoryEvent(session_id=gs.id, position=1, kind=EventKind("reveal") if "reveal" in EventKind._value2member_map_ else next(iter(EventKind)),
                    text="Trah's holy water frees Myna.")
    ev.entities = [myna, trah]
    db.add(ev)
    relations.add(db, trah, "allied_with" if "allied_with" in relations.TYPES else next(iter(relations.TYPES)), myna, "")
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


def test_history_groups_runs_and_batches_and_opens_each_in_its_window(db, admin, player):
    """Brett's picks HI1, HI2 and AH1 on docs/mockups/backstage-round-3/ (Nov 25): the same field of one thing changed
    again and again is one row (changed N times, now …); the same change to many things together is one row with its
    count; a row opens its window, before and after, with Restore; a player never opens it."""
    from datetime import UTC, datetime, timedelta

    from app.history_pages import group_changes

    now = datetime.now(UTC)

    def item(i, table="entities", row=1, field="status", new="published", actor="a@example.com", batch=None, ago=0):
        r = Revision(id=i, table=table, row_id=row, label="X", field=field, old="draft", new=new, actor=actor, batch=batch,
                     created_at=now - timedelta(seconds=ago))
        return {"r": r, "field": history.FIELD_LABELS.get(field, field), "source": "", "subject": f"Thing {row}", "who": "A",
                "old": "draft", "new": new}

    runs = group_changes([item(5, row=1, ago=0), item(4, row=1, ago=60), item(3, row=1, ago=120)])
    assert len(runs) == 1 and runs[0]["kind"] == "run" and runs[0]["run"]["n"] == 3 and runs[0]["ids"] == [5, 4, 3]
    alike = group_changes([item(i, table="story_events", row=i, ago=i) for i in range(10, 0, -1)])
    assert len(alike) == 1 and alike[0]["kind"] == "alike" and alike[0]["title"].startswith("10 key moments")
    apart = group_changes([item(2, row=1), item(1, row=2, ago=600)])  # (ten minutes apart: two rows)
    assert [e["kind"] for e in apart] == ["one", "one"]
    imp = group_changes([item(2, row=1, batch="b1"), item(1, row=2, field="name", batch="b1")])
    assert len(imp) == 1 and imp[0]["kind"] == "batch"

    import_bundle(db, BUNDLE)
    e = entity(db, "Star Mounts") if db.scalar(select(Entity).where(Entity.name == "Star Mounts")) else db.scalar(select(Entity))
    e.summary = "Changed once."
    db.flush()
    rev = db.scalar(select(Revision).where(Revision.table == "entities").order_by(Revision.id.desc()))
    page = admin.get("/c/main/manage/history").text
    assert f"/c/main/manage/history/window?ids={rev.id}" in page
    window = admin.get(f"/c/main/manage/history/window?ids={rev.id}").text
    assert "Before" in window and "After" in window and "Changed once." in window
    assert player.get(f"/c/main/manage/history/window?ids={rev.id}", follow_redirects=False).status_code in (303, 403)
    assert "Changed once." not in admin.get(f"/manage/history/window?ids={rev.id}").text  # (askdnd's window: no campaign's changes)
