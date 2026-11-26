"""Where a slow request's time went (app/timing.py; Brett, Nov 12: askdnd.ai crawled and the logs said how long each
request took, not why)."""

import logging
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import timing


def _app() -> FastAPI:
    app = FastAPI()

    @app.get("/slow/{n}")
    def slow(n: int):  # (a plain route: on a worker thread, as most of askdnd's are)
        with timing.step("waiting for the character's lock"):
            time.sleep(0.05)
        with timing.step("reading D&D Beyond"):
            time.sleep(0.02)
        return {"n": n}

    @app.get("/quick")
    def quick():
        return {}

    @app.get("/held")
    def held():  # (a long-poll: waiting is its job)
        with timing.step(timing.HELD):
            time.sleep(0.08)
        return {}

    app.add_middleware(timing.Stopwatch)
    return app


def test_a_slow_request_says_where_its_time_went(monkeypatch, caplog):
    monkeypatch.setattr(timing, "SLOW", 0.05)
    caplog.set_level(logging.WARNING, logger="askdnd.timing")
    c = TestClient(_app())
    assert c.get("/slow/75423618").json() == {"n": 75423618}
    line = next(r.getMessage() for r in caplog.records if r.name == "askdnd.timing")
    assert line.startswith("Slow request ") and "GET /slow/{n}" in line  # (the route as written: never the id itself)
    assert "75423618" not in line
    assert line.index("waiting for the character's lock") < line.index("reading D&D Beyond")  # (longest first)
    caplog.clear()
    c.get("/quick")
    c.get("/held")  # (Nov 20: the inbox held open was a "slow request" every 25 seconds, and a Sentry warning)
    assert not [r for r in caplog.records if r.name == "askdnd.timing"]


def test_a_step_outside_a_request_does_nothing():
    with timing.step("anything"):
        pass


def test_the_route_is_written_without_its_numbers():
    assert timing.route_of({"path": "/bridge/heard/75423618"}) == "/bridge/heard/<n>"
    assert timing.route_of({"path": "/characters/12/battle"}) == "/characters/<n>/battle"


def test_sentry_hears_the_query_count_as_a_count(monkeypatch):
    """Issue 134: the report sent the number of queries among the times, multiplied by 1000 (474 read as 474,000)."""
    import sentry_sdk

    from app import errors

    sent = []

    class Scope:
        def __init__(self):
            self.extras = {}

        def set_tag(self, *a):
            pass

        def set_extra(self, k, v):
            self.extras[k] = v

        def __enter__(self):
            sent.append(self)
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(errors, "on", lambda: True)
    monkeypatch.setattr(sentry_sdk, "new_scope", Scope)
    monkeypatch.setattr(sentry_sdk, "capture_message", lambda *a, **k: None)
    monkeypatch.setattr(timing, "_reported", {})
    timing._report("GET", "/manage/work", 20.0, {timing.DB: 19.0, timing.READS: 474})
    assert sent[0].extras["queries"] == 474 and sent[0].extras["steps_ms"] == {timing.DB: 19000}
