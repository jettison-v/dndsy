"""Database engine and per-request sessions."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


# Connections: up to one per worker thread (FastAPI runs plain routes on a pool of 40). With SQLAlchemy's default (5,
# and 10 more), the test table on Nov 2 ran out: requests waited 30 seconds for a connection while others held theirs
# through a read of D&D Beyond. Postgres allows 100; beta runs one copy of askdnd.
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=30) if config.DATABASE_URL else None
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with SessionLocal() as session:
        yield session
