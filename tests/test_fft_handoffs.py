"""Handoffs on Development (app/fft/handoffs.py; Roadmap item 45, Brett's picks CQ1–CQ5 on
docs/mockups/collaboration-queue/, Nov 25): what passes between Brett, Workshop and Claude, whose turn each is, and a
step past its usual time shown as missed, with a button that does it."""

from datetime import timedelta

from app.fft import handoffs, host, rules, views
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
    assert _row(db, f"t{c.id}")["state"] == "missed" and _row(db, f"t{c.id}")["wake"] == "claude"
    assert _row(db, "p900")["state"] == "missed" and not _row(db, "p900")["wake"]  # (askdnd's step: no Wake Claude, the review of #527)
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


def test_the_look_counts_from_when_listening_began_not_across_a_night_without_it(db):
    """Issue 178 (Brett, Nov 27: "This one seems overly stuck"): the last look was the night before, no one listened
    overnight, and the row was Missed for "1 day" the moment listening began. It counts from then instead."""
    handoffs.looked(db)  # (last night's look)
    row = db.get(host.ToolSetting, rules.CLAUDE_AI_LOOKED)
    row.value = (rules.now() - timedelta(hours=13)).isoformat()
    db.add(FftListener(name="main", read_id=0, heard_at=rules.now() - timedelta(hours=12)))  # (stopped listening last night)
    db.flush()
    rules.unread(db, rules.listener(db, "main"), peek=True)  # (listening again this morning)
    db.flush()
    assert _row(db, "look") is None  # (not due until 15 minutes after listening began)
    since = db.get(host.ToolSetting, rules.LISTENING_SINCE)
    since.value = (rules.now() - timedelta(minutes=20)).isoformat()  # (20 minutes on, still no look)
    db.flush()
    r = _row(db, "look")
    assert r["state"] == "missed" and rules.now() - r["at"] < timedelta(minutes=21)  # (late by minutes, not a day)


def test_asking_again_while_listening_keeps_when_listening_began(db):
    _listening(db)
    rules.unread(db, rules.listener(db, "main"), peek=True)
    db.flush()
    assert db.get(host.ToolSetting, rules.LISTENING_SINCE) is None  # (it never stopped: nothing began)


def test_bring_in_now_says_what_to_do_in_claudes_inbox(db):
    """Issue 178: the wake read only "Tool 0: claude woken", so Claude took it for nothing."""
    rules.wake_claude(db, "user:1", "look")
    rules.wake_claude(db, "user:1", "claude", "t1")
    db.flush()
    said = [views.event_words(e) for e in db.query(FftEvent).filter(FftEvent.kind == "claude_woken").order_by(FftEvent.id)]
    assert "Bring in now" in said[0] and "sync list" in said[0] and "Wake Claude" in said[1]


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


def test_a_note_filed_as_an_idea_is_answered_where_ideas_are(db):
    """The review of #527: Claude answers an idea on its Roadmap item, never as a line on the note."""
    _listening(db)
    n = FftNote(role="admin", first_name="Brett", kind="idea", text="A catalog of reviews", state="filed", filed_as="idea",
                created_at=rules.now() - timedelta(hours=2))
    db.add(n)
    db.flush()
    assert _row(db, f"n{n.id}")["state"] == "done"


def test_a_try_before_the_check_reached_for_you_isnt_its_try(db):
    """The review of #527: a local try before the deploy left the check's handoff done although the live one was never tried."""
    from app.fft.models import FftCheck, FftCheckWait, FftTry

    c = FftCheck(title="The card stays on For you")
    db.add(c)
    db.flush()
    db.add_all([FftCheckWait(check_id=c.id, pr="https://github.com/o/r/pull/901"), FftTry(check_id=c.id, version=1, result="passed", where="local")])
    db.flush()
    r = next(r for r in handoffs.rows(db) if r["key"].startswith(f"c{c.id}-"))
    assert r["state"] == "askdnd" and ("tried", False) in r["steps"]


def test_the_list_costs_the_same_few_queries_however_many_handoffs(db):
    """The review of #527: the status bar builds it on every For you and Development load."""
    from sqlalchemy import event

    def count():
        n = [0]

        def hit(*a):
            n[0] += 1
        event.listen(db.get_bind(), "before_cursor_execute", hit)
        handoffs.rows(db)
        event.remove(db.get_bind(), "before_cursor_execute", hit)
        return n[0]
    for i in range(3):
        db.add(FftNote(role="admin", kind="problem", text=f"note {i}", state="filed"))
        db.add(FftQuestion(about="document", text=f"q {i}", choices=[]))
    db.flush()
    few = count()
    for i in range(30):
        db.add(FftNote(role="admin", kind="problem", text=f"more {i}", state="filed"))
        db.add(FftQuestion(about="document", text=f"more q {i}", choices=[]))
    db.flush()
    assert count() == few
