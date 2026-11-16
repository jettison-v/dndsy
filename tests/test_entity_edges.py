"""World entries' own rules, the paths the other entry tests don't take (app/entities.py; the outside review's C12): what
each change refuses and why it says so, and a merge that brings everything over without a second copy of anything."""

import pytest
from sqlalchemy import select

from app import entities
from app.entities import EntityError
from app.importer import import_bundle
from app.models import Entity, EntityRelation, EventEntity, Fact, GameSession, Status, StoryEvent
from tests.table_setup import BUNDLE


@pytest.fixture
def main(db):
    import_bundle(db, {**BUNDLE, "sessions": [{"number": 1}]})
    return db.scalar(select(GameSession)).campaign_id


def made(db, main, name, kind="npc", **kw):
    return entities.create(db, main, kind, name, **kw)


@pytest.mark.parametrize("args, said", [
    (("npc", ""), "Enter a name."),
    (("npc", "x" * 201), "too long"),
    (("dragon", "Smaug"), "Pick what kind"),
    (("pc", "Someone"), "Manage › Characters"),
    (("npc", "Cole"), "already in the campaign record"),
])
def test_a_new_entry_says_what_it_needs(db, main, args, said):
    with pytest.raises(EntityError, match=said):
        entities.create(db, main, *args)


def test_a_quest_starts_open_and_a_hidden_one_is_a_draft(db, main):
    q = made(db, main, "Find the bell", "quest", published=False)
    assert q.quest_open is True and q.status == Status.DRAFT
    with pytest.raises(EntityError, match="Pick what kind"):
        entities.set_details(q, "dragon", "", True)
    with pytest.raises(EntityError, match="stay player characters"):
        entities.set_details(q, "pc", "", True)
    entities.set_details(q, "quest", "done", True)
    assert q.quest_open is False


def test_a_rename_keeps_the_old_name_once(db, main):
    e = made(db, main, "The Duke")
    for bad, said in (("  ", "Enter a name."), ("x" * 201, "too long"), ("The Duke", "already the name")):
        with pytest.raises(EntityError, match=said):
            entities.rename(e, bad)
    entities.rename(e, "Duke Arlo")
    entities.rename(e, "The Duke")  # (back again: its earlier name isn't added twice)
    entities.rename(e, "Arlo")
    assert sorted(a.alias for a in e.aliases) == ["Duke Arlo", "The Duke"]


def test_a_description_by_hand_and_its_undo(db, main):
    e = made(db, main, "The Duke", summary="Rules the harbor.")
    with pytest.raises(EntityError, match="Nothing changed"):
        entities.set_description(e, "Rules the harbor.")
    with pytest.raises(EntityError, match="4,000"):
        entities.set_description(e, "x" * 4001)
    entities.set_description(e, "Rules the harbor, badly.", by="DM")
    entities.undo_description(e)
    assert e.summary == "Rules the harbor." and e.summary_by == ""
    with pytest.raises(EntityError, match="Nothing to undo"):
        entities.undo_description(e)
    with pytest.raises(EntityError, match="no new description"):
        entities.accept_description(e, "  ")


def test_a_facts_steps_go_one_way(db, main):
    e = made(db, main, "The Duke")
    with pytest.raises(EntityError, match="Write the fact"):
        entities.add_fact(db, e, " ", {"email": "dm@example.com"})
    with pytest.raises(EntityError, match="4,000"):
        entities.add_fact(db, e, "x" * 4001, {"email": "dm@example.com"})
    f = Fact(entity_id=e.id, kind="addition", text="He has a twin.", author_name="DM", author_email="", status="pending")
    db.add(f)
    with pytest.raises(EntityError, match="Only facts on the page"):
        entities.done_fact(f)
    entities.reject_fact(f)
    with pytest.raises(EntityError, match="already decided"):
        entities.merge_fact(f)
    with pytest.raises(EntityError, match="already decided"):
        entities.reject_fact(f)
    entities.undo_fact(f)
    assert f.status == "pending"


def test_a_key_moment_by_hand_says_what_it_needs(db, main):
    e = made(db, main, "The Duke")
    session = db.scalar(select(GameSession))
    with pytest.raises(EntityError, match="Write what happened"):
        entities.add_moment(db, e, session.id, "reveal", "  ")
    with pytest.raises(EntityError, match="Pick the session"):
        entities.add_moment(db, e, 999999, "reveal", "He fled.")
    with pytest.raises(EntityError, match="kind of moment"):
        entities.add_moment(db, e, session.id, "nonsense", "He fled.")


def test_a_merge_brings_everything_over_once(db, main):
    """Its names, facts, relationships (one already there isn't doubled; one between the two goes), key moments (one
    already linked isn't doubled) and description (kept as a fact when the target has its own)."""
    keep = made(db, main, "Duke Arlo", summary="Rules the harbor.")
    dup = made(db, main, "The Duke", summary="A tall man.")
    other = made(db, main, "Womford", "place")
    with pytest.raises(EntityError, match="different entry"):
        entities.merge(db, keep, keep)
    db.add_all([EntityRelation(from_entity_id=dup.id, type="lives_in", to_entity_id=other.id),
                EntityRelation(from_entity_id=keep.id, type="lives_in", to_entity_id=other.id),
                EntityRelation(from_entity_id=dup.id, type="ally_of", to_entity_id=keep.id),
                Fact(entity_id=dup.id, kind="addition", text="He has a twin.", author_name="DM", author_email="", status="merged")])
    session = db.scalar(select(GameSession))
    both = StoryEvent(session_id=session.id, position=1, kind="reveal", text="The Duke is Arlo.", status=Status.PUBLISHED)
    only = StoryEvent(session_id=session.id, position=2, kind="reveal", text="The Duke fled.", status=Status.PUBLISHED)
    db.add_all([both, only])
    db.flush()
    db.add_all([EventEntity(event_id=both.id, entity_id=dup.id), EventEntity(event_id=both.id, entity_id=keep.id),
                EventEntity(event_id=only.id, entity_id=dup.id)])
    db.flush()
    entities.merge(db, dup, keep)
    assert db.get(Entity, dup.id) is None and "The Duke" in [a.alias for a in keep.aliases]
    rels = db.scalars(select(EntityRelation).where(EntityRelation.from_entity_id == keep.id)).all()
    assert sorted(r.type for r in rels) == ["lives_in"]  # (no second lives_in; no ally of itself)
    facts = {f.text for f in db.scalars(select(Fact).where(Fact.entity_id == keep.id))}
    assert "He has a twin." in facts and "From the merged entry The Duke: A tall man." in facts
    assert sorted(db.scalars(select(EventEntity.event_id).where(EventEntity.entity_id == keep.id))) == sorted([both.id, only.id])


def test_merging_into_an_entry_without_a_description_gives_it_this_one(db, main):
    keep = made(db, main, "Duke Arlo")
    dup = made(db, main, "The Duke", summary="A tall man.")
    entities.merge(db, dup, keep)
    assert keep.summary == "A tall man."


def test_a_quests_status_goes_to_claude_with_its_description(db, main):
    q = made(db, main, "Find the bell", "quest", summary="The bell was stolen.")
    words = entities.build_describe_messages(db, q)[0]["content"]
    text = words if isinstance(words, str) else " ".join(p.get("text", "") for p in words)
    assert "Quest status: open" in text
