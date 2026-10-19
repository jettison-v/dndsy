"""Small helpers every page module shares: the campaign, signing in with a
permission check, and the plain "not available" / "not found" pages.

askdnd serves one table, so "the campaign" is the first (and only) one.
"""

from collections.abc import Callable

from fastapi import Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import current_user
from app.models import Campaign
from app.templating import templates


def campaign(db: Session) -> Campaign | None:
    return db.scalar(select(Campaign).order_by(Campaign.id))


def message(request: Request, title: str, text: str, status: int = 200):
    return templates.TemplateResponse(request, "message.html", {"title": title, "message": text}, status_code=status)


def forbidden(request: Request, text: str = "Only the admin and the DM can do that."):
    return message(request, "Not available", text, 403)


def not_found(request: Request, text: str = "That isn't in the campaign."):
    return message(request, "Not found", text, 404)


def require(request: Request, allow: Callable[[dict], bool] | None = None,
            text: str = "This page is for the campaign admin."):
    """(user, None) if signed in and allowed, else (None, a sign-in redirect or a 403 page)."""
    user = current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    if allow is not None and not allow(user):
        return None, forbidden(request, text)
    return user, None
