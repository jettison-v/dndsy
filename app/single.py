"""One copy of the app at a time: the loops that start with the app (the Inbox digest, nobody's-listening, the Sentry
look, unwatched sheets) each run their look only where it holds a Postgres advisory lock, so two copies (during a
deploy, or a second replica) never send the same email twice or read the same sheet twice (the backend look-back's LB4,
Brett's pick Nov 25: one way to do it, not four copies).

The lock is held on its own connection and outlives the transaction, so nothing stays open while the look waits on
D&D Beyond, Sentry or the mail service. Each loop keeps its own lock number (`LOCK` in its module); tests/test_single.py
keeps them apart.
"""

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

log = logging.getLogger("askdnd.single")


def alone[T](lock: int, work: Callable[[Session], T], otherwise: T) -> T:
    """Run `work` with a session of its own while this copy holds `lock`; `otherwise` when another copy does."""
    from app.db import SessionLocal, engine

    with engine.connect() as hold:
        got = hold.execute(select(func.pg_try_advisory_lock(lock))).scalar()
        hold.commit()  # (the lock outlives the transaction: nothing stays open while the look runs)
        if not got:
            return otherwise
        try:
            with SessionLocal() as db:
                return work(db)
        finally:
            hold.execute(select(func.pg_advisory_unlock(lock)))
            hold.commit()


async def every(seconds: float, run_once: Callable[[], object], what: str) -> None:
    """A look every `seconds`, on a worker thread (never the event loop), never stopping on an error."""
    while True:
        await asyncio.sleep(seconds)
        try:
            await asyncio.to_thread(run_once)
        except Exception:
            log.warning("%s failed this time", what, exc_info=True)
