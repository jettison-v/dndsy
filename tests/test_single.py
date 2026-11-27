"""One copy of the app at a time (app/single.py; the backend look-back's LB4): each loop's look runs only where its
advisory lock is held, and no two loops share a lock number (one would silently skip the other's look)."""

from sqlalchemy import func, select

from app import digest, single, speed, unwatched
from app.fft import nudge, sentry_in


def test_every_loop_has_its_own_lock():
    locks = [digest.LOCK, unwatched.LOCK, nudge.LOCK, sentry_in.LOCK, speed.LOCK]
    assert len(set(locks)) == len(locks)


def test_a_look_runs_only_where_its_lock_is_held(db):
    from app.db import engine

    with engine.connect() as other:
        assert other.execute(select(func.pg_try_advisory_lock(nudge.LOCK))).scalar()
        other.commit()
        try:
            assert single.alone(nudge.LOCK, lambda db: "ran", "elsewhere") == "elsewhere"
        finally:
            other.execute(select(func.pg_advisory_unlock(nudge.LOCK)))
            other.commit()
    assert single.alone(nudge.LOCK, lambda db: "ran", "elsewhere") == "ran"


def test_one_way_to_send_an_email(monkeypatch):
    """app/mail.py: the digest and nobody's-listening send the same way; an email a person can stop carries the one-click
    unsubscribe headers, one that can't carries none."""
    import json

    from app import mail

    sent = []

    class Answer:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(mail.urllib.request, "urlopen", lambda req, timeout: (sent.append(json.loads(req.data)), Answer())[1])
    base = {"subject": "s", "html": "<p>h</p>", "text": "h"}
    assert mail.send("someone@example.com", base | {"stop": "https://askdnd.test/stop/1"})
    assert mail.send("someone@example.com", base)
    assert sent[0]["headers"]["List-Unsubscribe"] == "<https://askdnd.test/stop/1>" and "headers" not in sent[1]
    assert digest.SEND is mail.send and nudge.SEND is mail.send
