"""Campaign addresses (data organization step 4): /c/<campaign>/… opens any page in that campaign.

This sits in front of every page. For /c/<slug>/rest it remembers the campaign for the request (app/access.py's
`path_slug`) and hands the page "/rest", so every page works in any campaign without its own routes. Opening a
campaign this way also makes it the person's current campaign (users.current_campaign_id), so plain links on the
page (/campaign/12) stay in it. A campaign the person can't open is "not found".

Every page has one address (Brett, 2026-10-23). Story pages and the campaign's Manage pages live only at
/c/<campaign>/…; opened without it they're Not found, except the home page (/), which opens your current campaign's
Story. Everything else (characters, Party, Help, askdnd-wide Manage pages) has a plain address and shows the
current campaign. Panels, forms and pictures a page asks for still work at plain addresses.
"""

import re
from collections.abc import Callable

import anyio
from starlette.responses import PlainTextResponse, RedirectResponse

from app import access

PREFIX = re.compile(r"^/c/([a-z0-9][a-z0-9-]*)(/.*)?$")
STORY = ("/sessions", "/campaign", "/map")
# The campaign's Manage pages (app/manage.py), plus /manage itself (Needs you). /manage/history without a campaign
# is the admins' askdnd-wide History, so it isn't here.
MANAGE = ("/manage/inbox", "/manage/sessions", "/manage/proposals", "/manage/table", "/manage/house-rules",
          "/manage/settings", "/manage/dm-guide")

# askdnd-wide Manage pages: the same in every campaign, so their address never names one (/c/x/manage/usage → /manage/usage)
ASKDND = ("/manage/campaigns", "/manage/accounts", "/manage/tool-corrections", "/manage/usage", "/manage/backups", "/manage/design")


def is_story(path: str) -> bool:
    return path in ("/", "/story") or any(path == p or path.startswith(p + "/") or path.startswith(p + "?") for p in STORY)


def in_campaign(path: str) -> bool:
    """A page about one campaign: story pages and the campaign's Manage pages."""
    return is_story(path) or path == "/manage" or any(path == p or path.startswith(p + "/") for p in MANAGE)


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
                    viewing = bool((scope.get("session") or {}).get("real_user"))  # View as: nothing in their name
                    if not viewing and (access._rows().get(email) or {}).get("current") != here["id"]:
                        await anyio.to_thread.run_sync(remember, email, here["id"])
                if is_page_visit(scope) and any(rest == p or rest.startswith(p + "/") for p in ASKDND):
                    scope = {**scope, "path": GONE, "raw_path": GONE.encode()}  # askdnd's pages never name a campaign
            elif email and scope["path"] == "/" and scope["method"] == "GET" and not _header(scope, b"hx-request"):
                here = access.current_campaign(email) if access.level(email) else None
                if here:  # the home page: the one plain address kept, opening your current campaign's Story
                    query = scope.get("query_string", b"").decode()
                    return await RedirectResponse(f"/c/{here['slug']}/" + (f"?{query}" if query else ""), status_code=307)(scope, receive, send)
            elif is_page_visit(scope) and is_campaign_page(scope["path"]):
                scope = {**scope, "path": GONE, "raw_path": GONE.encode()}  # one address per page: /c/<campaign>/… (2026-10-23)
            await self.app(scope, receive, send)
        finally:
            access.viewer.reset(t_viewer)
            access.path_slug.reset(t_slug)


GONE = "/__not-found"  # no route: the friendly Not found page (app/main.py)


def is_page_visit(scope) -> bool:
    """Someone opening a page (not a panel, a form or a picture the page asks for)."""
    return scope["method"] == "GET" and not _header(scope, b"hx-request")


def is_campaign_page(path: str) -> bool:
    """A page that belongs to one campaign, opened without /c/<campaign>: its address is the prefixed one only."""
    if path in ("/story", "/sessions", "/map", "/campaign", "/manage") or re.fullmatch(r"/campaign/(?:glossary/)?\d+", path):
        return True
    return any(path == p or path.startswith(p + "/") for p in MANAGE) and "/images/" not in path


def _header(scope, name: bytes) -> bool:
    return any(k == name for k, _ in scope.get("headers") or [])
