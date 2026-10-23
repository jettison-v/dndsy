"""Characters separate from campaigns (data organization step 1): a character has its own name and data;
which campaign it's in, its story page there and the DM's Wild Shape ruling are a CampaignCharacter."""

import subprocess
from datetime import date

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app import characters, entities, history
from app.importer import import_bundle
from app.models import CampaignCharacter, Character, Entity, EntityKind, PlayerNote, Revision
from tests.test_characters import BUNDLE, admin, fake_fetch  # noqa: F401


def cole(db) -> Character:
    return next(c for c in db.scalars(select(Character)) if c.name == "Cole")


def test_import_puts_each_character_in_its_campaign(db):
    import_bundle(db, BUNDLE)
    ch = cole(db)
    m = ch.membership
    assert m.entity.name == "Cole" and m.entity.kind == EntityKind.PC and m.left_on is None
    assert ch.entity is m.entity and ch.campaign_id == m.campaign_id == m.entity.campaign_id
    assert [c.name for c in characters.campaign_characters(db, ch.campaign_id)] == ["Big C", "Cole", "Trah"]
    assert characters.for_entity(db, m.entity_id) is ch


def test_a_character_that_left_keeps_its_story_but_is_not_listed(db):
    import_bundle(db, BUNDLE)
    ch = cole(db)
    m, campaign_id = ch.membership, ch.campaign_id
    m.left_on = date(2026, 10, 22)
    db.flush()
    assert ch.membership is None and ch.entity is None and ch.wild_shape_keep is None
    assert "Cole" not in [c.name for c in characters.campaign_characters(db, campaign_id)]
    assert db.get(Entity, m.entity_id) is not None  # its story page stays part of the campaign's history
    assert characters.for_entity(db, m.entity_id) is ch


def test_one_campaign_at_a_time(db):
    import_bundle(db, BUNDLE)
    ch = cole(db)
    other = Entity(campaign_id=ch.campaign_id, kind=EntityKind.PC, name="Cole again")
    db.add(other)
    db.flush()
    with pytest.raises(ValueError, match="already in a campaign"):
        characters.join(db, ch, other)
    db.add(CampaignCharacter(campaign_id=ch.campaign_id, character_id=ch.id, entity_id=other.id))
    with pytest.raises(IntegrityError):
        db.flush()


def test_renaming_the_story_page_renames_the_character(db):
    import_bundle(db, BUNDLE)
    ch = cole(db)
    entities.rename(ch.entity, "No Name")
    db.flush()
    assert ch.name == "No Name" and "Cole" in [a.alias for a in ch.entity.aliases]


def test_wild_shape_keeps_belong_to_the_campaign_and_keep_their_history(db, admin):
    import_bundle(db, BUNDLE)
    ch = cole(db)
    ch.wild_shape_keep = ["unarmored-movement"]
    db.flush()
    assert ch.membership.wild_shape_keep == ["unarmored-movement"]
    rev = db.scalar(select(Revision).where(Revision.field == "wild_shape_keep"))
    assert rev.table == "campaign_characters" and rev.row_id == ch.membership.id and rev.label == "Character: Cole"
    db.commit()
    assert "Kept in Wild Shape" in admin.get("/c/main/manage/history?show=characters").text
    history.restore(db, rev)
    assert ch.wild_shape_keep is None


def test_refresh_keeps_the_d_and_d_beyond_campaign(db):
    import_bundle(db, BUNDLE)
    ch = cole(db)
    characters.refresh(db, ch, lambda _id: {**fake_fetch(_id), "campaign": {"id": 3005233, "name": "The Adventure Begins"}})
    assert ch.ddb_campaign_id == "3005233"
    characters.refresh(db, ch, fake_fetch)
    assert ch.ddb_campaign_id is None  # left its D&D Beyond campaign


def test_personal_quests_belong_to_their_campaign(db):
    bundle = {**BUNDLE, "player_notes": [
        {"character": "Cole", "kind": "quest", "title": "Find my sister", "data": {}},
        {"character": "Cole", "kind": "combo", "title": "Moonbeam then dodge", "data": {}},
    ]}
    import_bundle(db, bundle)
    ch = cole(db)
    notes = {n.kind: n for n in db.scalars(select(PlayerNote).where(PlayerNote.character_id == ch.id))}
    assert notes["quest"].campaign_id == ch.campaign_id
    assert notes["combo"].campaign_id is None  # travels with the character


def test_migration_copies_each_character_into_its_campaign(db_engine):
    """The step 1 migration on data shaped like production's, then back down and up again."""
    url = db_engine.url.render_as_string(hide_password=False)
    env = {"DATABASE_URL": url, "PATH": __import__("os").environ["PATH"]}
    from app.db import Base

    def alembic(*args):
        r = subprocess.run(["alembic", *args], env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    Base.metadata.drop_all(db_engine)
    try:
        alembic("upgrade", "8f4a6b0c3d59")
        with db_engine.begin() as c:
            c.execute(text("INSERT INTO campaigns (id, name, slug, dm_name) VALUES (1, 'Main', 'main', 'Mary')"))
            c.execute(text("INSERT INTO entities (id, campaign_id, kind, name, summary, status, summary_by) VALUES "
                           "(10, 1, 'pc', 'Cole', '', 'published', ''), (11, 1, 'pc', 'Trah', '', 'published', '')"))
            c.execute(text("INSERT INTO characters (id, entity_id, ddb_id, wild_shape_keep) VALUES "
                           "(1, 10, '75423618', '[\"unarmored-movement\"]'), (2, 11, NULL, NULL)"))
            c.execute(text("""INSERT INTO character_snapshots (character_id, raw, summary, status, error)
                              VALUES (1, '{"campaign": {"id": 3005233}}', '{}', 'ok', '')"""))
            c.execute(text("INSERT INTO player_notes (character_id, kind, title, status, data, position) VALUES "
                           "(1, 'quest', 'Find my sister', 'open', '{}', 1), (1, 'combo', 'Moonbeam', '', '{}', 2)"))
            c.execute(text("""INSERT INTO revisions ("table", row_id, label, field, old, new, actor, source)
                              VALUES ('characters', 1, 'Character: Cole', 'wild_shape_keep', NULL, '["unarmored-movement"]',
                                      'brett@example.com', 'edit')"""))
        alembic("upgrade", "head")
        with db_engine.connect() as c:
            rows = c.execute(text("SELECT character_id, campaign_id, entity_id, left_on, wild_shape_keep "
                                  "FROM campaign_characters ORDER BY character_id")).all()
            assert rows == [(1, 1, 10, None, ["unarmored-movement"]), (2, 1, 11, None, None)]
            assert c.execute(text("SELECT name, ddb_campaign_id FROM characters ORDER BY id")).all() == [
                ("Cole", "3005233"), ("Trah", None)]
            assert c.execute(text("SELECT ddb_campaign_id FROM campaigns")).scalar() == "3005233"
            assert c.execute(text("SELECT kind, campaign_id FROM player_notes ORDER BY position")).all() == [
                ("quest", 1), ("combo", None)]
            m1 = c.execute(text("SELECT id FROM campaign_characters WHERE character_id = 1")).scalar()
            assert c.execute(text('SELECT "table", row_id FROM revisions')).one() == ("campaign_characters", m1)
        alembic("downgrade", "8f4a6b0c3d59")
        with db_engine.connect() as c:
            assert c.execute(text("SELECT entity_id, wild_shape_keep FROM characters ORDER BY id")).all() == [
                (10, ["unarmored-movement"]), (11, None)]
            assert c.execute(text('SELECT "table", row_id FROM revisions')).one() == ("characters", 1)
        alembic("upgrade", "head")
    finally:
        subprocess.run(["alembic", "downgrade", "base"], env=env, capture_output=True)
        Base.metadata.create_all(db_engine)
