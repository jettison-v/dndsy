"""When nobody's listening (app/fft/nudge.py; Roadmap item 42, Brett's pick 1A on Talking both ways, Nov 24): askdnd
emails the admins once when something a person did has waited 30 minutes for Claude with no session listening; nothing
more until a session has listened again; counts and a link only."""

from datetime import timedelta

import pytest
from sqlalchemy import update

from app import config
from app.fft import nudge, rules
from app.fft.models import FftEvent, FftListener


@pytest.fixture
def sent(monkeypatch):
    out = []
    monkeypatch.setattr(nudge, "SEND", lambda to, mail: out.append((to, mail)))
    monkeypatch.setattr(config, "ADMIN_EMAILS", {"admin@example.com"})
    return out


def _brett_answers(db, minutes_ago):
    q = rules.ask(db, "claude", about="area", about_id=None, text="Left or right?", choices=[{"label": "Left"}, {"label": "Right"}])
    rules.answer(db, "user:1", q, choice=0, user_id=None)
    db.flush()
    db.execute(update(FftEvent).where(FftEvent.actor == "user:1").values(at=rules.now() - timedelta(minutes=minutes_ago)))
    db.flush()


def test_one_email_after_30_minutes_with_nobody_listening_then_quiet_until_claude_listens(db, sent):
    _brett_answers(db, 10)
    assert nudge.check(db) == "nothing" and not sent  # (10 minutes: not yet)
    _brett_answers(db, 45)
    assert nudge.check(db) == "sent"
    (to, mail), = sent
    assert to == "admin@example.com" and "wait for Claude" in mail["subject"] and "check askdnd" in mail["text"]
    assert "Left or right" not in mail["text"] + mail["html"]  # (counts and a link: never anyone's words)
    assert nudge.check(db) == "told" and len(sent) == 1  # (once)
    li = FftListener(name="claude:main", heard_at=rules.now())
    db.add(li)
    db.flush()
    assert nudge.check(db) == "listening"
    nudge._save(db, {"sent_at": (rules.now() - timedelta(hours=1)).isoformat()})  # (the email went an hour ago,
    li.heard_at = rules.now() - timedelta(minutes=10)  # then Claude listened, then went away again)
    db.flush()
    assert nudge.check(db) == "sent" and len(sent) == 2


def test_claudes_own_doings_and_whats_been_read_never_send_it(db, sent):
    rules.new_issue(db, "claude", "Claude's own work")
    db.flush()
    db.execute(update(FftEvent).values(at=rules.now() - timedelta(hours=2)))
    db.add(FftListener(name="claude:main", read_id=0, heard_at=rules.now() - timedelta(hours=1)))
    db.flush()
    assert nudge.check(db) == "nothing" and not sent
    _brett_answers(db, 45)
    top = db.scalar(rules.select(rules.func.max(FftEvent.id)))
    db.execute(update(FftListener).values(read_id=top))  # (read by Claude already)
    db.flush()
    assert nudge.check(db) == "nothing" and not sent
