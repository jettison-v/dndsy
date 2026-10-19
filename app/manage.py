"""The Manage area: one list of its pages (grouped for the menu and the tab bar)
and the Manage home page, which shows what needs attention in each.

Who sees what: Suggestions go to the DM, reviewers and admins; Recaps to reviewers
and admins; everything else to admins only.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import review
from app.auth import can_moderate, current_user, is_admin, is_reviewer
from app.db import get_db
from app.models import Campaign, CharacterSnapshot, User
from app.templating import templates

router = APIRouter()

# (key, label, href, what it's for, group, who may open it, extra paths that belong to it)
PAGES = (
    ("suggestions", "Suggestions", "/suggestions", "Corrections and additions from the table", "Table", can_moderate, ()),
    ("recaps", "Recaps", "/admin/sessions", "Draft, review and publish session recaps", "Table", is_reviewer, ("/admin/notes",)),
    ("history", "History", "/admin/history", "Every change, with Restore", "Table", is_reviewer, ()),
    ("people", "People", "/admin/people", "Who can sign in, their access and character", "Party", is_admin, ()),
    ("characters", "Characters", "/admin/characters", "D&D Beyond links and regrouping", "Party", is_admin, ()),
    ("usage", "Usage", "/admin/usage", "Claude spending and balance", "Admin", is_admin, ()),
    ("data", "Data", "/admin/import", "Import campaign data", "Admin", is_admin, ()),
)
GROUPS = ("Table", "Party", "Admin")


def pages_for(user: dict | None, path: str = "") -> list[dict]:
    """The Manage pages this person can open, with the one they're on marked."""
    out = []
    for key, label, href, about, group, allowed, extra in PAGES:
        if user and allowed(user):
            here = path == href or path.startswith(href + "/") or any(path.startswith(p) for p in extra)
            out.append({"key": key, "label": label, "href": href, "about": about, "group": group, "here": here})
    return out


def _ago(when: datetime | None) -> str:
    if when is None:
        return "never"
    days = (datetime.now(UTC) - when).days
    return "today" if days < 1 else "yesterday" if days == 1 else f"{days} days ago"


def _status(db: Session, user: dict, keys: set[str]) -> dict[str, dict]:
    """One line per card: a count or state, and whether it needs attention."""
    from app.admin_usage import usage_summary
    from app.extraction import latest_campaign_notes, timeline
    from app.suggestions import waiting_count

    campaign = db.scalar(select(Campaign).order_by(Campaign.id))
    out: dict[str, dict] = {}
    if "suggestions" in keys:
        n = waiting_count(db)
        out["suggestions"] = {"text": f"{n} waiting" if n else "Nothing waiting", "attention": bool(n)}
    if "recaps" in keys and campaign:
        sessions = timeline(db, campaign.id)
        statuses = [review.review_status(s, False) for s in sessions]
        unpublished = sum(1 for s in statuses if s in ("draft", "edited"))
        undrafted = statuses.count("no draft")
        notes = latest_campaign_notes(db, campaign.id)
        bits = [f"{unpublished} to review and publish" if unpublished else "", f"{undrafted} not drafted" if undrafted else ""]
        out["recaps"] = {"text": " · ".join(b for b in bits if b) or "All published", "attention": bool(unpublished),
                         "sub": f"Campaign doc synced {_ago(notes.source.last_synced_at) if notes else 'never'}"}
    if "people" in keys:
        people = db.scalar(select(func.count()).select_from(User)) or 0
        out["people"] = {"text": f"{people} {'person' if people == 1 else 'people'}", "attention": False}
    if "characters" in keys:
        snaps = list(db.scalars(select(CharacterSnapshot)))
        failed = sum(1 for s in snaps if s.status == "error")
        oldest = min((s.fetched_at for s in snaps if s.fetched_at), default=None)
        out["characters"] = {"text": f"{failed} couldn't refresh" if failed else f"Oldest copy from {_ago(oldest)}",
                             "attention": bool(failed)}
    if "usage" in keys:
        u = usage_summary(db)
        out["usage"] = {"text": f"${u['month']:.2f} this month", "attention": u["balance"] is not None and u["balance"] < 5,
                        "sub": f"About ${u['balance']:.2f} left" if u["balance"] is not None else "Add a top-up to track the balance"}
    if "history" in keys:
        from app.models import Revision

        n = db.scalar(select(func.count()).select_from(Revision).where(Revision.created_at > datetime.now(UTC).replace(hour=0, minute=0, second=0)))
        out["history"] = {"text": f"{n} change{'s' if n != 1 else ''} today" if n else "No changes today", "attention": False}
    if "data" in keys:
        out["data"] = {"text": "Import a campaign bundle (.json)", "attention": False}
    return out


@router.get("/manage")
def manage_home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    pages = pages_for(user)
    if not pages:
        return templates.TemplateResponse(request, "message.html", {"title": "Not available", "message": "Manage is for the DM, reviewers and admins."},
                                          status_code=403)
    status = _status(db, user, {p["key"] for p in pages})
    groups = [(g, [p for p in pages if p["group"] == g]) for g in GROUPS]
    return templates.TemplateResponse(request, "manage.html", {"groups": [(g, ps) for g, ps in groups if ps], "status": status})
