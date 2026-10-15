import pytest
from sqlalchemy import func, select

from app.importer import BundleError, import_bundle
from app.models import Character, Entity, EntityAlias, GameSession, GlossaryTerm, User

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
