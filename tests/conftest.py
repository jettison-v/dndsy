import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://localhost/askdnd_test")
# The app's own database connection (app.db) also points at the test database, so no test
# ever touches a development or production database (set before the app is imported).
os.environ["DATABASE_URL"] = TEST_DATABASE_URL


@pytest.fixture(scope="session")
def db_engine():
    """Fresh schema in the local test database. Skips if Postgres isn't running."""
    import app.models  # noqa: F401
    from app.db import Base

    engine = create_engine(TEST_DATABASE_URL)
    try:
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
def _access_rows(monkeypatch):
    """Access checks (app/access.py) read people from the database. Tests never see
    the local dev database: no rows unless the test uses `db`, and no caching."""
    from app import access

    monkeypatch.setattr(access, "loader", lambda: {})
    monkeypatch.setattr(access, "CACHE_SECONDS", -1)
    access.invalidate()


@pytest.fixture
def db(db_engine, monkeypatch):
    """A session whose changes are rolled back after each test."""
    from app import access

    with db_engine.connect() as conn:
        trans = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
            monkeypatch.setattr(access, "loader", lambda: access.rows_from(session))
            yield session
        trans.rollback()
