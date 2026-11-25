"""The worker: takes background jobs (app/jobs.py) one at a time per queue and runs them (Roadmap item 43; Brett's pick
LB1, Nov 25; docs/plans/2026-11-25-jobs-and-worker.md).

It runs two ways, from the same code:
- **its own process** (`uv run python -m app.worker`): the `askdnd-worker` service on Railway, so a deploy of the web
  app no longer stops work half done;
- **inside the web app** (`JOBS_RUNNER=inline`, the default locally, in tests and on staging): the same lanes on
  threads started at startup, never on the event loop.

Each queue is a lane on its own thread: it waits for a `pg_notify('askdnd_jobs', queue)` or a short poll, takes the
next job, beats every 15 seconds while it runs (on its own connection), and finishes or fails it, fenced on its
attempt. One lane also gives up on silent jobs and forgets old ones. On SIGTERM (a deploy) it stops taking jobs, lets
the one running finish within the drain, and otherwise puts it back for the next worker.

The worker never runs migrations: at startup it waits until the database's head is its own.
"""

import logging
import os
import signal
import threading
import time
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app import jobs

log = logging.getLogger("askdnd.worker")
POLL_SECONDS = 5  # (a lane looks again this often even without a notify: a job due later, a notify missed)
HOUSEKEEP_SECONDS = 30  # (how often silent jobs are given up on; old ones are forgotten hourly)
DRAIN_SECONDS = int(os.getenv("RAILWAY_DEPLOYMENT_DRAINING_SECONDS", "300") or 300)


def runner() -> str:
    """Where jobs run: "inline" (threads in the web app) or "worker" (the separate service)."""
    return (os.getenv("JOBS_RUNNER") or "inline").strip().lower()


_serving: set[str] = set()  # (the queues this copy's lanes serve)


def serving(queue: str) -> bool:
    """Whether a lane of this copy serves the queue now."""
    return queue in _serving


class Lane:
    """One queue, served one job at a time on its own thread."""

    def __init__(self, queue: str, session_factory, stop: threading.Event, who: str):
        self.queue, self.factory, self.stop, self.who = queue, session_factory, stop, who
        self.wake = threading.Event()
        self.current: dict | None = None
        self.last: tuple[str, str] | None = None  # (the last job's kind and how it ended: the loop's gap or rest)

    def run_once(self) -> bool:
        """Take and run one job; False when there was none."""
        with self.factory() as db:
            job = jobs.claim(db, self.queue, self.who)
        if job is None:
            return False
        self.current = job
        kind = jobs.KINDS.get(job["kind"])
        beating = threading.Event()
        beat = threading.Thread(target=self._beat, args=(job, beating), daemon=True)
        beat.start()
        try:
            with self.factory() as db:
                result = kind.run(db, job["payload"] or {})
                db.commit()
            with self.factory() as db:
                jobs.finish(db, job["id"], job["attempts"], result)
            self.last = (job["kind"], "done")
            _announce(job, "done")
        except Exception as e:  # (any failure is the job's, recorded on it; the lane goes on)
            log.warning("Job %s (%s) failed: %s", job["id"], job["kind"], e, exc_info=not isinstance(e, jobs.Expected))
            with self.factory() as db:
                state = jobs.fail(db, job["id"], job["attempts"], str(e) if isinstance(e, jobs.Expected) else f"{type(e).__name__}: {e}")
            self.last = (job["kind"], "failed")
            _announce(job, state or "failed")
        finally:
            beating.set()
            self.current = None
        return True

    def _beat(self, job: dict, done: threading.Event) -> None:
        while not done.wait(jobs.BEAT_SECONDS):
            try:
                with self.factory() as db:
                    if not jobs.beat(db, job["id"], job["attempts"]):
                        return
            except Exception:
                log.warning("A heartbeat for job %s didn't save", job["id"], exc_info=True)

    def loop(self) -> None:
        _serving.add(self.queue)
        try:
            while not self.stop.is_set():
                try:
                    if self.run_once():
                        self.stop.wait(self.pause())
                        continue
                except Exception:
                    log.exception("The %s lane couldn't take a job", self.queue)
                self.wake.wait(POLL_SECONDS)
                self.wake.clear()
        finally:
            _serving.discard(self.queue)

    def pause(self) -> float:
        """After a job: its kind's rest when it failed, else its gap (D&D Beyond asked at most once a second)."""
        kind = jobs.KINDS.get(self.last[0]) if self.last else None
        if kind is None:
            return 0
        return kind.rest if self.last[1] == "failed" else kind.gap


def _announce(job: dict, state: str) -> None:
    """Pages hear a job's new state (the Sessions row, the sync queue); a sheet the job stored announces itself."""
    try:
        from app import realtime

        realtime.publish(job.get("campaign_id"), "job", id=job["id"], job=job["kind"], state=state)
    except Exception:
        log.warning("Couldn't announce job %s", job["id"], exc_info=True)


def housekeep(session_factory) -> None:
    with session_factory() as db:
        jobs.reap(db)
        if datetime.now(UTC).minute == 0:
            jobs.sweep(db)


def start(session_factory, stop: threading.Event, who: str | None = None) -> list[Lane]:
    """Start a lane per queue the registered kinds use, and the housekeeping, on threads. Returns the lanes."""
    jobs.load_kinds()
    if not jobs.KINDS:
        return []  # (no kind of job yet: nothing to run)
    who = who or jobs.me()
    lanes = [Lane(q, session_factory, stop, who) for q in sorted({k.queue for k in jobs.KINDS.values()})]
    for lane in lanes:
        threading.Thread(target=lane.loop, name=f"jobs-{lane.queue}", daemon=True).start()

    def keep() -> None:
        while not stop.wait(HOUSEKEEP_SECONDS):
            try:
                housekeep(session_factory)
            except Exception:
                log.warning("Housekeeping the jobs failed", exc_info=True)

    threading.Thread(target=keep, name="jobs-housekeeping", daemon=True).start()
    threading.Thread(target=_listen, args=(lanes, stop), name="jobs-listen", daemon=True).start()
    return lanes


def _listen(lanes: list[Lane], stop: threading.Event) -> None:
    """Wake a lane as soon as a job is added to its queue (LISTEN askdnd_jobs), rather than at its next poll."""
    try:
        import psycopg

        from app import config

        url = config.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("LISTEN askdnd_jobs")
            by_queue = {lane.queue: lane for lane in lanes}
            while not stop.is_set():
                for note in conn.notifies(timeout=POLL_SECONDS, stop_after=1):
                    lane = by_queue.get(note.payload)
                    if lane:
                        lane.wake.set()
    except Exception:
        log.warning("The jobs listener stopped; lanes poll instead", exc_info=True)


def heartbeat(session_factory) -> None:
    """The worker is alive: when and which version (Backstage and /health read it)."""
    import json

    from app.models import ToolSetting

    with session_factory() as db:
        said = json.dumps({"at": datetime.now(UTC).isoformat(), "version": jobs.version(), "who": jobs.me()})
        row = db.get(ToolSetting, "jobs_worker")
        if row is None:
            db.add(ToolSetting(key="jobs_worker", value=said))
        else:
            row.value = said
        db.commit()


def worker_seen(db: Session) -> dict | None:
    """When the worker last beat, and its version (None if it never has)."""
    import json

    from app.models import ToolSetting

    row = db.get(ToolSetting, "jobs_worker")
    try:
        return json.loads(row.value) if row and row.value else None
    except ValueError:
        return None


def wait_for_migrations(engine, head: str, seconds: int = 600) -> None:
    """The worker never migrates: it waits until the web app's deploy has (the database's head is its own)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        with engine.connect() as conn:
            now = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if now == head:
            return
        time.sleep(5)
    raise SystemExit(f"The database is at {now}, not {head}: the worker waits for the web app's migration")


def main() -> None:  # pragma: no cover  (the service's own start; its parts are tested)
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    from app import realtime
    from app.db import SessionLocal, engine

    logging.basicConfig(level=logging.INFO)
    realtime.NOTIFY_ALWAYS = True  # (no listener here: its announcements go through Postgres to the web app's pages)
    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    wait_for_migrations(engine, head)
    stop = threading.Event()
    lanes = start(lambda: Session(engine) if SessionLocal is None else SessionLocal(), stop)

    def stopping(*_):
        log.info("Stopping: no new jobs; the one running has %ss", DRAIN_SECONDS)
        stop.set()

    signal.signal(signal.SIGTERM, stopping)
    signal.signal(signal.SIGINT, stopping)
    while not stop.is_set():
        heartbeat(SessionLocal)
        stop.wait(jobs.BEAT_SECONDS)
    deadline = time.monotonic() + max(DRAIN_SECONDS - 10, 0)
    while any(lane.current for lane in lanes) and time.monotonic() < deadline:
        time.sleep(1)
    for lane in lanes:  # (still running at the drain's end: back to the queue for the next worker)
        if lane.current:
            with SessionLocal() as db:
                jobs.put_back(db, lane.current["id"], lane.current["attempts"])


if __name__ == "__main__":  # pragma: no cover
    main()
