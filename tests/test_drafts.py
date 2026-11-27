"""Claude's drafting on the jobs queue (app/drafts.py; Roadmap item 43, step 6; issue 168: its least tested part): each
step finds its session, closes a run a stopped worker left running, reads a transcript from file storage only inside
the job, and records what went wrong on the session's run rather than failing the job. Claude is never called here:
the drafting itself is a stand-in."""

from sqlalchemy import select

from app import drafts, jobs
from app.importer import import_bundle
from app.models import ExtractionRun, GameSession


def _session(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": 5, "title": "Bells"}]})
    db.flush()
    return db.scalar(select(GameSession))


def test_a_step_for_a_session_that_isnt_there_is_skipped(db):
    for step in drafts.STEPS:
        assert jobs.KINDS[step].run(db, {"session_id": 999999}) == {"skipped": "no such session"}


def test_a_run_a_stopped_worker_left_running_is_closed_when_its_job_starts_again(db, monkeypatch):
    from app import extraction

    s = _session(db)
    db.add(ExtractionRun(session_id=s.id, source="transcript", status="running"))
    db.commit()
    asked = []
    monkeypatch.setattr(extraction, "revise_suggestions", lambda db, s: asked.append(s.id))
    assert jobs.KINDS["revise"].run(db, {"session_id": s.id}) == {"session": s.id} and asked == [s.id]
    left = db.scalar(select(ExtractionRun).where(ExtractionRun.session_id == s.id))
    assert left.status == "error" and left.error == drafts.STALE


def test_a_transcript_not_kept_is_said_on_the_sessions_run_not_a_failed_job(db, monkeypatch):
    from app import session_story

    s = _session(db)
    monkeypatch.setattr(session_story, "text", lambda s: None)
    for step, source in (("read_transcript", "transcript"), ("draft_recap", "recap")):
        assert jobs.KINDS[step].run(db, {"session_id": s.id}) == {"error": "no transcript"}
        run = db.scalar(select(ExtractionRun).where(ExtractionRun.session_id == s.id, ExtractionRun.source == source))
        assert run.status == "error" and "Send it again" in run.error


def test_a_transcript_is_read_inside_the_job_and_drafted_with_its_step(db, monkeypatch):
    from app import extraction, session_story

    s = _session(db)
    monkeypatch.setattr(session_story, "text", lambda s: "The party rang the bell twice.")
    seen = []
    monkeypatch.setattr(extraction, "extract_session", lambda db, s, source, **kw: seen.append((source.text, kw)))
    jobs.KINDS["read_transcript"].run(db, {"session_id": s.id})
    jobs.KINDS["draft_recap"].run(db, {"session_id": s.id, "update": True})
    assert seen == [("The party rang the bell twice.", {"step": "ask"}), ("The party rang the bell twice.", {"step": "tell", "update": True})]


def test_drafting_from_notes_that_cant_be_read_says_why_on_its_run(db, monkeypatch):
    from app import admin_sessions
    from app.extraction import ExtractionError

    s = _session(db)
    monkeypatch.setattr(admin_sessions, "source_for", lambda db, s: (_ for _ in ()).throw(ExtractionError("No notes for this session.")))
    assert jobs.KINDS["draft_notes"].run(db, {"session_id": s.id}) == {"error": "No notes for this session."}
    assert db.scalar(select(ExtractionRun.error).where(ExtractionRun.session_id == s.id)) == "No notes for this session."


def test_asking_for_a_step_adds_one_job_and_asking_again_while_it_runs_runs_it_after(db, monkeypatch):
    """Issue 153 for drafts: a resent transcript while its read runs isn't lost."""
    monkeypatch.setattr(drafts, "_run_here_if_nobody_will", lambda: None)
    s = _session(db)
    first = drafts.start(db, "read_transcript", s.id, by="dm")
    got = jobs.claim(db, drafts.QUEUE, "w1")
    assert got["id"] == first and drafts.start(db, "read_transcript", s.id, by="dm") == first
    assert jobs.finish(db, first, got["attempts"], {}) and drafts.waiting_sessions(db) == {s.id}  # (back in line: it runs again)
