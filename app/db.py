"""Database engine and per-request sessions."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app import config


class Base(DeclarativeBase):
    pass


# 30 connections at most (Sentry ASKDND-V2-7, 2026-11-02: the default 15 ran out while requests waited on D&D Beyond;
# beta's Postgres allows 100, and the backup job and the live listener take one each)
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_size=10, max_overflow=20) if config.DATABASE_URL else None
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one database session per request."""
    with SessionLocal() as session:
        yield session
