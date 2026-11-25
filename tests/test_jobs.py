"""Background jobs (app/jobs.py; Roadmap item 43, Brett's pick LB1, Nov 25): one at a time per queue, never twice the
same, given up on when its worker goes silent, and a late worker can't overwrite a later try."""

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
    job_id, _ = jobs.enqueue(db, "test_a", {}, "deploy")
    got = jobs.claim(db, "lane", "w1")
    assert jobs.put_back(db, job_id, got["attempts"])
    row = _row(db, job_id)
    assert row.state == "queued" and row.attempts == 0 and jobs.claim(db, "lane", "w2")["attempts"] == 1


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
