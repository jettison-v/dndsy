"""Where a slow request's time went (Brett, Nov 12: askdnd.ai crawled for a few minutes while the bridge's "the sheet
saved" requests for one character queued for up to two minutes, and the logs said how long each took but not why).

Every request carries a stopwatch (`Stopwatch`, an ASGI middleware), and the steps that can wait add to it with
`step("…")`: a database connection from the pool (`get_db`), a character's lock (app/ddb_bridge.py `_lock`), a read of
D&D Beyond (app/characters.py), storing a sheet. A request that takes `SLOW` seconds or more logs one line on Railway
with its steps and how many of the pool's connections were in use; one over `REPORT` seconds is also a warning in
Sentry, grouped by route, at most once per `QUIET` seconds each. Private like everything that reports (app/errors.py):
the method, the route with its numbers blanked, the steps' times, nothing else."""

import contextvars
import logging
import re
import time
from contextlib import contextmanager

log = logging.getLogger("askdnd.timing")

SLOW = 2.0  # seconds: log it
REPORT = 15.0  # seconds: tell Sentry too
QUIET = 600  # seconds between Sentry warnings for the same route
STEP_MIN = 0.005  # seconds: a step quicker than this isn't worth a word

_now: contextvars.ContextVar[dict | None] = contextvars.ContextVar("askdnd_timing", default=None)
_reported: dict[str, float] = {}


@contextmanager
def step(name: str):
    """Time one step of the request in hand (added up when it happens more than once). Outside a request it does
    nothing. The stopwatch is one dict shared by the request's threads (a plain route runs on a worker thread, and its
    context is copied there), so a step on any of them counts."""
    watch, start = _now.get(), time.monotonic()
    try:
        yield
    finally:
        if watch is not None:
            watch[name] = watch.get(name, 0.0) + time.monotonic() - start


def route_of(scope: dict) -> str:
    """The route as written ("/bridge/heard/{ddb_id}") where FastAPI matched one, else the address with its numbers
    blanked: never an id, a name or a query."""
    route = scope.get("route")
    path = getattr(route, "path", None) or re.sub(r"/\d+(?=/|$)", "/<n>", scope.get("path") or "")
    return path[:120]


def _pool() -> str:
    from app.db import engine

    if engine is None:
        return ""
    p = engine.pool
    try:
        return f"{p.checkedout()} of {p.size() + p._max_overflow} connections in use"  # (QueuePool's own counts)
    except AttributeError:
        return ""


def said(method: str, route: str, total: float, steps: dict) -> str:
    parts = [f"{name} {round(sec * 1000)} ms" for name, sec in sorted(steps.items(), key=lambda kv: -kv[1]) if sec >= STEP_MIN]
    other = total - sum(steps.values())
    if other >= STEP_MIN:
        parts.append(f"the rest {round(other * 1000)} ms")
    return f"Slow request {round(total * 1000)} ms: {method} {route}" + (" · " + ", ".join(parts) if parts else "")


def _report(method: str, route: str, total: float, steps: dict) -> None:
    pool = _pool()
    log.warning("%s%s", said(method, route, total, steps), f" · {pool}" if pool else "")
    if total < REPORT:
        return
    from app import errors

    key, now = f"{method} {route}", time.monotonic()
    if not errors.on() or now - _reported.get(key, -QUIET) < QUIET:
        return
    _reported[key] = now
    import sentry_sdk

    with sentry_sdk.new_scope() as scope:
        scope.set_tag("source", "timing")
        scope.set_tag("route", route)
        scope.set_extra("took_ms", round(total * 1000))
        scope.set_extra("steps_ms", {k: round(v * 1000) for k, v in steps.items()})
        scope.set_extra("pool", pool)
        scope.fingerprint = ["slow", method, route]
        sentry_sdk.capture_message(f"Slow request: {key}", level="warning")


class Stopwatch:
    """The stopwatch on every HTTP request (not the live connection, which stays open by design)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            return await self.app(scope, receive, send)
        watch: dict = {}
        token, start = _now.set(watch), time.monotonic()
        try:
            await self.app(scope, receive, send)
        finally:
            _now.reset(token)
            total = time.monotonic() - start
            if total >= SLOW:
                try:
                    _report(scope.get("method", ""), route_of(scope), total, dict(watch))
                except Exception:  # noqa: BLE001 (timing never breaks a request)
                    log.exception("Couldn't report a slow request")
