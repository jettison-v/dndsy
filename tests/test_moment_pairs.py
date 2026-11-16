"""The one-time clean-up of key moments a redraft doubled (scripts/moment_pairs.py; Nov 16, the UI/UX review): Claude's
published moments from an older draft than the session's newest go, except one per entry that nothing else links; a
person's moments, drafts waiting for review, moments a waiting redraft replaces, sessions drafted once and a session
cleaned up by hand are never touched; nothing it prints is a moment's words. Also the migration that marks a person's
moments and a waiting redraft's (by_hand, superseded) for the moments already there."""

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from app.models import Campaign, Entity, GameSession, Recap, Revision, Status, StoryEvent
from scripts import moment_pairs

T0 = datetime(2026, 11, 6, 17, 0, tzinfo=UTC)
T1, T2, T3 = T0 + timedelta(days=1), T0 + timedelta(days=2), T0 + timedelta(days=3)
WORDS = ("Old", "New", "storm", "harbor", "quest.", "hand", "Drafted", "redraft")


def moment(db, s, at, words, *, status=Status.PUBLISHED, links=(), by_hand=False, superseded=False, position=1):
    ev = StoryEvent(session_id=s.id, position=position, kind="event", text=words, status=status, by_hand=by_hand,
                    superseded=superseded, created_at=at)
    ev.entities = list(links)
    db.add(ev)
    db.flush()
    return ev


def recaps(db, s, *times):
    for version, at in enumerate(times, start=1):
        db.add(Recap(session_id=s.id, version=version, body="A night at sea.", author="ai", status=Status.DRAFT, created_at=at))
    db.flush()


def campaign(db):
    c = Campaign(name="Test", slug="test")
    db.add(c)
    db.flush()
    quest = Entity(campaign_id=c.id, kind="quest", name="Ring the Bell", status=Status.PUBLISHED)
    harbor = Entity(campaign_id=c.id, kind="place", name="Grey Harbor", status=Status.PUBLISHED)
    db.add_all([quest, harbor])
    db.flush()
    return c, quest, harbor


def session_in(db, c, number=None):
    s = GameSession(campaign_id=c.id, source="transcript", number=number)
    db.add(s)
    db.flush()
    return s


def test_older_drafts_moments_go_but_each_entry_keeps_its_newest_link(db):
    c, quest, harbor = campaign(db)
    twice, once, waiting = session_in(db, c), session_in(db, c, 3), session_in(db, c, 4)
    recaps(db, twice, T0, T1, T2)
    recaps(db, once, T1)
    recaps(db, waiting, T1, T3)
    oldest_harbor = moment(db, twice, T0, "Oldest: they sailed from the harbor.", links=[harbor])
    old_quest = moment(db, twice, T1, "Old: the party took the quest.", links=[quest])
    old_harbor = moment(db, twice, T1, "Old: they sailed from the harbor.", links=[harbor], position=2)  # (no newer one links it)
    old_plain = moment(db, twice, T1, "Old: a storm.", position=3)
    new_quest = moment(db, twice, T2, "New: the party took the quest.", links=[quest])
    new_plain = moment(db, twice, T2, "New: a storm.", position=2)
    by_hand_then = moment(db, twice, T1, "Written by hand at the draft's own time.", by_hand=True, position=4)
    hand = moment(db, twice, T1 + timedelta(hours=1), "Written by hand.", by_hand=True, position=5)
    single = moment(db, once, T1, "Drafted once.")
    replaced = moment(db, waiting, T1, "Replaced when the redraft is published.", superseded=True)
    replaced_too = moment(db, waiting, T0, "Replaced too.", superseded=True)
    redraft = moment(db, waiting, T3, "A redraft waiting for review.", status=Status.DRAFT)

    lines = []
    plan = moment_pairs.find(db.connection())
    moment_pairs.report(plan, out=lines.append)
    assert sorted(r["id"] for r in plan.remove) == sorted([oldest_harbor.id, old_quest.id, old_plain.id])
    assert [r["id"] for r in plan.kept_for_links] == [old_harbor.id]  # (the newest of the two linking the harbor)
    printed = "\n".join(lines)
    assert f"Session {twice.id} (number -): the newest draft's 2 moments stay; remove 3 of 4 older, keep 1" in printed
    assert "Total: 3 to remove, 1 kept as an entry's only link, 0 sessions skipped." in printed
    assert not any(word in printed for word in WORDS)  # (counts, never words)
    assert db.scalar(select(func.count()).select_from(StoryEvent)) == 12  # (finding changes nothing)

    logged = []
    assert moment_pairs.apply(db, plan, out=logged.append) == 3
    db.expire_all()
    assert set(db.scalars(select(StoryEvent.id))) == {old_harbor.id, new_quest.id, new_plain.id, by_hand_then.id, hand.id,
                                                       single.id, replaced.id, replaced_too.id, redraft.id}
    assert all(str(r["id"]) in "\n".join(logged) for r in plan.remove) and not any(w in "\n".join(logged) for w in WORDS)
    kept = db.scalars(select(Revision).where(Revision.table == "story_events", Revision.field == "deleted")).all()
    assert sorted(r.row_id for r in kept) == sorted(r["id"] for r in plan.remove) and {r.source for r in kept} == {"cleanup"}
    assert next(r for r in kept if r.row_id == old_quest.id).old["entity_ids"] == [quest.id]  # (history can bring it back, linked)

    again = moment_pairs.find(db.connection())
    assert again.remove == [] and [r["id"] for r in again.kept_for_links] == [old_harbor.id]


def test_a_session_cleaned_up_by_hand_is_reported_and_left_alone(db):
    c, quest, harbor = campaign(db)
    s = session_in(db, c, 7)
    recaps(db, s, T1, T2)
    older = [moment(db, s, T1, f"Old moment {i}.", position=i) for i in range(1, 5)]
    moment(db, s, T2, "The one left of the new draft.")
    lines = []
    plan = moment_pairs.find(db.connection())
    moment_pairs.report(plan, out=lines.append)
    assert plan.remove == [] and plan.kept_for_links == [] and len(older) == 4
    assert lines[0] == (f"Session {s.id} (number 7): skipped, its newest draft has 1 moments beside 4 in an older one "
                        "(cleaned up by hand?); nothing removed, 4 older moments left.")
    assert lines[-1] == "Total: 0 to remove, 0 kept as an entry's only link, 1 session skipped."


def test_nothing_doubled_says_so(db):
    lines = []
    moment_pairs.report(moment_pairs.find(db.connection()), out=lines.append)
    assert lines == ["No doubled key moments."]


def test_the_address_given_works_as_railway_writes_it(monkeypatch):
    assert moment_pairs.database_url(["--url", "postgresql://localhost/somewhere"]) == "postgresql+psycopg://localhost/somewhere"
    for bare in (["--url"], ["--url", "--apply"]):
        with pytest.raises(SystemExit, match="--url needs the database's address"):
            moment_pairs.database_url(bare)


def migration():
    path = next(Path(__file__).resolve().parent.parent.glob("migrations/versions/*_moments_by_hand.py"))
    spec = importlib.util.spec_from_file_location("moments_by_hand", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_marks_a_persons_moments_and_a_waiting_redrafts(db):
    """Claude's moments share their recap's created_at; any other, or one a person reworded, is a person's. In a session
    with Claude's drafts waiting, Claude's published moments are the ones that redraft replaces."""
    c, quest, harbor = campaign(db)
    done, mid = session_in(db, c, 1), session_in(db, c, 2)
    recaps(db, done, T1)
    recaps(db, mid, T1, T2)
    claudes = moment(db, done, T1, "Claude's.")
    reworded = moment(db, done, T1, "Claude's, reworded by the DM.", position=2)
    added = moment(db, done, T1 + timedelta(minutes=5), "Added on the review page.", position=3)
    restored_by_system = moment(db, done, T1, "Claude's, its status changed by publishing.", position=4)
    db.add_all([Revision(table="story_events", row_id=reworded.id, field="text", old="x", new="y", actor="dm@example.com"),
                Revision(table="story_events", row_id=restored_by_system.id, field="status", old="draft", new="published",
                         actor="dm@example.com")])
    old_published = moment(db, mid, T1, "Published from the first draft.")
    redraft = moment(db, mid, T2, "The redraft's.", status=Status.DRAFT)
    mid_hand = moment(db, mid, T1 + timedelta(minutes=5), "The DM's, published.", position=2)
    m = migration()
    db.execute(text(m.BY_HAND))
    db.execute(text(m.SUPERSEDED))
    db.expire_all()
    marks = {ev.id: (ev.by_hand, ev.superseded) for ev in db.scalars(select(StoryEvent))}
    assert marks == {claudes.id: (False, False), reworded.id: (True, False), added.id: (True, False),
                     restored_by_system.id: (False, False), old_published.id: (False, True), redraft.id: (False, False),
                     mid_hand.id: (True, False)}
