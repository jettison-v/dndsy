"""Backstage › Tuning › Sync (app/sync_page.py; Roadmap item 44, Brett's picks SQ1–SQ6 on docs/mockups/sync-queue/,
Nov 25): reads, changes and drafts in one list, each opening to its story, Retry and Cancel kept with who pressed them,
and what needs someone said once, here and on Overview."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from app import jobs, sheet_reads, sync_page
from app.models import BridgeBatch, BridgeIntent


@pytest.fixture
def cole(db):
    from app.importer import import_bundle
    from tests.table_setup import BUNDLE, char

    import_bundle(db, BUNDLE)
    db.commit()
    return char(db, "Cole")


def _read(db, ch, state="queued", error="", ago=timedelta(0), by="", priority=sheet_reads.PAGE):
    job_id, _ = jobs.enqueue(db, sheet_reads.KIND, {"character_id": ch.id}, f"ddb:char:{ch.id}:{state}:{ago}", priority=priority, by=by)
    db.execute(text("UPDATE jobs SET state = :s, error = :e, attempts = :n, created_at = now() - :ago, started_at = now() - :ago, "
                    "finished_at = CASE WHEN :ended THEN now() - :ago + interval '2 seconds' END WHERE id = :id"),
               {"s": state, "e": error, "n": 0 if state == "queued" else 3, "ended": state in ("done", "failed"), "ago": ago, "id": job_id})
    return job_id


def test_reads_and_changes_are_one_list_with_what_needs_someone(db, cole):
    """A failed read and a change waiting over 10 minutes are trouble and said once; done work over a day old and failed
    work over 30 days old leave the list."""
    failed = _read(db, cole, "failed", "D&D Beyond answered 503")
    _read(db, cole, "done", ago=timedelta(days=2))
    _read(db, cole, "failed", "long ago", ago=timedelta(days=31))
    done = _read(db, cole, "done", ago=timedelta(hours=2), by="Brett", priority=sheet_reads.PRESS)
    late = BridgeIntent(character_id=cole.id, kind="hp", label="Hit points 31 → 24", state="waiting", data={})
    db.add(late)
    db.flush()
    db.execute(text("UPDATE bridge_intents SET created_at = now() - interval '15 minutes' WHERE id = :id"), {"id": late.id})
    db.expire_all()
    listed = {r["key"]: r for r in sync_page.rows(db)}
    assert set(listed) == {f"j{failed}", f"j{done}", f"c{late.id}"}
    assert listed[f"j{failed}"]["trouble"] and listed[f"c{late.id}"]["trouble"] and listed[f"c{late.id}"]["late"]
    assert not listed[f"j{done}"]["trouble"] and listed[f"j{done}"]["why"] == "asked by Brett" and listed[f"j{done}"]["took"] == "2.0 s"
    assert "trouble" in listed[f"j{failed}"]["views"].split() and "read" in listed[f"j{failed}"]["views"].split()
    n = sync_page.needs(db)
    assert n["tone"] == "broken" and "1 failed" in n["says"] and "waiting over 10 minutes" in n["says"]


def test_nothing_wrong_says_nothing(db, cole):
    _read(db, cole, "done")
    assert sync_page.needs(db) is None and sync_page.card_state(db)[1] == "ok"


def test_a_reads_story_has_each_try_and_retry_says_who(admin, db, cole):
    job_id, _ = jobs.enqueue(db, sheet_reads.KIND, {"character_id": cole.id}, "story", by="nobody had it open", priority=sheet_reads.UNWATCHED)
    db.commit()
    for error in ("D&D Beyond answered 503", "503 again", "503 a third time"):
        got = jobs.claim(db, sheet_reads.QUEUE, "w")
        jobs.fail(db, job_id, got["attempts"], error)
        db.execute(text("UPDATE jobs SET run_at = now() WHERE id = :id"), {"id": job_id})
    db.commit()
    s = sync_page.story(db, f"j{job_id}")
    words = [st["words"] for st in s["steps"]]
    assert words[0] == "Asked: nobody had it open" and s["state"] == "failed" and s["retry"] and not s["cancel"]
    assert [st["error"] for st in s["steps"][1:]] == ["D&D Beyond answered 503", "503 again", "503 a third time"]
    page = admin.get(f"/manage/sync/j{job_id}")
    assert page.status_code == 200 and 'data-do="sync-retry"' in page.text and "503 a third time" in page.text
    r = admin.post(f"/manage/sync/j{job_id}/retry", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/manage/sync"
    db.expire_all()
    s = sync_page.story(db, f"j{job_id}")
    assert s["state"] == "queued" and s["steps"][-1]["words"].startswith("Retried by")


def test_a_waiting_change_can_be_cancelled_and_a_stopped_one_retried(admin, db, cole):
    it = BridgeIntent(character_id=cole.id, kind="hp", label="Hit points 31 → 24", state="waiting", data={})
    db.add(it)
    db.flush()
    db.add(BridgeBatch(character_id=cole.id, intents=[it.id], state="stopped", attempts=2, error="D&D Beyond changed meanwhile"))
    db.commit()
    s = sync_page.story(db, f"c{it.id}")
    assert s["cancel"] and not s["retry"] and any("2 tries" in st["words"] for st in s["steps"])
    admin.post(f"/manage/sync/c{it.id}/cancel")
    db.expire_all()
    assert db.get(BridgeIntent, it.id).state == "dismissed" and db.get(BridgeIntent, it.id).data["sync"][-1]["did"] == "cancel"
    stuck = BridgeIntent(character_id=cole.id, kind="hp", label="Drank a Potion of Healing", state="not_yet", data={}, error="D&D Beyond held 21, not 17")
    db.add(stuck)
    db.commit()
    assert sync_page.needs(db)["tone"] == "broken"
    admin.post(f"/manage/sync/c{stuck.id}/retry")
    db.expire_all()
    assert db.get(BridgeIntent, stuck.id).state == "waiting"
    r = admin.post(f"/manage/sync/c{stuck.id}/retry", follow_redirects=False)  # (already waiting: nothing to retry)
    assert r.status_code == 303 and db.get(BridgeIntent, stuck.id).data["sync"][-1]["did"] == "retry"


def test_a_standing_rule_the_sync_page_is_for_admins(dm, db):
    """A standing rule (Brett, Nov 25, the sync queue's pick SQ1: Backstage's askdnd-wide pages are admins' alone)."""
    assert dm.get("/manage/sync", follow_redirects=False).status_code in (303, 403)
    assert dm.post("/manage/sync/j1/retry", follow_redirects=False).status_code in (303, 403)


def test_the_page_and_overview_say_what_needs_someone(admin, db, cole):
    _read(db, cole, "failed", "D&D Beyond answered 503")
    db.commit()
    page = admin.get("/manage/sync").text
    assert 'data-needs="sync"' in page and 'data-ls-start="trouble"' in page and 'data-state="failed"' in page
    assert 'data-needs="sync"' in admin.get("/manage/askdnd").text
    assert 'data-item="sync"' in admin.get("/manage/sync").text or "/manage/sync" in admin.get("/manage/askdnd").text


def test_an_unknown_row_is_not_found(admin):
    assert admin.get("/manage/sync/x1").status_code == 404 and admin.get("/manage/sync/j999999").status_code == 404


def test_its_states_come_from_the_one_key():
    from app.states import STATES

    assert all(s in STATES for s in ("queued", "running", "done", "failed", "not yet", "cancelled"))
    assert datetime.now(UTC)  # (the page's times are written in UTC for app.js to show in the reader's own)


def test_retry_joins_the_same_work_already_on_its_way(db, cole):
    """The review of #526: a failed read retried while a newer read of the same sheet waits used to break the
    one-at-a-time rule (a 500). The newer one goes first instead, the press kept on both."""
    old = _read(db, cole, "failed", "503")
    db.execute(text("UPDATE jobs SET dedup_key = 'ddb:char:x' WHERE id = :id"), {"id": old})
    newer, _ = jobs.enqueue(db, sheet_reads.KIND, {"character_id": cole.id}, "ddb:char:x", priority=sheet_reads.UNWATCHED)
    assert jobs.retry(db, old, "Brett")
    rows = {r.id: r for r in db.execute(text("SELECT * FROM jobs WHERE id IN (:a, :b)"), {"a": old, "b": newer})}
    assert rows[old].state == "failed" and rows[newer].priority >= 10
    assert rows[old].story[-1]["did"] == "retry" and rows[newer].story[-1]["by"] == "Brett"


def test_a_failure_since_put_right_needs_no_one_and_test_campaigns_never(db, cole, monkeypatch):
    """The review of #526: a 2 am failure the next read put right kept Overview red all day; a live test's seat too."""
    failed = _read(db, cole, "failed", "503", ago=timedelta(hours=1))
    db.execute(text("UPDATE jobs SET dedup_key = 'ddb:char:y' WHERE id = :id"), {"id": failed})
    assert sync_page.needs(db)["tone"] == "broken"
    fixed, _ = jobs.enqueue(db, sheet_reads.KIND, {"character_id": cole.id}, "ddb:char:y")
    db.execute(text("UPDATE jobs SET state = 'done', finished_at = now() WHERE id = :id"), {"id": fixed})
    assert sync_page.needs(db) is None
    row = next(r for r in sync_page.rows(db) if r["key"] == f"j{failed}")
    assert not row["trouble"] and row["why"].endswith("since done")
    db.execute(text("UPDATE campaigns SET is_test = true WHERE id = :c"), {"c": cole.campaign_id})
    db.add(BridgeIntent(character_id=cole.id, kind="hp", label="A test seat's change", state="not_yet", data={}))
    db.flush()
    assert sync_page.needs(db) is None


def test_failures_stay_listed_behind_any_number_of_routine_reads(db, cole, monkeypatch):
    """The review of #526: the list cut at its newest few hundred lost an earlier failure behind reads every few minutes."""
    monkeypatch.setattr(sync_page, "LIMIT", 2)
    failed = _read(db, cole, "failed", "503", ago=timedelta(hours=3))
    for n in range(4):
        _read(db, cole, "done", ago=timedelta(minutes=n))
    listed = [r["key"] for r in sync_page.rows(db)]
    assert f"j{failed}" in listed and len(listed) == 3


def test_a_draft_is_named_by_its_sessions_number(db, cole):
    from app import drafts
    from app.models import GameSession

    s = GameSession(campaign_id=cole.campaign_id, number=20, title="", source="transcript")
    db.add(s)
    db.flush()
    job_id, _ = jobs.enqueue(db, drafts.STEPS[-1], {"session_id": s.id}, f"draft:x:{s.id}")
    row = next(r for r in sync_page.rows(db) if r["key"] == f"j{job_id}")
    assert row["who"] == "Session 20" and sync_page.story(db, f"j{job_id}")["title"].startswith("Session 20 ·")


def test_retrying_a_change_tells_the_extension_to_make_it(db, cole):
    stuck = BridgeIntent(character_id=cole.id, kind="hp", label="Drank a Potion of Healing", state="not_yet", data={})
    db.add(stuck)
    db.flush()
    assert sync_page.act(db, f"c{stuck.id}", "retry", "Brett")
    said = [k for _, k, _ in db.info.get("announce", [])]
    assert "deliver" in said and "character" in said
