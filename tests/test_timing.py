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
    assert not [r for r in caplog.records if r.name == "askdnd.timing"]


def test_a_step_outside_a_request_does_nothing():
    with timing.step("anything"):
        pass


def test_the_route_is_written_without_its_numbers():
    assert timing.route_of({"path": "/bridge/heard/75423618"}) == "/bridge/heard/<n>"
    assert timing.route_of({"path": "/characters/12/battle"}) == "/characters/<n>/battle"
