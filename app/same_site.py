"""Changes come only from askdnd's own pages (foundations F2, docs/plans/2026-11-13-engineering-practices.md).

A change (POST, PUT, PATCH, DELETE) that carries askdnd's sign-in cookie must come from one of askdnd's own pages: the
browser says where a request came from (Origin, and Sec-Fetch-Site), and another site's page can't change either. The
cookie is SameSite=Lax already; this is the second lock (the WebSocket has the same rule, app/realtime.py `_same_site`).

Requests that prove who they are some other way are left to their route: the extension's own key (X-Askdnd-Bridge),
Claude's feedback key, a bearer token, and anything without the cookie (the Processor, staging's notes, mail providers'
one-click unsubscribe). A page on another site can't add those headers without askdnd agreeing to it first, and it
never does (no CORS).
"""

from urllib.parse import urlparse

from starlette.responses import PlainTextResponse

CHANGES = {"POST", "PUT", "PATCH", "DELETE"}
COOKIE = "askdnd_session"
OWN_PROOF = (b"x-askdnd-bridge", b"x-feedback-key", b"authorization")


def from_elsewhere(headers: dict[bytes, bytes]) -> bool:
    """Whether a change made with the sign-in cookie came from a page that isn't askdnd's."""
    if COOKIE.encode() + b"=" not in headers.get(b"cookie", b""):
        return False
    if any(h in headers for h in OWN_PROOF):
        return False
    origin = headers.get(b"origin", b"").decode("latin-1")
    if origin:
        return origin == "null" or urlparse(origin).netloc != headers.get(b"host", b"").decode("latin-1")
    return headers.get(b"sec-fetch-site", b"") == b"cross-site"


class SameSite:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] in CHANGES and from_elsewhere(dict(scope["headers"])):
            await PlainTextResponse("askdnd only takes changes from its own pages.", status_code=403)(scope, receive, send)
            return
        await self.app(scope, receive, send)
