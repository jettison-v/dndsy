"""Reading sheets from D&D Beyond, through the jobs queue (Roadmap item 43, step 4; the backend look-back's LB2, Brett's
pick A, Nov 25; docs/plans/2026-11-25-jobs-and-worker.md).

Every read of a character's sheet is a `ddb_refresh` job on the `ddb` queue, one at a time: a page's tick, Refresh
now, Refresh everyone, linking a sheet, the look at sheets nobody has open. So D&D Beyond is asked once per character
however many pages ask (one job per character waiting or running: asking again only moves it up), never twice at once,
with a second between reads and a 30-second rest after D&D Beyond fails, and every read is on the record (the Sync
queue, item 44). The read itself is unchanged: `characters.read_released` then `store`, and a stored sheet announces
itself to open pages (app/realtime.py).

Who asks sets the order: a person pressing Refresh (10) ahead of a page's tick (0) ahead of a sheet nobody has open
(-5). A press waits a few seconds for its answer (`read_now`), so its message still says what happened; a page's tick
doesn't wait (the new copy reaches it through the live connection).
"""

import contextlib
import threading
import time
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import jobs

KIND = "ddb_refresh"
QUEUE = "ddb"
PRESS, PAGE, UNWATCHED = 10, 0, -5  # (priorities)
WAIT_SECONDS = 8.0  # (a press waits this long for its answer, then says it's on its way)


class ReadFailed(jobs.Expected):
    """D&D Beyond didn't give the sheet (askdnd kept the last good copy): the job tries again after its backoff."""


def _run(db: Session, payload: dict) -> dict:
    from app import characters as chars
    from app.models import Character

    ch = db.get(Character, int(payload.get("character_id") or 0))
    if ch is None or not ch.ddb_id:
        return {"skipped": "no sheet linked"}
    snap = chars.store(db, ch, chars.read_released(db, ch))
    db.commit()
    if snap.status != "ok":
        raise ReadFailed(snap.error or "D&D Beyond didn't answer")
    return {"status": "ok"}


jobs.register(jobs.Kind(KIND, QUEUE, _run, max_attempts=3, timeout=timedelta(seconds=60), backoff=(10, 60),
                        keep_done=timedelta(hours=24), gap=1.0, rest=30.0))


def who(user: dict | None) -> str:
    """Who asked, as the Sync queue says it: a first name only (never an email)."""
    from app.extraction import first_name

    return first_name((user or {}).get("name") or "")[:60]


def label(ch) -> str:
    return f"Read {ch.name}'s sheet"[:200]


def request_read(db: Session, ch, *, min_age: timedelta, priority: int = PAGE, by: str = "") -> int | None:
    """Ask for a read of this character's sheet, unless one was tried in the last `min_age`; in the caller's
    transaction. Returns the job's id, or None when nothing was asked."""
    if not ch.ddb_id:
        return None
    snap = ch.snapshot
    if snap is not None and snap.attempted_at is not None and datetime.now(UTC) - snap.attempted_at < min_age:
        return None
    job_id, new = jobs.enqueue(db, KIND, {"character_id": ch.id}, f"ddb:char:{ch.id}", priority=priority,
                               campaign_id=ch.campaign_id, label=label(ch), by=by)
    if not new and priority >= PRESS:  # (a press on one trying again after a failure: it's asked afresh, now)
        db.execute(text("UPDATE jobs SET error = '' WHERE id = :id AND state = 'queued'"), {"id": job_id})
    return job_id


def _state(db: Session, job_ids: list[int]) -> dict[int, tuple[str, str]]:
    """{job id: (state, its last error)}, each look its own short transaction (nothing held while waiting)."""
    rows = db.execute(text("SELECT id, state, error FROM jobs WHERE id = ANY(:ids)"), {"ids": job_ids}).all()
    db.commit()
    return {r.id: (r.state, r.error or "") for r in rows}


def _open(st: tuple[str, str] | None) -> bool:
    """Still to be answered: waiting its first try or running (one trying again after a failure has its answer)."""
    return st is not None and (st[0] == "running" or (st[0] == "queued" and not st[1]))


def read_now(db: Session, chars_: list, *, by: str = "", seconds: float = WAIT_SECONDS) -> dict[int, str]:
    """A person pressed Refresh: ask for each sheet first in line and wait up to `seconds` for the answers. Returns
    {character id: "done" | "failed" | "waiting" | "skipped"}: "failed" once a try failed (it tries again by itself,
    and the page keeps the last good copy meanwhile), "waiting" when it hasn't been answered in time, "skipped" for one
    with no sheet linked. Where no lane of this copy serves the queue and jobs run here (tests, a copy started without
    them), this request runs the queue itself until its own are answered."""
    from app import worker

    asked = {ch.id: request_read(db, ch, min_age=timedelta(0), priority=PRESS, by=by) for ch in chars_}
    ids = [j for j in asked.values() if j is not None]
    db.commit()
    deadline = time.monotonic() + seconds
    states = _state(db, ids) if ids else {}
    if ids and worker.runner() == "inline" and not worker.serving(QUEUE):
        lane = worker.Lane(QUEUE, lambda: contextlib.nullcontext(db), threading.Event(), jobs.me())
        while any(_open(states.get(j)) for j in ids) and time.monotonic() < deadline and lane.run_once():
            states = _state(db, ids)
    while any(_open(states.get(j)) for j in ids) and time.monotonic() < deadline:
        time.sleep(0.25)
        states = _state(db, ids)
    db.expire_all()  # (the sheets as the jobs stored them)
    out = {}
    for cid, j in asked.items():
        st = states.get(j) if j is not None else None
        out[cid] = ("skipped" if j is None else "done" if st is None or st[0] == "done" else
                    "failed" if st[0] == "failed" or st[1] else "waiting")
    return out
