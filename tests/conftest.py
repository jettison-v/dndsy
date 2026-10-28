import os
import re
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

# Each copy of the code (the main folder, each session's worktree) tests on its own database, named after its folder
# (askdnd_test_dndsy, askdnd_test_blissful_mestorf_689aef, …), so test runs in different copies never block each other.
# TEST_DATABASE_URL overrides it (GitHub sets it).
_CHECKOUT = re.sub(r"[^a-z0-9]+", "_", Path(__file__).resolve().parents[1].name.lower()).strip("_")[:30]
TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL") or f"postgresql+psycopg://localhost/askdnd_test_{_CHECKOUT}"
# The tests run in parallel (pytest-xdist, `-n auto` in pyproject.toml): each worker gets a database of its own
# (…_gw0, …_gw1), so one worker dropping its tables never pulls them from under another.
if WORKER := os.getenv("PYTEST_XDIST_WORKER"):
    _url = make_url(TEST_DATABASE_URL)
    TEST_DATABASE_URL = _url.set(database=f"{_url.database}_{WORKER}").render_as_string(hide_password=False)
# The app's own database connection (app.db) also points at the test database, so no test
# ever touches a development or production database (set before the app is imported).
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.hookimpl(tryfirst=True)  # before pytest-xdist reads the groups
def pytest_collection_modifyitems(items):
    """The browser tests share one server per file: keep them together on one worker."""
    for item in items:
        if "browser" in item.path.parts:
            item.add_marker(pytest.mark.xdist_group("browser"))


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session):
    """On GitHub every test must run: a skip there means missing tooling (the database, Chromium), so it fails."""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    skipped = reporter.stats.get("skipped", []) if reporter else []
    if os.getenv("CI") and not WORKER and skipped and session.exitstatus == 0:
        reporter.write_sep("=", f"{len(skipped)} skipped on GitHub, where every test must run", red=True)
        for report in skipped:
            reporter.write_line(f"  {report.nodeid}: {report.longrepr[-1] if isinstance(report.longrepr, tuple) else ''}")
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _ensure_database(url) -> None:
    """Create this copy's (or worker's) test database the first time it's needed."""
    admin = create_engine(url.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :d"), {"d": url.database}):
                conn.execute(text(f'CREATE DATABASE "{url.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def db_engine():
    """Fresh schema in the local test database. Skips if Postgres isn't running."""
    import app.models  # noqa: F401
    from app.db import Base

    engine = create_engine(TEST_DATABASE_URL)
    try:
        _ensure_database(engine.url)
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except OperationalError:
        if os.getenv("CI"):  # on GitHub a missing database must fail the run, not skip every test
            raise
        pytest.skip("local test database not available (brew services start postgresql@18)")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _no_background_drafts(monkeypatch):
    """Publishing a session starts drafting the next one (a real Claude call in a thread): never in tests.
    Tests that care replace it with their own recorder."""
    from app import admin_sessions

    monkeypatch.setattr(admin_sessions, "_draft_in_background", lambda ids: True)


@pytest.fixture(autouse=True)
def file_store(monkeypatch, tmp_path):
    """File storage (app/files.py) is a fresh folder per test, never private/files or S3."""
    from app import files

    store = files.LocalFolder(tmp_path / "files")
    monkeypatch.setattr(files, "storage", lambda: store)
    return store


@pytest.fixture(autouse=True)
def _books_read_fresh():
    """Each test reads books' entries from its own database (app/books.py keeps what it read)."""
    from app import books

    books._read.clear()


@pytest.fixture(autouse=True)
def _access_rows(monkeypatch):
    """Access checks (app/access.py) read people from the database. Tests never see
    the local dev database: no rows unless the test uses `db`, and no caching."""
    from app import access, game_mode, house_rules, live

    monkeypatch.setattr(access, "loader", lambda: {})
    monkeypatch.setattr(live, "loader", lambda: [])
    monkeypatch.setattr(game_mode, "loader", lambda campaign_id: dict(game_mode.OFF))
    monkeypatch.setattr(house_rules, "loader", lambda: {})
    monkeypatch.setattr(access, "CACHE_SECONDS", -1)
    monkeypatch.setattr(house_rules, "CACHE_SECONDS", -1)
    access.invalidate()
    house_rules.invalidate()


def _count_writes(conn) -> list[int]:
    """[how many statements other than reads this test's connection has run so far]"""
    writes = [0]

    @event.listens_for(conn, "before_cursor_execute")
    def _count(conn, cursor, statement, *args):
        if not statement.lstrip()[:6].upper() == "SELECT":
            writes[0] += 1

    return writes


def _until_changed(session, writes, load):
    """The access rows (and house rules) as the app's cache would hold them, reloaded after every write or unsaved
    change, so a test always sees its own changes. Loading them afresh on each of a page's dozens of checks was most
    of the time of the page tests."""
    last = {"at": None}

    def loader():
        if last["at"] != writes[0] or session.new or session.dirty or session.deleted:
            last["rows"] = load()  # its query saves the unsaved changes first, as before
            last["at"] = writes[0]
        return last["rows"]

    return loader


@pytest.fixture
def db(db_engine, monkeypatch):
    """A session whose changes are rolled back after each test."""
    from app import access, game_mode, house_rules, live
    from app.models import Campaign

    with db_engine.connect() as conn:
        trans = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
            writes = _count_writes(conn)
            monkeypatch.setattr(access, "loader", _until_changed(session, writes, lambda: access.rows_from(session)))
            monkeypatch.setattr(live, "loader", lambda: live.rows_from(session))
            monkeypatch.setattr(game_mode, "loader", lambda cid: game_mode.state(session, session.get(Campaign, cid)))
            monkeypatch.setattr(house_rules, "loader", _until_changed(session, writes, lambda: house_rules.rows_from(session)))
            from app import campaign_paths

            monkeypatch.setattr(campaign_paths, "remember", lambda email, cid: campaign_paths.remember_in(session, email, cid))
            yield session
        trans.rollback()


# The table's characters and signed-in clients (tests/table_setup.py), for any test file. Imported inside each fixture:
# the app must load only after DATABASE_URL above points at the test database.
@pytest.fixture
def no_network(monkeypatch):
    """D&D Beyond is never called: fetches and refreshes use the fixtures' fake."""
    from app import characters, ddb
    from tests.table_setup import fake_fetch

    monkeypatch.setattr(ddb, "fetch_character_json", fake_fetch)
    monkeypatch.setattr(characters.refresh, "__defaults__", (fake_fetch,))
    monkeypatch.setattr(characters.refresh_all, "__defaults__", (fake_fetch,))


def _signed_in(monkeypatch, db, email):
    from app.main import app
    from tests.table_setup import sign_in

    yield sign_in(monkeypatch, db, email)
    app.dependency_overrides.clear()


@pytest.fixture
def admin(monkeypatch, db):
    yield from _signed_in(monkeypatch, db, "admin@example.com")


@pytest.fixture
def dm(monkeypatch, db):
    yield from _signed_in(monkeypatch, db, "dm@example.com")


@pytest.fixture
def player(monkeypatch, db):
    yield from _signed_in(monkeypatch, db, "player@example.com")
