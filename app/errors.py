"""Knowing when something breaks (VTT 0.9, docs/plans/2026-10-22-vtt-roadmap.md): errors on beta go to Sentry
(sentry.io), which alerts Brett, instead of a player finding them mid-game. Off unless SENTRY_DSN is set, so local
development and tests send nothing.

What's sent is the error itself: its type, message, the code it happened in (file, function, line), the page's
address and the release. Private by default, because askdnd holds things that must never leave it:
- no request bodies (the Processor's upload carries filtered transcript text; forms carry notes), cookies, query
  strings or headers beyond the browser's name;
- no local variables in stack traces (they can hold notes, sheet data or recaps);
- no IP addresses, emails or names: who it happened to is the account's role only;
- no breadcrumbs from database queries or log messages (their text can hold the same).

Pages' own JavaScript errors come back through askdnd (`POST /errors/page`, sent by app.js) rather than through a
Sentry script on every page, so no third party runs in players' browsers.
"""

import logging
import os
import time
from collections import deque
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import Response

from app import config

router = APIRouter()
log = logging.getLogger(__name__)

KEPT_HEADERS = {"user-agent"}
_state = {"on": False}


def _scrub(event: dict, hint: dict | None = None) -> dict:
    """The last word on what leaves askdnd (Sentry calls it for every event)."""
    req = event.get("request") or {}
    if req:
        url = req.get("url") or ""
        event["request"] = {"url": urlsplit(url)._replace(query="", fragment="").geturl() if url else "",
                            "method": req.get("method"),
                            "headers": {k: v for k, v in (req.get("headers") or {}).items() if k.lower() in KEPT_HEADERS}}
    user = event.get("user") or {}
    event["user"] = {"role": user["role"]} if user.get("role") else {}
    for exc in (event.get("exception") or {}).get("values") or []:
        for frame in (exc.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    for thread in (event.get("threads") or {}).get("values") or []:
        for frame in (thread.get("stacktrace") or {}).get("frames") or []:
            frame.pop("vars", None)
    return event


def _breadcrumb(crumb: dict, hint: dict | None = None) -> dict | None:
    if crumb.get("category") in ("query", "redis") or crumb.get("type") == "query" or crumb.get("category", "").startswith("log"):
        return None
    if crumb.get("category") == "httplib" and isinstance(crumb.get("data"), dict):
        crumb["data"] = {k: crumb["data"][k] for k in ("method", "status_code") if k in crumb["data"]}
    return crumb


def setup(service: str = "web") -> bool:
    """Start reporting if SENTRY_DSN is set. `service`: "web" (the app) or "backup" (the nightly backup)."""
    dsn = os.getenv("SENTRY_DSN", "").strip()
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("SENTRY_ENVIRONMENT") or ("beta" if config.IS_PRODUCTION else config.APP_ENV),
        release=(os.getenv("RAILWAY_GIT_COMMIT_SHA") or "")[:12] or None,
        server_name=service,
        # Collect as little as possible in the first place; _scrub() below is the backstop
        data_collection={"user_info": False, "cookies": {"mode": "off"}, "http_bodies": [],
                         "http_headers": {"request": {"mode": "allowlist", "terms": sorted(KEPT_HEADERS)}},
                         "url_query_params": {"mode": "off"}, "database_query_data": False, "queues": False,
                         "gen_ai": {"inputs": False, "outputs": False}, "stack_frame_variables": False},
        max_request_body_size="never",
        traces_sample_rate=0,  # errors only, no performance tracing
        before_send=_scrub,
        before_breadcrumb=_breadcrumb,
    )
    sentry_sdk.set_tag("service", service)
    _state["on"] = True
    return True


def on() -> bool:
    return _state["on"]


# ------------------------------------------------------------------ pages' JavaScript errors
_recent: deque[float] = deque()
PAGE_LIMIT = 30  # at most this many page errors a minute, from everyone (a broken page in a loop can't flood Sentry)


def _cut(value, n: int) -> str:
    return str(value or "")[:n]


@router.post("/errors/page")
async def page_error(request: Request):
    """A page's JavaScript error (app.js "page errors"): signed-in people only, trimmed, rate-limited."""
    from app.access import ROLE_LABELS, role
    from app.auth import current_user

    user = current_user(request)
    if not user:
        return Response(status_code=401)
    try:
        got = await request.json()
    except ValueError:
        return Response(status_code=400)
    if not isinstance(got, dict):
        return Response(status_code=400)
    now = time.monotonic()
    while _recent and now - _recent[0] > 60:
        _recent.popleft()
    if len(_recent) >= PAGE_LIMIT:
        return Response(status_code=429)
    _recent.append(now)
    message, page = _cut(got.get("message"), 300), urlsplit(_cut(got.get("page"), 300)).path
    log.warning("Page error on %s: %s", page, message)
    if on():
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("source", "page")
            scope.set_tag("page", page)
            scope.set_user({"role": ROLE_LABELS.get(role(user.get("email")) or "", "") or None})
            scope.set_extra("where", f"{_cut(got.get('source'), 200)}:{_cut(got.get('line'), 8)}:{_cut(got.get('column'), 8)}")
            scope.set_extra("stack", _cut(got.get("stack"), 2000))
            scope.fingerprint = ["page", message, _cut(got.get("source"), 200)]
            sentry_sdk.capture_message(f"Page error: {message}", level="error")
    return Response(status_code=204)
