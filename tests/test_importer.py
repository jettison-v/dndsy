import pytest
from sqlalchemy import func, select

from app.importer import BundleError, import_bundle
from app.models import Character, Entity, EntityAlias, EntityRelation, GameSession, GlossaryTerm, User

BUNDLE = {
    "campaign": {"slug": "test-campaign", "name": "Test Campaign"},
    "members": [
        {"email": "Owner@Example.com", "name": "Owner", "role": "player", "is_admin": True},
        {"email": "dm@example.com", "name": "DM", "role": "dm"},
    ],
    "entities": [
        {
            "kind": "pc",
            "name": "No Name",
            "aliases": [{"alias": "Sarkas", "note": "former name"}],
            "character": {"owner_email": "owner@example.com", "ddb_id": 123},
        },
        {"kind": "npc", "name": "Lillippi Lemon", "summary": "Tiefling bard.", "aliases": ["LL"]},
        {"kind": "quest", "name": "Find the library", "quest_open": True},
    ],
    "glossary": [{"term": "Lillippi", "misheard_as": ["Lollipy"]}],
    "sessions": [{"number": 17, "title": "Grove"}, {"played_on": "2026-08-29", "source": "transcript"}],
}


def count(db, model):
    return db.scalar(select(func.count()).select_from(model))


def test_import_creates_everything(db):
    counts = import_bundle(db, BUNDLE)
    assert counts["entities created"] == 3
    assert counts["sessions created"] == 2
    ch = db.scalar(select(Character))
    assert ch.ddb_id == "123"
    assert ch.owner.email == "owner@example.com"
    assert db.scalar(select(User).where(User.email == "owner@example.com")).is_admin


def test_import_twice_does_not_duplicate(db):
    import_bundle(db, BUNDLE)
    again = dict(BUNDLE, glossary=[{"term": "Lillippi", "misheard_as": ["Lollipy", "Lilipy"]}])
    counts = import_bundle(db, again)
    assert counts["entities created"] == 0 and counts["sessions created"] == 0
    assert count(db, Entity) == 3
    assert count(db, EntityAlias) == 2
    assert db.scalar(select(GlossaryTerm)).misheard_as == ["Lollipy", "Lilipy"]
    assert count(db, GameSession) == 2


def test_entity_names_match_ignoring_case_and_spacing(db):
    import_bundle(db, BUNDLE)
    import_bundle(db, {"campaign": BUNDLE["campaign"], "entities": [{"kind": "npc", "name": "lillippi  lemon", "summary": "Bard."}]})
    assert count(db, Entity) == 3
    assert db.scalar(select(Entity).where(Entity.name == "Lillippi Lemon")).summary == "Bard."


def test_bad_bundles_rejected(db):
    with pytest.raises(BundleError):
        import_bundle(db, {"members": []})
    with pytest.raises(BundleError):
        import_bundle(db, {"campaign": {"slug": "x", "name": "X"}, "entities": [{"kind": "npc", "name": "A", "character": {}}]})
    with pytest.raises(BundleError):
        import_bundle(db, {"campaign": {"slug": "x", "name": "X"}, "sessions": [{"title": "no date"}]})


def test_alias_matching_existing_name_renames_it(db):
    import_bundle(db, {"campaign": BUNDLE["campaign"], "entities": [{"kind": "npc", "name": "Kiera", "summary": "Sailor."}]})
    kiera = db.scalar(select(Entity).where(Entity.name == "Kiera"))
    counts = import_bundle(db, {"campaign": BUNDLE["campaign"], "entities": [
        {"kind": "npc", "name": "Kieran", "aliases": ["Kiera"], "summary": "Sailor, now Kieran."}]})
    assert counts["entities renamed"] == 1 and counts["entities created"] == 0
    db.refresh(kiera)
    assert kiera.name == "Kieran" and kiera.summary == "Sailor, now Kieran."
    assert [(a.alias, a.note) for a in kiera.aliases] == [("Kiera", "former name")]
    again = import_bundle(db, {"campaign": BUNDLE["campaign"], "entities": [{"kind": "npc", "name": "Kieran", "aliases": ["Kiera"]}]})
    assert again["entities renamed"] == 0 and count(db, Entity) == 1 and count(db, EntityAlias) == 1
    # A place called Kiera is a different kind, so it's not a rename.
    import_bundle(db, {"campaign": BUNDLE["campaign"], "entities": [{"kind": "place", "name": "Kiera's Rest", "aliases": ["Kieran"]}]})
    assert count(db, Entity) == 2


def test_import_relationships(db):
    bundle = dict(BUNDLE, relationships=[
        {"from": "LL", "type": "member_of", "to": "Find the library"},
        {"from": "Sarkas", "type": "ally_of", "to": "Lillippi Lemon", "note": "since the grove"},
    ])
    counts = import_bundle(db, bundle)
    assert counts["relationships added"] == 2
    rels = {(r.from_entity.name, r.type, r.to_entity.name, r.note) for r in db.scalars(select(EntityRelation))}
    assert ("No Name", "ally_of", "Lillippi Lemon", "since the grove") in rels
    assert import_bundle(db, bundle)["relationships added"] == 0
    with pytest.raises(BundleError, match="no entity named"):
        import_bundle(db, dict(BUNDLE, relationships=[{"from": "Nobody", "type": "ally_of", "to": "LL"}]))
    with pytest.raises(BundleError, match="unknown relationship type"):
        import_bundle(db, dict(BUNDLE, relationships=[{"from": "LL", "type": "likes", "to": "Sarkas"}]))
