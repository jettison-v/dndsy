"""Handoffs on Development (app/fft/handoffs.py; Roadmap item 45, Brett's picks CQ1–CQ5 on
docs/mockups/collaboration-queue/, Nov 25): what passes between Brett, Workshop and Claude, whose turn each is, and a
step past its usual time shown as missed, with a button that does it."""

from datetime import timedelta

from app.fft import handoffs, rules
from app.fft.models import FftChat, FftEvent, FftLine, FftListener, FftNote, FftPull, FftQuestion


def _listening(db, read_id=0):
    db.add(FftListener(name="main", read_id=read_id, heard_at=rules.now()))
    db.flush()


def _row(db, key):
    return next((r for r in handoffs.rows(db) if r["key"] == key), None)


def test_a_note_is_claudes_until_answered_and_missed_only_while_claude_listens(db):
    n = FftNote(role="admin", first_name="Brett", kind="problem", text="The window hides", state="filed", created_at=rules.now() - timedelta(minutes=40))
    db.add(n)
    db.flush()
    assert _row(db, f"n{n.id}")["state"] == "claude"  # (nobody listening: it just waits)
    _listening(db)
    r = _row(db, f"n{n.id}")
    assert r["state"] == "missed" and r["wake"] == "claude" and r["title"].startswith("Your note")
    db.add(FftLine(note_id=n.id, who="claude", to="sender", text="Found it"))
    db.flush()
    r = _row(db, f"n{n.id}")
    assert r["state"] == "done" and not r["wake"] and r["steps"][-1] == ("Claude's answer", True)


def test_a_players_note_waits_for_your_ok_first(db):
    n = FftNote(role="player", first_name="Cole's player", kind="problem", text="The potion didn't stick", state="waiting")
    db.add(n)
    db.flush()
    r = _row(db, f"n{n.id}")
    assert r["state"] == "you" and ("an admin's OK", False) in r["steps"]


def test_a_question_is_yours_then_claudes_until_read(db):
    _listening(db)
    q = FftQuestion(about="document", text="Which window?", choices=[])
    db.add(q)
    db.flush()
    assert _row(db, f"q{q.id}")["state"] == "you"
    q.answered_at = rules.now() - timedelta(minutes=45)
    ev = rules._event(db, "user:1", "question_answered", "question", q.id)
    db.flush()
    assert _row(db, f"q{q.id}")["state"] == "missed"
    db.query(FftListener).update({"read_id": ev.id})
    db.flush()
    assert _row(db, f"q{q.id}")["state"] == "done"


def test_a_chat_line_and_a_merged_pull_request_are_missed_when_late(db):
    _listening(db)
    c = FftChat(words="Picks saved on 47", said_at=rules.now() - timedelta(minutes=45))
    p = FftPull(number=900, title="The Sync page", state="merged", closed_at=rules.now() - timedelta(minutes=45), created_at=rules.now() - timedelta(hours=2))
    db.add_all([c, p])
    db.flush()
    assert _row(db, f"t{c.id}")["state"] == "missed" and _row(db, "p900")["state"] == "missed" and _row(db, "p900")["wake"] == "askdnd"
    c.filed_at = rules.now()
    p.live_at = rules.now()
    db.flush()
    assert _row(db, f"t{c.id}")["state"] == "done" and _row(db, "p900")["state"] == "done"


def test_claude_ai_unlooked_while_listening_is_missed_and_a_look_clears_it(db):
    _listening(db)
    r = _row(db, "look")
    assert r is not None and r["state"] == "missed" and r["wake"] == "look"
    handoffs.looked(db)
    db.flush()
    assert _row(db, "look") is None


def test_missed_comes_first_then_yours_then_claudes_then_done(db):
    _listening(db)
    db.add_all([FftChat(words="filed", said_at=rules.now() - timedelta(minutes=5), filed_at=rules.now()),
                FftQuestion(about="document", text="Yours", choices=[]),
                FftChat(words="late", said_at=rules.now() - timedelta(hours=2))])
    db.flush()
    states = [r["state"] for r in handoffs.rows(db)]
    assert states == sorted(states, key=lambda s: handoffs.ORDER[s])


def test_wake_claude_is_an_event_with_who_pressed_it_and_the_tab_shows_it(admin, db):
    _listening(db)
    db.add(FftChat(words="Unfiled", said_at=rules.now() - timedelta(hours=1)))
    db.commit()
    page = admin.get("/manage/work?tab=handoffs").text
    assert 'data-handoff="' in page and 'data-whose="missed"' in page and 'data-do="handoff-wake"' in page
    assert 'data-stat="missed"' in admin.get("/manage/for-you").text  # (the status bar's count: CQ4)
    r = admin.post("/manage/work/handoffs/wake", data={"what": "claude", "key": "t1"}, follow_redirects=False)
    assert r.status_code == 303
    ev = db.query(FftEvent).filter(FftEvent.kind == "claude_woken").one()
    assert ev.actor.startswith("user:") and ev.data["what"] == "claude"


def test_a_standing_rule_handoffs_are_for_admins(dm, player):
    """A standing rule (Brett, Nov 17: Workshop's pages are admins' alone, R1)."""
    for who in (dm, player):
        assert who.get("/manage/work?tab=handoffs", follow_redirects=False).status_code in (303, 403)
        assert who.post("/manage/work/handoffs/wake", data={"what": "claude"}, follow_redirects=False).status_code in (303, 403)
