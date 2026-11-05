"""The one-time clean-up of test leftovers (migrations/versions/2026_11_05-f4a9c2d81e30_test_leftovers.py)."""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from app.importer import import_bundle
from app.models import Campaign, Character, Entity, User
from tests.table_setup import BUNDLE, char, owned_by

MIGRATION = Path(__file__).parent.parent / "migrations" / "versions" / "2026_11_05-f4a9c2d81e30_test_leftovers.py"


def _run(db):
    spec = importlib.util.spec_from_file_location("leftovers", MIGRATION)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    with Operations.context(MigrationContext.configure(db.connection())):
        m.upgrade()
    db.expire_all()


def test_it_deletes_only_test_leftovers_and_never_the_tables_own(db, monkeypatch):
    """A standing rule (CLAUDE.md › Repo: anything that deletes data on beta needs Brett's approval; Brett approved this
    list, Nov 5): the clean-up never takes a character at a real table, a test copy still at one, or an account in use."""
    from app import characters

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    import_bundle(db, {"campaign": {"slug": "vtt-test", "name": "VTT test"}, "entities": [
        {"kind": "pc", "name": "Spurt the Sorcerer", "character": {"ddb_id": "172836747"}},
        {"kind": "pc", "name": "Cathartic", "character": {"ddb_id": "172986165"}}]})
    test = db.scalar(select(Campaign).where(Campaign.slug == "vtt-test"))
    test.is_test = True
    kept_copy = characters.test_copy(db, cole, test.id)  # a test copy still at VTT test
    old_copy = characters.test_copy(db, cole, test.id)
    characters.move(db, old_copy, None)  # one at no table: the first try's
    db.add_all([User(email="tim.old@example.com", name="Tim", access="removed"), User(email="tim@example.com", name="Tim", access="member"),
                User(email="sam.old@example.com", name="Sam", access="removed")])  # (Sam: removed, but no newer account)
    db.flush()
    spurt_entry = db.scalar(select(Entity).where(Entity.name == "Spurt the Sorcerer")).id
    kept_id, old_id = kept_copy.id, old_copy.id

    _run(db)
    names = sorted(c.name for c in db.scalars(select(Character)))
    assert names == ["Big C", "Cathartic", "Cole", "Cole", "Trah"]  # the real table, Cathartic and the copy still at VTT test
    assert db.get(Character, kept_id) and db.get(Character, old_id) is None
    assert db.get(Entity, spurt_entry) is None
    emails = {u.email for u in db.scalars(select(User))}
    assert "tim.old@example.com" not in emails and {"tim@example.com", "sam.old@example.com", "player@example.com"} <= emails


def test_a_replaced_account_a_sign_in_list_names_stays(db, monkeypatch):
    monkeypatch.setenv("ALLOWED_EMAILS", "tim.old@example.com")
    db.add_all([User(email="tim.old@example.com", name="Tim", access="removed"), User(email="tim@example.com", name="Tim", access="member")])
    db.flush()
    _run(db)
    assert "tim.old@example.com" in {u.email for u in db.scalars(select(User))}  # (its record is what keeps it out)
