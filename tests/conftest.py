import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://localhost/askdnd_test")


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
        pytest.skip("local test database not available (brew services start postgresql@18)")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def db(db_engine):
    """A session whose changes are rolled back after each test."""
    with db_engine.connect() as conn:
        trans = conn.begin()
        with Session(bind=conn, join_transaction_mode="create_savepoint") as session:
            yield session
        trans.rollback()
