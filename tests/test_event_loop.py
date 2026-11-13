"""The server's one event loop never waits for the database pool (Sentry ASKDND-V2-P, Nov 8): worker threads give their
connections back through the loop, so the loop waiting for one froze the whole server for 37 seconds, every page and
live connection with it, until the pool's 30-second timeout broke it."""

import asyncio
import inspect
import threading
import time

from fastapi.routing import APIRoute, APIWebSocketRoute

from app import access
from app.db import get_db
from app.main import app

# Async because they await Google's sign-in; their database work runs in run_in_threadpool.
AWAIT_GOOGLE = {"/auth/callback", "/admin/notes/callback"}


def _uses_db(dependant) -> bool:
    return any(d.call is get_db or _uses_db(d) for d in dependant.dependencies)


def _routes(routes):
    for r in routes:
        if hasattr(r, "original_router"):  # (an included router)
            yield from _routes(r.original_router.routes)
        else:
            yield r


def test_no_async_route_uses_the_database():
    """CLAUDE.md › Conventions: a route that uses the database is a plain `def` (it runs on a worker thread)."""
    every = [r for r in _routes(app.routes) if isinstance(r, APIRoute | APIWebSocketRoute)]
    assert len(every) > 150  # (the walk finds them all)
    found = [r.path for r in every if inspect.iscoroutinefunction(r.endpoint) and _uses_db(r.dependant)]
    assert sorted(found) == sorted(AWAIT_GOOGLE)


def test_the_access_check_on_the_loop_never_waits_for_aged_rows(monkeypatch):
    """Middleware asks who may sign in on every request, on the loop: rows that have merely aged are refreshed on a
    thread while the loop goes on with the ones it has."""
    calls: list[bool] = []
    started = threading.Event()

    def slow():
        calls.append(access._on_loop())
        started.set()
        time.sleep(0.2)
        return {"new@example.com": {"access": access.MEMBER}}

    monkeypatch.setattr(access, "loader", slow)
    monkeypatch.setattr(access, "CACHE_SECONDS", 10)  # (the server's: the tests' own setup caches nothing)
    monkeypatch.setitem(access._cache, "rows", {"old@example.com": {"access": access.MEMBER}})
    monkeypatch.setitem(access._cache, "at", time.monotonic() - access.CACHE_SECONDS - 1)

    async def ask():
        t = time.monotonic()
        rows = access._rows()
        return rows, time.monotonic() - t

    rows, took = asyncio.run(ask())
    assert "old@example.com" in rows and took < 0.1  # (the loop went on at once)
    assert started.wait(2) and calls == [False]  # (loaded on a thread, through the pool)
    for _ in range(50):
        if "new@example.com" in access._cache["rows"]:
            break
        time.sleep(0.02)
    assert "new@example.com" in access._cache["rows"]


def test_a_change_is_loaded_at_once_on_the_loop_through_its_own_connection(monkeypatch):
    """After a change (`invalidate`) the next look loads it straight away, even on the loop: through the loop's own
    connection (`db.LoopSession`), never the pool's (`SessionLocal`), which a worker thread waits for."""
    import contextlib

    from app import db as dbmod

    used = []
    monkeypatch.setattr(dbmod, "LoopSession", lambda: used.append("loop") or contextlib.nullcontext())
    monkeypatch.setattr(dbmod, "SessionLocal", lambda: used.append("pool") or contextlib.nullcontext())
    monkeypatch.setattr(access, "rows_from", lambda db: {"someone@example.com": {"access": access.MEMBER}})
    monkeypatch.setattr(access, "loader", access._load_from_db)
    monkeypatch.setattr(access, "CACHE_SECONDS", 10)
    access.invalidate()

    async def ask():
        return access._rows()

    assert "someone@example.com" in asyncio.run(ask()) and used == ["loop"]
    access.invalidate()
    access._rows()
    assert used == ["loop", "pool"]  # (off the loop: the pool, as before)


def test_a_change_made_while_the_rows_load_stays_due(monkeypatch):
    """Rows loaded from before a change never count as fresh (the change waits for the next look)."""

    def changing():
        access.invalidate()  # (someone changed something while this load ran)
        return {}

    monkeypatch.setattr(access, "loader", changing)
    access.invalidate()
    access._rows()
    assert access._cache["at"] == 0.0
    monkeypatch.setattr(access, "loader", dict)
    access._rows()
    assert access._cache["at"] > 0
