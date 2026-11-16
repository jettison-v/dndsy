"""The one-time clean-up of key moments a redraft doubled (scripts/moment_pairs.py; Nov 16, the UI/UX review): Claude's
published moments from an older draft than the session's newest go, unless one is the only link to an entry; a person's
moments, drafts waiting for review and sessions drafted once are never touched; nothing it prints is a moment's words."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import Campaign, Entity, GameSession, Recap, Revision, Status, StoryEvent
from scripts import moment_pairs

T1 = datetime(2026, 11, 9, 3, 45, tzinfo=UTC)
T2, T3 = T1 + timedelta(hours=13), T1 + timedelta(days=2)


def moment(db, s, at, text, *, status=Status.PUBLISHED, links=(), by_hand=False, position=1):
    ev = StoryEvent(session_id=s.id, position=position, kind="event", text=text, status=status, by_hand=by_hand, created_at=at)
    ev.entities = list(links)
    db.add(ev)
    db.flush()
    return ev


def recap(db, s, version, at, author="ai"):
    db.add(Recap(session_id=s.id, version=version, body="A night at sea.", author=author, status=Status.DRAFT, created_at=at))


def test_older_drafts_moments_go_unless_one_is_an_entrys_only_link(db):
    c = Campaign(name="Test", slug="test")
    db.add(c)
    db.flush()
    quest = Entity(campaign_id=c.id, kind="quest", name="Ring the Bell", status=Status.PUBLISHED)
    harbor = Entity(campaign_id=c.id, kind="place", name="Grey Harbor", status=Status.PUBLISHED)
    twice, once = GameSession(campaign_id=c.id, source="transcript"), GameSession(campaign_id=c.id, source="transcript", number=3)
    db.add_all([quest, harbor, twice, once])
    db.flush()
    recap(db, twice, 1, T1)
    recap(db, twice, 2, T2)
    recap(db, twice, 3, T3)
    recap(db, once, 1, T1)
    old_quest = moment(db, twice, T1, "Old: the party took the quest.", links=[quest])
    old_harbor = moment(db, twice, T1, "Old: they sailed from the harbor.", links=[harbor])  # (no newer moment links it)
    old_plain = moment(db, twice, T1, "Old: a storm.")
    new_quest = moment(db, twice, T2, "New: the party took the quest.", links=[quest])
    new_plain = moment(db, twice, T2, "New: a storm.")
    hand = moment(db, twice, T1 + timedelta(hours=1), "Written by the DM.", by_hand=True)
    waiting = moment(db, twice, T3, "A redraft waiting for review.", status=Status.DRAFT)
    single = moment(db, once, T1, "Drafted once.")

    lines = []
    plan = moment_pairs.find(db.connection())
    moment_pairs.report(plan, out=lines.append)
    assert sorted(r["id"] for r in plan.remove) == sorted([old_quest.id, old_plain.id])
    assert [r["id"] for r in plan.kept_for_links] == [old_harbor.id]
    printed = "\n".join(lines)
    assert "Total: 2 to remove, 1 kept" in printed
    assert not any(word in printed for word in ("Old:", "New:", "storm", "harbor", "quest.", "DM"))  # (counts, never words)
    assert db.scalar(select(func.count()).select_from(StoryEvent)) == 8  # (finding changes nothing)

    logged = []
    assert moment_pairs.apply(db, plan, out=logged.append) == 2
    db.expire_all()
    left = set(db.scalars(select(StoryEvent.id)))
    assert left == {old_harbor.id, new_quest.id, new_plain.id, hand.id, waiting.id, single.id}
    assert all(str(r["id"]) in "\n".join(logged) for r in plan.remove) and "storm" not in "\n".join(logged)
    kept = db.scalars(select(Revision).where(Revision.table == "story_events", Revision.field == "deleted")).all()
    assert sorted(r.row_id for r in kept) == sorted([old_quest.id, old_plain.id]) and {r.source for r in kept} == {"cleanup"}
    assert next(r for r in kept if r.row_id == old_quest.id).old["entity_ids"] == [quest.id]  # (history can bring it back, linked)

    again = moment_pairs.find(db.connection())
    assert again.remove == [] and [r["id"] for r in again.kept_for_links] == [old_harbor.id]


def test_nothing_doubled_says_so(db):
    lines = []
    moment_pairs.report(moment_pairs.find(db.connection()), out=lines.append)
    assert lines == ["No doubled key moments."]
