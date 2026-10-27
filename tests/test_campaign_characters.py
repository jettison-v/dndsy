"""Characters separate from campaigns (data organization step 1): a character has its own name and data;
which campaign it's in, its story page there and the DM's Wild Shape ruling are a CampaignCharacter."""

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app import characters, entities, history
from app.importer import import_bundle
from app.models import CampaignCharacter, Character, Entity, EntityKind, PlayerNote, Revision
from tests.table_setup import BUNDLE, fake_fetch


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
