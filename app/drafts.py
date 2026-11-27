"""Claude's drafting, through the jobs queue (Roadmap item 43, step 6; the backend look-back's LB1, Brett's pick A and his
OK on the scope, Nov 25; docs/plans/2026-11-25-jobs-and-worker.md).

Each piece of drafting is a job on the `draft` queue, one at a time as before (it keeps spending and the order
predictable): drafting a session from notes or a written account, a transcript's first read (questions and suggested
World updates), putting answers into the suggestions, and drafting the recap. A job carries the session's id only,
never words: a transcript is read from file storage inside the job (`session_story.text`), never the database
(CLAUDE.md › Privacy). The work itself is unchanged (`extraction.extract_session`, `revise_suggestions`), and so is
the spending limit it keeps.

A deploy no longer loses a draft for good: a job whose worker stopped is taken again once (its lease runs out), and
the run it left half done is marked interrupted first, so Sessions never shows two at once. Asking again while one is
waiting or running for the same session and step adds nothing.
"""

from datetime import timedelta

from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app import jobs

QUEUE = "draft"
STEPS = ("draft_notes", "read_transcript", "revise", "draft_recap")
STALE = "Interrupted (the server restarted): tried again."


def _close_stale_runs(db: Session, session_id: int) -> None:
    """A run of this session's still marked running when its job starts was left by a worker that stopped (the draft
    lane runs one job at a time): it's over."""
    from app.models import NON_DRAFTING_SOURCES, ExtractionRun

    db.execute(update(ExtractionRun).where(ExtractionRun.session_id == session_id, ExtractionRun.status == "running",
                                           ExtractionRun.source.notin_(NON_DRAFTING_SOURCES)).values(status="error", error=STALE))
    db.commit()


def _session(db: Session, payload: dict):
    from app.models import GameSession

    s = db.get(GameSession, int(payload.get("session_id") or 0))
    if s is not None:
        _close_stale_runs(db, s.id)
    return s


def _draft_notes(db: Session, payload: dict) -> dict:
    from app import admin_sessions
    from app.extraction import ExtractionError, extract_session
    from app.models import ExtractionRun

    s = _session(db, payload)
    if s is None:
        return {"skipped": "no such session"}
    try:
        source, background, images = admin_sessions.source_for(db, s)
    except ExtractionError as e:
        db.add(ExtractionRun(session_id=s.id, source=s.source, status="error", error=str(e)))
        db.commit()
        return {"error": str(e)[:200]}
    extract_session(db, s, source, background=background, background_images=images)
    return {"session": s.id}


def _read_transcript(db: Session, payload: dict) -> dict:
    from app import session_story
    from app.extraction import Source, extract_session
    from app.models import ExtractionRun

    s = _session(db, payload)
    if s is None:
        return {"skipped": "no such session"}
    words = session_story.text(s)  # (from file storage, inside the job: the payload never holds the transcript)
    if words is None:
        db.add(ExtractionRun(session_id=s.id, source="transcript", status="error",
                             error="askdnd doesn't have this session's transcript. Send it again from the Processor."))
        db.commit()
        return {"error": "no transcript"}
    extract_session(db, s, Source("transcript", words), step="ask")
    return {"session": s.id}


def _revise(db: Session, payload: dict) -> dict:
    from app.extraction import revise_suggestions

    s = _session(db, payload)
    if s is None:
        return {"skipped": "no such session"}
    revise_suggestions(db, s)
    return {"session": s.id}


def _draft_recap(db: Session, payload: dict) -> dict:
    from app import session_story
    from app.extraction import Source, extract_session
    from app.models import ExtractionRun

    s = _session(db, payload)
    if s is None:
        return {"skipped": "no such session"}
    words = session_story.text(s)
    if words is None:
        db.add(ExtractionRun(session_id=s.id, source="recap", status="error",
                             error="askdnd doesn't have this session's transcript. Send it again from the Processor."))
        db.commit()
        return {"error": "no transcript"}
    extract_session(db, s, Source("transcript", words), step="tell", update=bool(payload.get("update")))
    return {"session": s.id}


_RUN = {"draft_notes": _draft_notes, "read_transcript": _read_transcript, "revise": _revise, "draft_recap": _draft_recap}
for _step in STEPS:  # (tried once more only after an interruption: a failure Claude reports is kept on its run, not retried)
    jobs.register(jobs.Kind(_step, QUEUE, _RUN[_step], max_attempts=2, timeout=timedelta(minutes=20), backoff=(0,),
                            keep_done=timedelta(days=90), again_if_asked=True))  # (asked again while it runs, a resent
    # transcript or Start over: run once more after it, issue 153)


def start(db: Session, step: str, session_id: int, *, by: str = "", **extra) -> int:
    """Ask for a piece of drafting (committed here, so the lane sees it at once). Returns the job's id."""
    from app.models import GameSession

    s = db.get(GameSession, session_id)
    job_id, _ = jobs.enqueue(db, step, {"session_id": session_id, **extra}, f"draft:{step}:{session_id}",
                             campaign_id=s.campaign_id if s else None, label=f"{step.replace('_', ' ').capitalize()}: session {session_id}"[:200],
                             by=by)
    db.commit()
    _run_here_if_nobody_will()
    return job_id


def _run_here_if_nobody_will() -> None:
    """Where no lane of this copy serves the queue and jobs run here (a copy started without its lanes), a thread takes
    the queue until it's empty, as the old drafting thread did. Tests replace the starters, so none runs there."""
    import threading

    from app import worker

    if worker.runner() != "inline" or worker.serving(QUEUE):
        return
    from app.db import SessionLocal

    lane = worker.Lane(QUEUE, SessionLocal, threading.Event(), jobs.me())
    threading.Thread(target=lambda: [None for _ in iter(lane.run_once, False)], name="drafts-here", daemon=True).start()


def waiting_sessions(db: Session) -> set[int]:
    """Sessions with drafting waiting or running on the queue (Sessions shows them as drafting)."""
    rows = db.execute(text("SELECT payload FROM jobs WHERE queue = :q AND state IN ('queued', 'running')"), {"q": QUEUE}).all()
    return {int(r.payload["session_id"]) for r in rows if r.payload and r.payload.get("session_id")}


def busy(db: Session) -> bool:
    """Whether Claude is drafting, or has drafting waiting."""
    return db.execute(text("SELECT 1 FROM jobs WHERE queue = :q AND state IN ('queued', 'running') LIMIT 1"), {"q": QUEUE}).first() is not None
