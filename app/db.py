"""Database engine and per-request sessions."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import NullPool

from app import config


class Base(DeclarativeBase):
    pass


# 30 connections at most, one each for most of FastAPI's 40 worker threads (Sentry ASKDND-V2-7, 2026-11-02: the default
# 15 ran out while requests held theirs through a read of D&D Beyond, which now reads a class's spell lists once in 6
# hours). Beta's Postgres allows 100: room for a second copy while a deploy overlaps, the backup job and the listener.
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20) if config.DATABASE_URL else None
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
# The event loop's own way in (app/access.py, the sign-in check every page and middleware makes): a connection of its
# own each time, never one from the pool. Worker threads give pool connections back only through the loop, so the loop
# waiting for one froze the whole server for 37 seconds (Sentry ASKDND-V2-P, Nov 8). Nothing else may use it.
loop_engine = create_engine(config.DATABASE_URL, poolclass=NullPool) if config.DATABASE_URL else None
LoopSession = sessionmaker(bind=loop_engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request. Its connection is taken at once, timed, so a slow request
    says whether it waited for one (app/timing.py: the pool running out looks like a slow server with nothing to do)."""
    from app import timing

    with SessionLocal() as session:
        with timing.step("waiting for a database connection"):
            session.connection()
        yield session
