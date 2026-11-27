"""Background jobs (app/jobs.py; Roadmap item 43, Brett's pick LB1, Nov 25): one at a time per queue, never twice the
same, given up on when its worker goes silent, and a late worker can't overwrite a later try."""

import threading
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app import jobs


@pytest.fixture
def kinds(monkeypatch):
    monkeypatch.setattr(jobs, "KINDS", {})
    jobs.register(jobs.Kind("test_a", "lane", lambda db, p: {"ok": True}, max_attempts=2, backoff=(5,)))
    jobs.register(jobs.Kind("test_b", "lane", lambda db, p: None, keep_done=timedelta(hours=1)))
    return jobs.KINDS


def _row(db, job_id):
    return db.execute(text("SELECT * FROM jobs WHERE id = :id"), {"id": job_id}).one()


def test_the_same_job_is_never_queued_twice(db, kinds):
    a, new_a = jobs.enqueue(db, "test_a", {"character": 7}, "char:7")
    b, new_b = jobs.enqueue(db, "test_a", {"character": 7}, "char:7", priority=10)
    assert a == b and new_a and not new_b and _row(db, a).priority == 10  # (asked again sooner: it moves up)
    c, _ = jobs.enqueue(db, "test_a", {"character": 8}, "char:8")
    assert c != a


def test_a_worker_takes_the_most_urgent_known_job_it_may_run_now(db, kinds):
    late, _ = jobs.enqueue(db, "test_a", {}, "late", priority=50, run_at=datetime.now(UTC) + timedelta(minutes=5))
    low, _ = jobs.enqueue(db, "test_a", {}, "low", priority=0)
    high, _ = jobs.enqueue(db, "test_b", {}, "high", priority=10)
    db.execute(text("INSERT INTO jobs (kind, queue, priority) VALUES ('from_a_newer_worker', 'lane', 99)"))
    got = jobs.claim(db, "lane", "w1")
    assert got["id"] == high and got["attempts"] == 1 and _row(db, high).state == "running"
    assert jobs.claim(db, "lane", "w1")["id"] == low
    assert jobs.claim(db, "lane", "w1") is None  # (the newer kind waits; the late one isn't due)
    assert _row(db, late).state == "queued"


def test_a_job_given_up_on_cant_be_finished_by_its_old_worker(db, kinds):
    job_id, _ = jobs.enqueue(db, "test_a", {}, "fence")
    first = jobs.claim(db, "lane", "w1")
    db.execute(text("UPDATE jobs SET heartbeat_at = now() - interval '2 minutes' WHERE id = :id"), {"id": job_id})
    assert jobs.reap(db) == 1 and _row(db, job_id).state == "queued" and _row(db, job_id).error == "Interrupted"
    second = jobs.claim(db, "lane", "w2")
    assert second["attempts"] == 2
    assert not jobs.finish(db, job_id, first["attempts"], {"late": True}) and not jobs.beat(db, job_id, first["attempts"])
    assert jobs.finish(db, job_id, second["attempts"], {"ok": True}) and _row(db, job_id).state == "done"


def test_a_failure_tries_again_after_its_backoff_then_fails(db, kinds):
    job_id, _ = jobs.enqueue(db, "test_a", {}, "retry")
    got = jobs.claim(db, "lane", "w1")
    assert jobs.fail(db, job_id, got["attempts"], "D&D Beyond said no") == "queued"
    row = _row(db, job_id)
    assert row.run_at > datetime.now(UTC) + timedelta(seconds=3) and jobs.claim(db, "lane", "w1") is None  # (waiting out its backoff)
    db.execute(text("UPDATE jobs SET run_at = now() WHERE id = :id"), {"id": job_id})
    got = jobs.claim(db, "lane", "w1")
    assert jobs.fail(db, job_id, got["attempts"], "still no") == "failed" and _row(db, job_id).finished_at is not None
    # a job that ran past its last attempt's lease fails rather than going round again
    j2, _ = jobs.enqueue(db, "test_a", {}, "silent")
    db.execute(text("UPDATE jobs SET state = 'running', attempts = 2, heartbeat_at = now() - interval '5 minutes' WHERE id = :id"), {"id": j2})
    jobs.reap(db)
    assert _row(db, j2).state == "failed"


def test_a_stopping_worker_puts_its_job_back_uncounted(db, kinds):
    """Issue 155: put back, its try is given back as one more allowed, but its number stays, so the next worker's try
    is another number and the old worker, still running for a moment, can't finish over it."""
    job_id, _ = jobs.enqueue(db, "test_a", {}, "deploy")
    got = jobs.claim(db, "lane", "w1")
    assert jobs.put_back(db, job_id, got["attempts"])
    row = _row(db, job_id)
    assert row.state == "queued" and row.max_attempts == 3  # (2, and the try given back)
    again = jobs.claim(db, "lane", "w2")
    assert again["attempts"] == 2 and not jobs.finish(db, job_id, got["attempts"], {"old": True})  # (the old worker fenced out)
    assert jobs.finish(db, job_id, again["attempts"], {"new": True}) and _row(db, job_id).result == {"new": True}


def test_asked_again_while_it_runs_a_draft_runs_the_newer_request_after_it(db, kinds):
    """Issue 153: a resent transcript or Start over while a draft runs was folded into the run under way and lost. A
    kind that wants it keeps the newer request and runs it once this one ends; one waiting takes the newer payload; a
    read (no again_if_asked) needn't run twice."""
    jobs.register(jobs.Kind("test_draft", "lane", lambda db, p: {"ok": True}, max_attempts=2, again_if_asked=True))
    job_id, _ = jobs.enqueue(db, "test_draft", {"session": 1, "update": False}, "draft:1")
    got = jobs.claim(db, "lane", "w1")
    same, new = jobs.enqueue(db, "test_draft", {"session": 1, "update": True}, "draft:1")
    assert same == job_id and not new
    assert jobs.finish(db, job_id, got["attempts"], {"ok": True})
    row = _row(db, job_id)
    assert row.state == "queued" and row.payload == {"session": 1, "update": True} and row.rerun is None and row.attempts == 0
    waiting, _ = jobs.enqueue(db, "test_a", {"v": 1}, "read:1")
    jobs.enqueue(db, "test_a", {"v": 2}, "read:1")
    assert _row(db, waiting).payload == {"v": 2}  # (waiting: the newer request's)
    read = jobs.claim(db, "lane", "w1")
    while read["id"] != waiting:
        jobs.finish(db, read["id"], read["attempts"], {})
        read = jobs.claim(db, "lane", "w1")
    jobs.enqueue(db, "test_a", {"v": 3}, "read:1")
    assert jobs.finish(db, waiting, read["attempts"], {}) and _row(db, waiting).state == "done"  # (a read: answered by the one under way)


def test_past_its_time_limit_a_job_fails_rather_than_run_twice(db, kinds):
    """Issue 154: a draft past its 20 minutes was put back while its worker still ran it, and run (and paid for) twice.
    Past its kind's limit while still beating, it fails; silent, it's put back as before."""
    jobs.register(jobs.Kind("test_slow", "lane", lambda db, p: None, max_attempts=3, timeout=timedelta(minutes=20)))
    slow, _ = jobs.enqueue(db, "test_slow", {}, "slow")
    got = jobs.claim(db, "lane", "w1")
    db.execute(text("UPDATE jobs SET started_at = now() - interval '25 minutes', heartbeat_at = now() WHERE id = :id"), {"id": slow})
    db.commit()
    assert jobs.reap(db) == 1 and _row(db, slow).state == "failed" and _row(db, slow).error == "Timed out"
    assert not jobs.finish(db, slow, got["attempts"], {})  # (its worker, finishing late, is fenced out)
    quiet, _ = jobs.enqueue(db, "test_slow", {}, "quiet")
    jobs.claim(db, "lane", "w1")
    db.execute(text("UPDATE jobs SET heartbeat_at = now() - interval '2 minutes' WHERE id = :id"), {"id": quiet})
    db.commit()
    assert jobs.reap(db) == 1 and _row(db, quiet).state == "queued"


def test_a_jobs_story_keeps_each_try_and_who_pressed_retry_or_cancel(db, kinds):
    """The Sync page (Roadmap item 44, Brett's picks SQ4 and the story of each row): each try as it ended, with its
    error, and Retry and Cancel with who pressed them; Retry starts its tries afresh and goes first."""
    job_id, _ = jobs.enqueue(db, "test_a", {}, "story")
    got = jobs.claim(db, "lane", "w1")
    jobs.fail(db, job_id, got["attempts"], "D&D Beyond answered 503")
    db.execute(text("UPDATE jobs SET run_at = now() WHERE id = :id"), {"id": job_id})
    got = jobs.claim(db, "lane", "w1")
    jobs.fail(db, job_id, got["attempts"], "503 again")
    story = _row(db, job_id).story
    assert [(s["n"], s["ended"], s["error"]) for s in story] == [(1, "again", "D&D Beyond answered 503"), (2, "failed", "503 again")]
    assert all(s["took"] >= 0 for s in story)
    assert jobs.retry(db, job_id, "Brett")
    row = _row(db, job_id)
    assert row.state == "queued" and row.attempts == 0 and row.priority >= 10 and row.story[-1]["did"] == "retry" and row.story[-1]["by"] == "Brett"
    got = jobs.claim(db, "lane", "w1")
    assert not jobs.retry(db, job_id, "Brett") and not jobs.cancel(db, job_id, "Brett")  # (running: neither)
    jobs.finish(db, job_id, got["attempts"], {"ok": True})
    assert _row(db, job_id).story[-1]["ended"] == "done"
    waiting, _ = jobs.enqueue(db, "test_a", {}, "waiting")
    assert jobs.cancel(db, waiting, "Brett") and _row(db, waiting).state == "cancelled" and _row(db, waiting).story[-1]["did"] == "cancel"
    stopped, _ = jobs.enqueue(db, "test_a", {}, "stopped")
    got = jobs.claim(db, "lane", "w1")
    jobs.put_back(db, stopped, got["attempts"])
    assert _row(db, stopped).story[-1]["ended"] == "stopped"


def test_finished_jobs_are_kept_as_long_as_their_kind_says(db, kinds):
    old_done, _ = jobs.enqueue(db, "test_b", {}, "old")
    new_done, _ = jobs.enqueue(db, "test_b", {}, "new")
    old_failed, _ = jobs.enqueue(db, "test_a", {}, "failed")
    db.execute(text("UPDATE jobs SET state = 'done', finished_at = now() - interval '2 hours' WHERE id = :id"), {"id": old_done})
    db.execute(text("UPDATE jobs SET state = 'done', finished_at = now() - interval '10 minutes' WHERE id = :id"), {"id": new_done})
    db.execute(text("UPDATE jobs SET state = 'failed', finished_at = now() - interval '20 days' WHERE id = :id"), {"id": old_failed})
    assert jobs.sweep(db) == 1
    assert db.execute(text("SELECT count(*) FROM jobs WHERE id IN (:a, :b, :c)"), {"a": old_done, "b": new_done, "c": old_failed}).scalar() == 2
    assert jobs.counts(db) == {"done": 1, "failed": 1}


def test_two_workers_never_take_the_same_job(db_engine, kinds):
    """SKIP LOCKED: during a deploy an old and a new worker run side by side; each takes a different job."""
    with Session(db_engine) as setup:
        ids = [jobs.enqueue(setup, "test_a", {}, f"both:{n}")[0] for n in range(2)]
        setup.commit()
    try:
        with db_engine.connect() as hold:
            locked = hold.begin()
            hold.execute(text("SELECT id FROM jobs WHERE id = :id FOR UPDATE"), {"id": ids[0]})  # (one being taken right now)
            with Session(db_engine) as other:
                got = jobs.claim(other, "lane", "w2")
            locked.rollback()
        assert got["id"] == ids[1]
    finally:
        with Session(db_engine) as tidy:
            tidy.execute(text("DELETE FROM jobs WHERE dedup_key LIKE 'both:%'"))
            tidy.commit()


def test_a_lane_runs_a_job_and_records_how_it_went(db, kinds, monkeypatch):
    """app/worker.py: a lane takes the next job, runs it, and finishes it (or fails it, kept for a retry)."""
    import contextlib
    import threading

    from app import worker

    said = []
    monkeypatch.setattr(worker, "_announce", lambda job, state: said.append((job["kind"], state)))
    jobs.register(jobs.Kind("test_boom", "lane", lambda db, p: 1 / 0, max_attempts=2))
    lane = worker.Lane("lane", lambda: contextlib.nullcontext(db), threading.Event(), "w1")
    ok, _ = jobs.enqueue(db, "test_a", {}, "runs", priority=5)
    boom, _ = jobs.enqueue(db, "test_boom", {}, "boom")
    assert lane.run_once() and _row(db, ok).state == "done" and _row(db, ok).result == {"ok": True}
    assert lane.run_once() and _row(db, boom).state == "queued" and "ZeroDivisionError" in _row(db, boom).error
    assert said == [("test_a", "done"), ("test_boom", "queued")] and lane.current is None
    assert not lane.run_once()  # (the failed one waits out its backoff)


def test_the_worker_says_it_is_alive_and_announces_without_a_listener(db, kinds, monkeypatch):
    import contextlib

    from app import realtime, worker

    worker.heartbeat(lambda: contextlib.nullcontext(db))
    seen = worker.worker_seen(db)
    assert seen and seen["at"] and "who" in seen
    sent = []
    monkeypatch.setattr(realtime, "deliver", lambda c, m: sent.append(c))
    monkeypatch.setattr(realtime, "_bus", {"up": False})
    monkeypatch.setattr(realtime, "NOTIFY_ALWAYS", True)
    realtime.publish(3, "job", id=1, state="done")  # (through Postgres: nothing delivered on this copy directly)
    assert sent == []
    monkeypatch.setattr(realtime, "NOTIFY_ALWAYS", False)
    realtime.publish(3, "job", id=1, state="done")
    assert sent == [3]
    worker._announce({"id": 1, "kind": "test_a", "campaign_id": 3}, "done")  # (as a lane says it: a job's kind is `job`)
    assert sent == [3, 3]


def test_nothing_starts_without_a_kind_of_job(monkeypatch):
    import threading

    from app import worker

    monkeypatch.setattr(jobs, "KINDS", {})
    monkeypatch.setattr(jobs, "load_kinds", lambda: None)
    assert worker.start(lambda: None, threading.Event()) == [] and worker.runner() in ("inline", "worker")


def test_a_lane_that_cant_reach_its_queue_says_so_once_and_waits_longer(monkeypatch, caplog):
    """The database away, or a deploy's migration not run yet: one error for Sentry, not one every five seconds."""
    import threading

    from app import worker

    stop, waits = threading.Event(), []
    lane = worker.Lane("lane", lambda: None, stop, "w1")

    def broken():
        if len(waits) >= 4:
            stop.set()
        raise RuntimeError("relation jobs does not exist")

    monkeypatch.setattr(lane, "run_once", broken)
    monkeypatch.setattr(lane.wake, "wait", lambda s: waits.append(s))
    with caplog.at_level("ERROR", logger="askdnd.worker"):
        lane.loop()
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1
    assert waits[:3] == [10, 20, 40] and all(w <= 60 for w in waits)


def test_the_web_app_reads_dnd_beyond_itself_while_the_worker_is_away(db, monkeypatch, caplog):
    """With jobs in the separate worker: quiet 90 seconds, the web app serves the D&D Beyond reads (drafts wait); back,
    it stops; away five minutes, one error for Sentry."""
    import contextlib
    from datetime import timedelta

    from app import worker

    started = []
    monkeypatch.setattr(worker.threading, "Thread", lambda target, name, daemon: type("T", (), {"start": lambda self: started.append(name)})())
    watch = worker.Watch(lambda: contextlib.nullcontext(db), "web")
    assert watch.look() == "covering" and started == ["jobs-ddb-fallback"]  # (never heard from)
    worker.heartbeat(lambda: contextlib.nullcontext(db))
    assert watch.look() == "worker" and watch.covering is None
    assert watch.look(datetime.now(UTC) + timedelta(seconds=60)) == "same"
    caplog.clear()
    with caplog.at_level("ERROR", logger="askdnd.worker"):
        assert watch.look(datetime.now(UTC) + timedelta(seconds=100)) == "covering"
        watch.look(datetime.now(UTC) + timedelta(minutes=6))
        watch.look(datetime.now(UTC) + timedelta(minutes=7))
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1


def test_a_worker_waiting_for_its_deploys_migration_is_covered_for_but_not_reported(db, monkeypatch, caplog):
    """Issue 133: a deploy with a migration starts the new worker before the web app has migrated; it waits, saying so,
    and the web app covers for it without telling Sentry it's gone. Once it stops saying so, away is away."""
    import contextlib
    from datetime import timedelta

    from app import worker

    monkeypatch.setattr(worker.threading, "Thread", lambda target, name, daemon: type("T", (), {"start": lambda self: None})())
    own = lambda: contextlib.nullcontext(db)
    t0 = datetime.now(UTC)
    worker.heartbeat(own, now=t0)
    watch = worker.Watch(own, "web")
    assert watch.look(t0) == "same"  # (heard from: the worker does the reads)
    later = t0 + timedelta(minutes=6)
    worker.heartbeat(own, waiting="migration", now=later - timedelta(seconds=10))
    assert worker.worker_seen(db)["at"] == t0.isoformat()  # (the last working beat: the web app still covers)
    with caplog.at_level("ERROR", logger="askdnd.worker"):
        assert watch.look(later) == "covering"
        assert not [r for r in caplog.records if r.levelname == "ERROR"]
        watch.look(later + timedelta(minutes=3))  # (it stopped saying so: away)
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1


def test_a_worker_waiting_too_long_for_a_migration_is_away_after_all(db, monkeypatch, caplog):
    """Issue 133's review: a web deploy that never migrates leaves the worker waiting through every restart; past
    WAIT_BELIEVED since it began waiting, Sentry hears it's away even while it keeps saying so."""
    import contextlib
    from datetime import timedelta

    from app import worker

    monkeypatch.setattr(worker.threading, "Thread", lambda target, name, daemon: type("T", (), {"start": lambda self: None})())
    own = lambda: contextlib.nullcontext(db)
    t0 = datetime.now(UTC)
    worker.heartbeat(own, now=t0)
    watch = worker.Watch(own, "web")
    with caplog.at_level("ERROR", logger="askdnd.worker"):
        for minutes in range(1, 15):
            worker.heartbeat(own, waiting="migration", now=t0 + timedelta(minutes=minutes))
            watch.look(t0 + timedelta(minutes=minutes, seconds=5))
        assert not [r for r in caplog.records if r.levelname == "ERROR"]
        assert worker.worker_seen(db)["waiting_since"] == (t0 + timedelta(minutes=1)).isoformat()
        for minutes in range(15, 18):
            worker.heartbeat(own, waiting="migration", now=t0 + timedelta(minutes=minutes))
            watch.look(t0 + timedelta(minutes=minutes, seconds=5))
    assert len([r for r in caplog.records if r.levelname == "ERROR"]) == 1


def test_waiting_for_the_migration_says_so_until_it_lands(monkeypatch):
    """Issue 133: the worker's wait for the web app's migration beats as waiting, then returns once the head is its own."""
    from app import worker

    versions = iter(["old", "old", "old", "new"])

    class Conn:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def execute(self, *a):
            return type("R", (), {"scalar": lambda self: next(versions)})()

    engine = type("E", (), {"connect": lambda self: Conn()})()
    beats, clock = [], [0.0]
    monkeypatch.setattr(worker.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s))
    monkeypatch.setattr(worker.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(worker.jobs, "BEAT_SECONDS", 10)
    worker.wait_for_migrations(engine, "new", beat=lambda: beats.append(clock[0]))
    assert beats == [0.0, 10.0]  # (every BEAT_SECONDS while it waits, never once it's in)


def test_health_says_how_jobs_run(db, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)
    monkeypatch.setenv("JOBS_RUNNER", "worker")
    got = client.get("/health").json()
    assert got["jobs"] == "worker" and "quiet_seconds" in got["worker"]
    monkeypatch.setenv("JOBS_RUNNER", "inline")
    assert "worker" not in client.get("/health").json()


def test_a_job_that_ran_is_never_failed_because_saying_so_didnt_save(db, kinds, monkeypatch):
    """Issue 154: a failed finish() was taken for the job failing, so it was put back and run (and paid for) again. Its
    finish is tried again instead; the job itself is never failed for it. A lane on a request's own session doesn't
    beat on it (issue 156)."""
    import contextlib
    import threading

    from app import worker

    monkeypatch.setattr(worker, "_announce", lambda job, state: None)
    monkeypatch.setattr(worker.time, "sleep", lambda s: None)
    real, calls = jobs.finish, []

    def flaky(db, job_id, attempts, result=None):
        calls.append(job_id)
        if len(calls) == 1:
            raise RuntimeError("the database blinked")
        return real(db, job_id, attempts, result)

    monkeypatch.setattr(worker.jobs, "finish", flaky)
    started = []
    monkeypatch.setattr(worker.threading, "Thread", lambda target, args=(), daemon=False: type("T", (), {"start": lambda self: started.append(1)})())
    lane = worker.Lane("lane", lambda: contextlib.nullcontext(db), threading.Event(), "w1", beats=False)
    ok, _ = jobs.enqueue(db, "test_a", {}, "flaky")
    assert lane.run_once() and _row(db, ok).state == "done" and len(calls) == 2 and lane.last == ("test_a", "done")
    assert started == []  # (no beat thread on the request's session)


def test_while_covering_for_the_worker_the_web_app_gives_up_on_its_silent_jobs(db, kinds, monkeypatch):
    """Issue 152: with the worker away nothing gave up on the jobs it held, so a read it was running stayed running for
    good and that sheet was never read again. While the web app covers, it does."""
    import contextlib

    from app import worker

    monkeypatch.setattr(worker.threading, "Thread", lambda target, name, daemon: type("T", (), {"start": lambda self: None})())
    held, _ = jobs.enqueue(db, "test_a", {}, "held")
    jobs.claim(db, "lane", "dead-worker")
    db.execute(text("UPDATE jobs SET heartbeat_at = now() - interval '5 minutes' WHERE id = :id"), {"id": held})
    db.commit()
    stop = threading.Event()
    watch = worker.Watch(lambda: contextlib.nullcontext(db), "web")
    looks = iter([False, True])
    monkeypatch.setattr(stop, "wait", lambda s: next(looks))
    watch.run(stop)
    assert _row(db, held).state == "queued"  # (given up on, back in line for the web app's own lane)
