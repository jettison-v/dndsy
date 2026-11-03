"""Small helpers every page module shares: the campaign, signing in with a
permission check, and the plain "not available" / "not found" pages.

"The campaign" is the one the person asking is in now (app/access.py: the /c/<campaign>/ address, else the one
they last opened); with no one asking (background work, the upload API), the first one.
"""

import json
from collections.abc import Callable

from fastapi import Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import access
from app.auth import current_user
from app.models import Campaign
from app.templating import templates


def campaign(db: Session) -> Campaign | None:
    if not access.viewer.get():
        return first_campaign(db)
    cid = access.current_campaign_id()
    return db.get(Campaign, cid) if cid else None


def first_campaign(db: Session) -> Campaign | None:
    return db.scalar(select(Campaign).order_by(Campaign.id))


def base(c: dict | Campaign | None = None) -> str:
    """The start of a story page's address in a campaign ("/c/main"), the current one if none is given."""
    c = c if c is not None else access.current_campaign()
    slug = c["slug"] if isinstance(c, dict) else c.slug if c is not None else None
    return f"/c/{slug}" if slug else ""


def person_name(user: dict | None) -> str:
    """How someone is named where we record who wrote something (a description, a recap)."""
    return ((user or {}).get("name") or (user or {}).get("email") or "someone")[:200]


def message(request: Request, title: str, text: str, status: int = 200):
    return templates.TemplateResponse(request, "message.html", {"title": title, "message": text}, status_code=status)


def forbidden(request: Request, text: str = "Only the admin and the DM can do that."):
    return message(request, "Not available", text, 403)


def not_found(request: Request, text: str = "That isn't in the campaign."):
    return message(request, "Not found", text, 404)


NOTICE_KINDS = ("ok", "info", "warn", "error")


def notice(text: str, kind: str = "ok"):
    """A corner card's message (app.js "corner cards"; Brett, 2026-10-29), for `request.session["toast"]` (the next
    page shows it) or HX-Trigger's "toast". Its text alone when it says something was done; {"text", "kind"} for
    "info", "warn" (a refused or invalid action: amber, a little longer) or "error" (something didn't save: red, until
    closed)."""
    assert kind in NOTICE_KINDS
    return text if kind == "ok" else {"text": text, "kind": kind}


def require(request: Request, allow: Callable[[dict], bool] | None = None,
            text: str = "This page is for the campaign admin."):
    """(user, None) if signed in and allowed, else (None, a sign-in redirect or a 403 page)."""
    user = current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    if allow is not None and not allow(user):
        return None, forbidden(request, text)
    return user, None


def changed(character, toast: str = "", closePanel: bool = False, deliver: bool = False, **more) -> str:  # noqa: N803 (the event's name in app.js)
    """The HX-Trigger header for "you changed something of this character's" (a pin, reminder, note, a change for D&D
    Beyond): the page and its open side panels show their new copy (app.js "characterChanged", the one way every page
    shows a new copy). `toast` says so; `closePanel` closes the window the form was in first; `deliver`: a change for
    D&D Beyond was just made (deliver_now); `more`: other events."""
    events = {"characterChanged": {"character": character.id}, **more}
    if deliver:
        events["bridgeDeliver"] = deliver_now(character)
    if toast:
        events["toast"] = toast
    if closePanel:
        events = {"closePanel": True, **events}
    return json.dumps(events)


def deliver_now(character) -> dict:
    """The "bridgeDeliver" event for a change for D&D Beyond just made here: whatever page it was made on tells the
    extension to make it now (app.js → askdnd.js), instead of at its next check every 30 seconds. With the change it
    just made (`upto`, its newest one from the last few seconds), the corner card saying so follows it to D&D Beyond
    (app.js "following a change"; Bridge Review, Nov 3)."""
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import select
    from sqlalchemy.orm import object_session

    from app.models import BridgeIntent

    out = {"ddbId": str(character.ddb_id or "")}
    db = object_session(character)
    newest = db.scalar(select(BridgeIntent).where(BridgeIntent.character_id == character.id).order_by(BridgeIntent.id.desc()).limit(1)) if db else None
    if newest is not None and newest.created_at and newest.created_at > datetime.now(UTC) - timedelta(seconds=15):
        out |= {"character": character.id, "upto": newest.id}
    return out


async def _body_json(request: Request):
    try:
        return await request.json()
    except ValueError:
        return None  # (not JSON: the route's own check turns it away)


async def _body_form(request: Request):
    return await request.form()


# A route that reads its body and uses the database takes it through one of these and is a plain `def`: reading a body
# has to wait, and a plain route runs on a worker thread, so its database work never holds up everyone's live connection.
JsonBody = Depends(_body_json)
FormBody = Depends(_body_form)
