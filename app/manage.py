"""The Manage area: one list of its pages (grouped for the menu and the tab bar)
and the Manage home page, which shows what needs attention in each.

Who sees what: Suggestions go to the DM, reviewers and admins; Recaps to reviewers
and admins; everything else to admins only.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import web
from app import review
from app.auth import can_moderate, current_user, is_admin, is_reviewer
from app.db import get_db
from app.models import CharacterSnapshot, User
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
    ("data", "Data", "/admin/import", "Imports and nightly backups", "Admin", is_admin, ()),
    ("design", "Design system", "/manage/design", "Every component and token, for building and reviewing screens", "Admin", is_admin, ()),
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
    delta = datetime.now(UTC) - when
    hours = int(delta.total_seconds() // 3600)
    if hours < 1:
        return "less than an hour ago"
    if hours < 24:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    return "yesterday" if delta.days == 1 else f"{delta.days} days ago"


STALE_CHARACTERS = timedelta(days=7)
BACKUP_DUE = timedelta(hours=30)  # nightly, with slack


def backup_status(db: Session) -> dict:
    """When the nightly backup last worked, and whether that needs attention."""
    from app.models import JobRun

    last = db.scalar(select(JobRun).where(JobRun.name == "backup").order_by(JobRun.id.desc()))
    good = db.scalar(select(JobRun).where(JobRun.name == "backup", JobRun.status == "ok").order_by(JobRun.id.desc()))
    if last is None:
        return {"text": "No backup recorded yet", "attention": True, "last": None, "good": None}
    if last.status != "ok":
        return {"text": f"Last backup failed ({_ago(last.finished_at)})", "attention": True, "last": last, "good": good}
    overdue = datetime.now(UTC) - last.finished_at > BACKUP_DUE
    return {"text": f"Last backup {_ago(last.finished_at)}" + (" (overdue)" if overdue else ""),
            "attention": overdue, "last": last, "good": good}


def _status(db: Session, user: dict, keys: set[str]) -> dict[str, dict]:
    """One line per card: a count or state, and whether it needs attention."""
    from app.admin_usage import usage_summary
    from app.extraction import latest_campaign_notes, timeline
    from app.suggestions import waiting_count

    campaign = web.campaign(db)
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
        stale = oldest is not None and datetime.now(UTC) - oldest > STALE_CHARACTERS
        out["characters"] = {"text": f"{failed} couldn't refresh from D&D Beyond" if failed else f"Oldest copy from {_ago(oldest)}",
                             "attention": bool(failed) or stale,
                             "sub": "Refresh all, or check the D&D Beyond links" if failed or stale else ""}
    if "usage" in keys:
        u = usage_summary(db)
        low = u["balance"] is not None and u["balance"] < 5
        if u["limit_reached"]:
            sub = f"Monthly limit of ${u['limit']:.2f} reached: drafting is paused"
        elif u["balance"] is not None:
            sub = f"About ${u['balance']:.2f} left"
        else:
            sub = "Add a top-up to track the balance"
        month = f"${u['month']:.2f} of ${u['limit']:.2f} this month" if u["limit"] is not None else f"${u['month']:.2f} this month"
        out["usage"] = {"text": month, "attention": low or u["limit_reached"], "sub": sub}
    if "history" in keys:
        from app.models import Revision

        n = db.scalar(select(func.count()).select_from(Revision).where(Revision.created_at > datetime.now(UTC).replace(hour=0, minute=0, second=0)))
        out["history"] = {"text": f"{n} change{'s' if n != 1 else ''} today" if n else "No changes today", "attention": False}
    if "data" in keys:
        b = backup_status(db)
        out["data"] = {"text": b["text"], "attention": b["attention"], "sub": "Import a campaign bundle (.json)"}
    return out


@router.get("/manage")
def manage_home(request: Request, db: Session = Depends(get_db)):
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    pages = pages_for(user)
    if not pages:
        return web.forbidden(request, "Manage is for the DM, reviewers and admins.")
    status = _status(db, user, {p["key"] for p in pages})
    groups = [(g, [p for p in pages if p["group"] == g]) for g in GROUPS]
    return templates.TemplateResponse(request, "manage.html", {"groups": [(g, ps) for g, ps in groups if ps], "status": status})


# ------------------------------------------------------------------ design system (roadmap step 9)

# Tokens shown on the component page, in the order of app.css's :root (the stylesheet is the source of truth)
COLOR_TOKENS = (
    ("Surfaces", ("--bg", "--surface", "--surface-2", "--line", "--line-strong", "--chrome")),
    ("Text", ("--text", "--text-strong", "--muted", "--faint", "--link")),
    ("Story", ("--story-bg", "--story-line", "--story-text")),
    ("Status", ("--red", "--amber", "--green", "--blue", "--violet")),
    ("Action economy", ("--k-action", "--k-bonus", "--k-reaction", "--k-other")),
)
TEXT_SIZES = (("--fs-xs", "12", "Labels, secondary lines, tags"), ("--fs-sm", "14", "List cells, chips, controls"),
              ("--fs-md", "16", "Body text, a row's name"), ("--fs-lg", "19", "Section headings"),
              ("--fs-xl", "26", "Character name"), ("--fs-2xl", "30", "Page title"))
SPACE = (("--sp-1", 4), ("--sp-2", 8), ("--sp-3", 12), ("--sp-4", 16), ("--sp-5", 24), ("--sp-6", 32))
CORNERS = (("--r-sm", "6px", "Small chips, inner boxes"), ("--r-md", "8px", "Buttons, inputs"),
           ("--r-lg", "12px", "Sections, cards, panels"), ("--r-pill", "999px", "Tags, chips, counts"))


@router.get("/manage/design")
def design_page(request: Request):
    """Admins: every token and component with the app's own markup (made-up content only)."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not is_admin(user):
        return web.forbidden(request, "The design system page is for admins.")
    demo = {"c": {"id": 0}, "picks": {"star": {"spell:Fire Bolt"}, "fav": {"spell:Fire Bolt", "spell:Shield"}, "remind": set(),
                                       "notes": {"spell:Shield": "Save it for the big hit"}}}
    return templates.TemplateResponse(request, "design.html", {"colors": COLOR_TOKENS, "sizes": TEXT_SIZES, "space": SPACE,
                                                               "corners": CORNERS, **demo})


@router.get("/manage/design/panel")
def design_panel(request: Request):
    """The sample side panel and modal on the component page."""
    user = current_user(request)
    if not user or not is_admin(user):
        return web.forbidden(request, "The design system page is for admins.")
    return templates.TemplateResponse(request, "_design_panel.html", {})
