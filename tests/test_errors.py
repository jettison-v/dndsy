"""Error reporting (VTT 0.9, app/errors.py): off without SENTRY_DSN; when on, what's sent is the error, never the
private things around it (request bodies, cookies, query strings, local variables, emails); pages' JavaScript errors
come back through askdnd, signed in, trimmed and rate-limited."""

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from app import errors
from tests.test_table_rolls import table  # noqa: F401


class Captured(Transport):
    """Stands in for Sentry's transport: keeps what would have been sent."""

    def __init__(self, options):
        super().__init__(options)
        self.events = []

    def capture_envelope(self, envelope):
        for item in envelope.items:
            if item.type in ("event", "error"):
                self.events.append(item.payload.json)


@pytest.fixture
def sentry(monkeypatch):
    monkeypatch.setenv("SENTRY_DSN", "https://key@o0.ingest.sentry.io/0")
    assert errors.setup()
    sent = Captured(sentry_sdk.get_client().options)
    sentry_sdk.get_client().transport = sent
    yield sent
    sentry_sdk.init()  # no DSN: reporting off again
    errors._state["on"] = False
    errors._recent.clear()


def test_off_without_a_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert not errors.setup() and not errors.on()


def test_what_leaves_is_the_error_not_whats_around_it():
    event = {
        "request": {"url": "https://beta.askdnd.ai/characters/1/plan?q=secret#x", "method": "POST", "data": "transcript text",
                    "cookies": {"session": "abc"}, "query_string": "q=secret",
                    "headers": {"Cookie": "session=abc", "User-Agent": "Chrome", "Referer": "https://beta.askdnd.ai/?open=4"}},
        "user": {"email": "pat@example.com", "ip_address": "1.2.3.4"},
        "exception": {"values": [{"stacktrace": {"frames": [{"function": "f", "vars": {"notes": "my secret plan"}}]}}]},
    }
    out = errors._scrub(event)
    assert out["request"] == {"url": "https://beta.askdnd.ai/characters/1/plan", "method": "POST", "headers": {"User-Agent": "Chrome"}}
    assert out["user"] == {}
    assert "vars" not in out["exception"]["values"][0]["stacktrace"]["frames"][0]
    assert errors._breadcrumb({"category": "query", "message": "SELECT notes"}) is None
    assert errors._breadcrumb({"category": "logging", "message": "Page error"}) is None
    assert errors._breadcrumb({"category": "httplib", "data": {"url": "https://x?y", "method": "GET", "status_code": 200}})["data"] == \
        {"method": "GET", "status_code": 200}


def test_a_server_error_reaches_sentry_without_its_local_variables(sentry):
    def recap():
        notes = "my " + "secret plan"  # noqa: F841 - a local that must not be sent (the source line itself is public)
        raise ValueError("Couldn't draft the recap")

    try:
        recap()
    except ValueError:
        sentry_sdk.capture_exception()
    (event,) = sentry.events
    assert event["exception"]["values"][0]["value"] == "Couldn't draft the recap"
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    assert frames and not any("vars" in f for f in frames)  # no local variables, so the plan stays here


def test_a_pages_javascript_error_comes_home(table, sentry):  # noqa: F811
    from fastapi.testclient import TestClient

    from app.main import app

    error = {"message": "x is undefined", "source": "/static/app.js?v=1", "line": 120, "column": 7,
             "stack": "TypeError at /static/app.js:120:7", "page": "/characters/1/battle?open=3"}
    assert TestClient(app).post("/errors/page", json=error).status_code == 401  # signed in only
    assert table["dm"].post("/errors/page", json=error).status_code == 204
    (event,) = sentry.events
    assert event["message"] == "Page error: x is undefined" and event["tags"]["page"] == "/characters/1/battle"
    assert event["tags"]["source"] == "page" and event["extra"]["where"] == "/static/app.js?v=1:120:7"
    assert event["user"] == {"role": "DM"}  # the role, never the email
    assert table["player"].post("/errors/page", json={**error, "message": "y" * 5000}).status_code == 204
    assert len(sentry.events[-1]["message"]) < 400  # trimmed
    for _ in range(errors.PAGE_LIMIT):
        table["player"].post("/errors/page", json=error)
    assert table["player"].post("/errors/page", json=error).status_code == 429  # a page erroring in a loop can't flood it
