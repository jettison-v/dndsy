"""Background jobs (Roadmap item 43; Brett's pick LB1 on docs/mockups/backend-look-back/, Nov 25; the plan is
docs/plans/2026-11-25-jobs-and-worker.md).

A job is a row in `jobs` that a worker takes, one at a time per queue, with `SELECT … FOR UPDATE SKIP LOCKED`: two
workers (an old and a new one, during a deploy) never take the same job. A request only adds a job and says so with
`pg_notify`, both in its own transaction, so a rolled-back request leaves nothing behind. The work itself runs in
app/worker.py, never holding a transaction while it waits on D&D Beyond or Claude.

The rules, in one place:
- a job is `queued`, `running`, `done`, `failed` or `cancelled`;
- the same `dedup_key` is never queued or running twice (adding it again raises the waiting one's priority);
- a running job's worker beats every 15 seconds; one silent for 60 (or past its kind's time limit) goes back to the
  queue while it has attempts left, else fails ("interrupted" or "timed out");
- finishing is fenced on the attempt it was claimed for, so a worker that was given up on can't overwrite a later try;
- a worker takes only kinds it knows (an older worker leaves a newer kind waiting).
"""

import os
import socket
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

LEASE = timedelta(seconds=60)  # (a running job whose worker hasn't beaten for this long is given up on)
BEAT_SECONDS = 15


@dataclass(frozen=True)
class Kind:
    """What one kind of job is: its queue (a lane served one at a time), how often it may be tried, its time limit,
    how long a finished one is kept, and the function that does it (given a Session and the payload; returns a small
    dict kept as the job's result)."""

    name: str
    queue: str
    run: Callable[[Session, dict], dict | None]
    max_attempts: int = 3
    timeout: timedelta = timedelta(seconds=60)
    backoff: tuple[int, ...] = (10, 60)  # (seconds before each retry)
    keep_done: timedelta = timedelta(hours=24)
    gap: float = 0  # (seconds its lane waits after each one: D&D Beyond is asked at most once a second)
    rest: float = 0  # (seconds its lane rests after one fails: D&D Beyond struggling isn't asked again at once)


KINDS: dict[str, Kind] = {}


class Expected(Exception):
    """A failure the job expects at times (D&D Beyond not answering): kept on the job as its own words, no stack trace."""


def register(kind: Kind) -> Kind:
    KINDS[kind.name] = kind
    return kind


KIND_MODULES = ("app.sheet_reads",)  # (each registers its kinds when imported: the web app and the worker load the same)


def load_kinds() -> None:
    import importlib

    for name in KIND_MODULES:
        importlib.import_module(name)


def me() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"[:80]


def version() -> str:
    return (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "")[:40]


def enqueue(db: Session, kind: str, payload: dict | None = None, dedup_key: str | None = None, *, priority: int = 0,
            campaign_id: int | None = None, label: str = "", by: str = "", run_at: datetime | None = None) -> tuple[int, bool]:
    """Add a job (in the caller's transaction): (its id, whether it was new). One already waiting or running with the
    same dedup_key is kept, its priority raised to this one's if higher and its time brought forward if sooner."""
    k = KINDS[kind]
    row = db.execute(text(
        "INSERT INTO jobs (kind, queue, payload, dedup_key, campaign_id, label, requested_by, priority, run_at, max_attempts) "
        "VALUES (:kind, :queue, CAST(:payload AS jsonb), :dedup, :campaign, :label, :by, :priority, COALESCE(:run_at, now()), :max) "
        "ON CONFLICT (dedup_key) WHERE state IN ('queued', 'running') DO UPDATE SET priority = GREATEST(jobs.priority, EXCLUDED.priority), "
        "run_at = LEAST(jobs.run_at, EXCLUDED.run_at) "
        "RETURNING id, (xmax = 0) AS created"),
        {"kind": kind, "queue": k.queue, "payload": _json(payload or {}), "dedup": dedup_key, "campaign": campaign_id,
         "label": label[:200], "by": by[:200], "priority": priority, "run_at": run_at, "max": k.max_attempts}).one()
    db.execute(text("SELECT pg_notify('askdnd_jobs', :queue)"), {"queue": k.queue})
    return row.id, bool(row.created)


def claim(db: Session, queue: str, worker: str | None = None) -> dict | None:
    """Take the next job of a queue this code knows, in its own short transaction (committed here): {id, kind, payload,
    attempts} or None."""
    known = [k.name for k in KINDS.values() if k.queue == queue]
    if not known:
        return None
    row = db.execute(text(
        "UPDATE jobs SET state = 'running', attempts = attempts + 1, started_at = now(), heartbeat_at = now(), "
        "claimed_by = :me, version = :version WHERE id = ("
        "  SELECT id FROM jobs WHERE state = 'queued' AND queue = :queue AND kind = ANY(:known) AND run_at <= now() "
        "  ORDER BY priority DESC, run_at, id FOR UPDATE SKIP LOCKED LIMIT 1) "
        "RETURNING id, kind, payload, attempts, campaign_id"),
        {"me": worker or me(), "version": version(), "queue": queue, "known": known}).one_or_none()
    db.commit()
    return dict(row._mapping) if row else None


def beat(db: Session, job_id: int, attempts: int) -> bool:
    """A running job's heartbeat (its own short transaction); False when it's no longer this attempt's to run."""
    n = db.execute(text("UPDATE jobs SET heartbeat_at = now() WHERE id = :id AND state = 'running' AND attempts = :n"),
                   {"id": job_id, "n": attempts}).rowcount
    db.commit()
    return bool(n)


def finish(db: Session, job_id: int, attempts: int, result: dict | None = None) -> bool:
    """Done, fenced on the attempt it was claimed for: False (and nothing written) when the job was given up on."""
    n = db.execute(text("UPDATE jobs SET state = 'done', finished_at = now(), result = CAST(:result AS jsonb), error = '' "
                        "WHERE id = :id AND state = 'running' AND attempts = :n"),
                   {"id": job_id, "n": attempts, "result": _json(result) if result is not None else None}).rowcount
    db.commit()
    return bool(n)


def fail(db: Session, job_id: int, attempts: int, error: str, retry: bool = True) -> str:
    """It went wrong: back to the queue after its backoff while attempts are left (and `retry`), else failed. Fenced
    as finish is. Returns the job's new state, or "" when it wasn't this attempt's."""
    row = db.execute(text("SELECT kind, max_attempts FROM jobs WHERE id = :id AND state = 'running' AND attempts = :n"),
                     {"id": job_id, "n": attempts}).one_or_none()
    if row is None:
        db.rollback()
        return ""
    k = KINDS.get(row.kind)
    again = retry and attempts < row.max_attempts
    wait = (k.backoff[min(attempts - 1, len(k.backoff) - 1)] if k and k.backoff else 0) if again else 0
    db.execute(text("UPDATE jobs SET state = :state, error = :error, finished_at = CASE WHEN :again THEN NULL ELSE now() END, "
                    "run_at = now() + make_interval(secs => :wait) WHERE id = :id AND state = 'running' AND attempts = :n"),
               {"state": "queued" if again else "failed", "error": error[:2000], "again": again, "wait": wait, "id": job_id, "n": attempts})
    db.commit()
    return "queued" if again else "failed"


def put_back(db: Session, job_id: int, attempts: int) -> bool:
    """A worker stopping (a deploy): its job goes back to the queue as it was, this attempt not counted against it."""
    n = db.execute(text("UPDATE jobs SET state = 'queued', attempts = attempts - 1, claimed_by = '', started_at = NULL "
                        "WHERE id = :id AND state = 'running' AND attempts = :n"), {"id": job_id, "n": attempts}).rowcount
    db.commit()
    return bool(n)


def reap(db: Session, now: datetime | None = None) -> int:
    """Running jobs whose worker went silent past the lease, or that ran past their kind's time limit: back to the
    queue while they have attempts left, else failed. Returns how many."""
    now = now or datetime.now(UTC)
    rows = db.execute(text("SELECT id, kind, attempts, max_attempts, heartbeat_at, started_at FROM jobs WHERE state = 'running'")).all()
    n = 0
    for r in rows:
        k = KINDS.get(r.kind)
        silent = r.heartbeat_at is None or now - r.heartbeat_at > LEASE
        overrun = k is not None and r.started_at is not None and now - r.started_at > k.timeout
        if not (silent or overrun):
            continue
        again = r.attempts < r.max_attempts
        db.execute(text("UPDATE jobs SET state = :state, error = :error, finished_at = CASE WHEN :again THEN NULL ELSE now() END "
                        "WHERE id = :id AND state = 'running' AND attempts = :n"),
                   {"state": "queued" if again else "failed", "error": "Interrupted" if silent else "Timed out", "again": again,
                    "id": r.id, "n": r.attempts})
        n += 1
    db.commit()
    return n


def sweep(db: Session, now: datetime | None = None) -> int:
    """Forget finished jobs once kept long enough: each kind's done ones after its keep_done, failed and cancelled ones
    after 30 days. Returns how many."""
    now = now or datetime.now(UTC)
    n = db.execute(text("DELETE FROM jobs WHERE state IN ('failed', 'cancelled') AND finished_at < :cut"),
                   {"cut": now - timedelta(days=30)}).rowcount
    for k in KINDS.values():
        n += db.execute(text("DELETE FROM jobs WHERE state = 'done' AND kind = :kind AND finished_at < :cut"),
                        {"kind": k.name, "cut": now - k.keep_done}).rowcount
    db.commit()
    return n


def counts(db: Session) -> dict[str, int]:
    """How many jobs are in each state (the sync queue's top line, Roadmap item 44)."""
    return {r.state: r.n for r in db.execute(text("SELECT state, count(*) AS n FROM jobs GROUP BY state"))}


def _json(value) -> str:
    import json

    return json.dumps(value, default=str)
