"""View as: an admin sees askdnd exactly as someone else does (Brett, 2026-10-23: "test as a DM").

Starting it (Manage › Accounts or a campaign's Table) stores who in the admin's own session. On every request
while it's on, `ViewAs` hands the pages a copy of the session in which that person is the one signed in, so every
permission, campaign and menu follows from the same rules as for them. The real session is never changed except
to start or stop.

It is read-only: anything but reading (a form, a button, a roll) is refused until "Stop viewing", so nothing
happens in the other person's name, and remembering which campaign they last opened is skipped.

Players' notes stay private: an admin who is a campaign's DM can't view as someone who plays in it, because that
would show the DM their players' notes (the one thing a DM never sees).
"""

import json

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.responses import Response

from app import access
from app.db import get_db
from app.models import User

router = APIRouter()
STOP = "/view-as/stop"


def viewing(session: dict | None) -> dict | None:
    """The person being viewed as ({"email", "name"}), when the real person signed in is an admin."""
    session = session or {}
    target = session.get("view_as") or {}
    real = (session.get("real_user") or session.get("user") or {}).get("email")
    if not target.get("email") or access.level(real) != access.ADMIN or access.level(target["email"]) is None:
        return None
    return target


def refusal(real_email: str, target_email: str) -> str:
    """Why an admin may not view as this person, or "" when they may."""
    real_email, target_email = real_email.strip().lower(), target_email.strip().lower()
    if access.level(real_email) != access.ADMIN:
        return "Only admins can view as someone else."
    if target_email == real_email:
        return "That's you."
    if access.level(target_email) is None:
        return "They can't sign in, so there's nothing to see."
    rows = access._rows()
    mine = (rows.get(real_email) or {}).get("roles") or {}
    theirs = (rows.get(target_email) or {}).get("roles") or {}
    for cid, r in mine.items():
        if r == access.DM and cid in theirs and theirs[cid] != access.DM:
            return "You're the DM of a campaign they play in. Viewing as them would show you their notes."
    return ""


class ViewAs:
    """Between the session and the campaign addresses: swaps who's signed in, for reading only."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        session = scope.get("session")
        target = viewing(session)
        if target is None:
            if session and session.get("view_as"):
                session.pop("view_as", None)  # no longer allowed (removed, or no longer an admin)
            return await self.app(scope, receive, send)
        if scope["path"] == STOP:  # stopping changes the real session, so it gets the real one
            return await self.app(scope, receive, send)
        if scope["method"] not in ("GET", "HEAD"):
            return await _refuse(scope, session, target)(scope, receive, send)
        real = session.get("user") or {}
        seen = {**session, "user": {"email": target["email"], "name": target.get("name") or target["email"], "picture": None},
                "real_user": real}
        await self.app({**scope, "session": seen}, receive, send)


def _refuse(scope, session: dict, target: dict) -> Response:
    message = f"You're viewing as {target.get('name') or target['email']}, so nothing can be changed. Stop viewing first."
    if any(k == b"hx-request" for k, _ in scope.get("headers") or []):
        return HTMLResponse("", headers={"HX-Trigger": json.dumps({"toast": message}), "HX-Reswap": "none"})
    session["toast"] = message
    referer = next((v.decode() for k, v in scope.get("headers") or [] if k == b"referer"), "/")
    return RedirectResponse(referer or "/", status_code=303)


@router.post("/view-as")
def start(request: Request, email: str = Form(...), db: Session = Depends(get_db)):
    real = request.session.get("user") or {}
    why = refusal(real.get("email", ""), email)
    if why:
        request.session["toast"] = why
        return RedirectResponse(request.headers.get("referer") or "/manage/accounts", status_code=303)
    u = db.scalar(select(User).where(User.email == email.strip().lower()))
    name = (u.name if u and u.name and u.name != u.email else None) or email
    request.session["view_as"] = {"email": email.strip().lower(), "name": name}
    request.session["view_as_back"] = request.headers.get("referer") or "/manage/accounts"
    return RedirectResponse("/", status_code=303)


@router.post(STOP)
def stop(request: Request):
    request.session.pop("view_as", None)
    back = request.session.pop("view_as_back", None) or "/manage/accounts"
    request.session["toast"] = "Back to your own view"
    return RedirectResponse(back, status_code=303)
