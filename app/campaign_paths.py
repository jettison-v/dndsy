"""Campaign addresses (data organization step 4): /c/<campaign>/… opens any page in that campaign.

This sits in front of every page. For /c/<slug>/rest it remembers the campaign for the request (app/access.py's
`path_slug`) and hands the page "/rest", so every page works in any campaign without its own routes. Opening a
campaign this way also makes it the person's current campaign (users.current_campaign_id), so plain links on the
page (/campaign/12) stay in it. A campaign the person can't open is "not found".

Story pages opened at their old address (/, /sessions, /campaign, /map) are sent to the same page in the person's
current campaign, so the address says which campaign it is. Everything else (characters, Party, Manage) keeps its
address and shows the current campaign.
"""

import re
from collections.abc import Callable

import anyio
from starlette.responses import PlainTextResponse, RedirectResponse

from app import access

PREFIX = re.compile(r"^/c/([a-z0-9][a-z0-9-]*)(/.*)?$")
STORY = ("/sessions", "/campaign", "/map")


def is_story(path: str) -> bool:
    return path in ("/", "/story") or any(path == p or path.startswith(p + "/") or path.startswith(p + "?") for p in STORY)


def remember_in(db, email: str, campaign_id: int) -> None:
    """Make it the person's current campaign (the one plain addresses open)."""
    from sqlalchemy import select

    from app.models import User

    u = db.scalar(select(User).where(User.email == email))
    if u and u.current_campaign_id != campaign_id:
        u.current_campaign_id = campaign_id
        db.commit()
    access.invalidate()


def _remember(email: str, campaign_id: int) -> None:
    from app.db import SessionLocal

    with SessionLocal() as db:
        remember_in(db, email, campaign_id)


remember: Callable[[str, int], None] = _remember  # tests write with their own session


class CampaignPaths:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        email = ((scope.get("session") or {}).get("user") or {}).get("email", "").strip().lower()
        m = PREFIX.match(scope["path"])
        slug = m.group(1) if m else None
        t_viewer, t_slug = access.viewer.set(email), access.path_slug.set(slug)
        try:
            if m:
                rest = m.group(2) or "/"
                scope = {**scope, "path": rest, "raw_path": rest.encode()}
                if email and access.level(email):
                    here = access.current_campaign(email)
                    if here is None:
                        return await PlainTextResponse("That campaign isn't one of yours.", 404)(scope, receive, send)
                    if (access._rows().get(email) or {}).get("current") != here["id"]:
                        await anyio.to_thread.run_sync(remember, email, here["id"])
            elif email and scope["method"] == "GET" and is_story(scope["path"]) and not _header(scope, b"hx-request"):
                here = access.current_campaign(email) if access.level(email) else None
                if here:
                    query = scope.get("query_string", b"").decode()
                    path = "" if scope["path"] in ("/", "/story") else scope["path"]
                    url = f"/c/{here['slug']}{path or '/'}" + (f"?{query}" if query else "")
                    return await RedirectResponse(url, status_code=307)(scope, receive, send)
            await self.app(scope, receive, send)
        finally:
            access.viewer.reset(t_viewer)
            access.path_slug.reset(t_slug)


def _header(scope, name: bytes) -> bool:
    return any(k == name for k, _ in scope.get("headers") or [])
