"""The Manage area: one list of its pages, in two groups, and the Needs you page.

- **The campaign** (the DM, reviewers, admins): pages about one campaign, always at its own address
  (/c/<campaign>/manage/…), so they can't act on the wrong one (app/campaign_paths.py sends plain addresses there).
- **askdnd** (admins): pages that are the same for every campaign, at /manage/….

Who may open each page is in app/access.py (`allows()`), through app/auth.py's checks. Old addresses (/admin/…,
/suggestions) redirect to their new homes (`MOVED`, below).
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, review, web
from app.auth import (
    can_edit_settings,
    can_moderate,
    can_see_table,
    can_set_house_rules,
    current_user,
    is_admin,
    is_reviewer,
)
from app.db import get_db
from app.templating import templates

router = APIRouter()

CAMPAIGN, ASKDND = "campaign", "askdnd"
# (key, label, address, what it's for, group, who may open it, extra addresses that belong to it).
# A campaign page's address is under the campaign's (/c/<campaign>/manage/…).
PAGES = (
    ("needs", "Needs you", "/manage", "What's waiting, most important first", CAMPAIGN, can_moderate, ()),
    ("inbox", "Inbox", "/manage/inbox", "Suggestions from the table and Claude's drafts, waiting for your OK", CAMPAIGN, can_moderate, ()),
    ("sessions", "Sessions", "/manage/sessions", "Draft, review and publish recaps; the campaign doc", CAMPAIGN, is_reviewer, ("/manage/proposals",)),
    ("table", "Table", "/manage/table", "Who plays which character, roles, D&D Beyond links", CAMPAIGN, can_see_table, ()),
    ("house", "House rules", "/manage/house-rules", "Your rulings on how askdnd rolls things at this table", CAMPAIGN, can_set_house_rules, ()),
    ("history", "History", "/manage/history", "This campaign's changes, with Restore", CAMPAIGN, is_reviewer, ()),
    ("settings", "Settings", "/manage/settings", "The campaign's name, the DM's name, its D&D Beyond id", CAMPAIGN, can_edit_settings, ()),
    ("guide", "DM guide", "/manage/dm-guide", "How the campaign record works, and getting through the backlog", CAMPAIGN, can_moderate, ()),
    ("campaigns", "Campaigns", "/manage/campaigns", "Every campaign; start one, move a character", ASKDND, is_admin, ()),
    ("accounts", "Accounts", "/manage/accounts", "Who can sign in, who's an admin, their campaigns", ASKDND, is_admin, ()),
    ("corrections", "Tool corrections", "/manage/tool-corrections", "Fixes to how askdnd reads D&D Beyond, for every character", ASKDND, is_admin, ()),
    ("usage", "Usage", "/manage/usage", "Claude spending and balance", ASKDND, is_admin, ()),
    ("backups", "Backups and imports", "/manage/backups", "Nightly backups, then imports", ASKDND, is_admin, ()),
    ("askdnd-history", "History", "/manage/history", "Changes to accounts and askdnd as a whole", ASKDND, is_admin, ()),
    ("design", "Design system", "/manage/design", "Every component and token, for building askdnd", ASKDND, is_admin, ()),
)


def pages_for(user: dict | None, path: str = "") -> list[dict]:
    """The Manage pages this person can open, with the one they're on marked. `path` is the address without
    /c/<campaign> (app/campaign_paths.py takes it off); a campaign page is "here" only at a campaign's address."""
    if not user:
        return []
    in_campaign = access.path_slug.get() is not None
    base = web.base()
    out = []
    for key, label, href, about, group, allowed, extra in PAGES:
        if not allowed(user):
            continue
        same = path == href or (href != "/manage" and path.startswith(href + "/")) or any(path.startswith(p) for p in extra)
        out.append({"key": key, "label": label, "href": (base if group == CAMPAIGN else "") + href, "about": about,
                    "group": group, "here": same and (group == CAMPAIGN) == in_campaign})
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


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def needs(db: Session, user: dict) -> list[dict]:
    """What's waiting in the campaign, most important first: one line each, with where to go.
    Admins also get askdnd-wide items (backups, spending), marked `admin`."""
    from app import characters as chars
    from app.admin_usage import usage_summary
    from app.extraction import session_label, timeline
    from app.suggestions import waiting_count

    campaign = web.campaign(db)
    base = web.base(campaign)
    out: list[dict] = []
    if campaign and can_moderate(user):
        n = waiting_count(db)
        if n:
            out.append({"text": f"{_plural(n, 'suggestion')} or draft{'s' if n != 1 else ''} from the table",
                        "sub": "Waiting for your OK", "href": f"{base}/manage/inbox", "go": "Open the inbox"})
    if campaign and is_reviewer(user):
        rows = [(s, review.review_status(s, False)) for s in timeline(db, campaign.id)]
        ready = [s for s, st in rows if st in ("draft", "edited")]
        if ready:
            first = ready[0]
            out.append({"text": f"{session_label(first)} is ready to review" if len(ready) == 1
                        else f"{_plural(len(ready), 'session')} ready to review",
                        "sub": "Nothing reaches the table until you publish it",
                        "href": f"{base}/manage/sessions/{first.id}" if len(ready) == 1 else f"{base}/manage/sessions",
                        "go": "Review it" if len(ready) == 1 else "Sessions"})
        undrafted = sum(1 for s, st in rows if st == "no draft" and s.source == "notes")
        if undrafted:
            out.append({"text": f"Backlog: {_plural(undrafted, 'session')} not drafted yet",
                        "sub": "Publishing a session drafts the next one", "href": f"{base}/manage/sessions", "go": "Sessions"})
        snaps = [ch.snapshot for ch in chars.campaign_characters(db, campaign.id) if ch.ddb_id]
        failed = [s for s in snaps if s and s.status == "error"]
        oldest = min((s.fetched_at for s in snaps if s and s.fetched_at), default=None)
        where = (f"{base}/manage/table", "Table") if can_see_table(user) else ("/party", "Party")
        if failed:
            out.append({"text": f"{_plural(len(failed), 'character')} couldn't refresh from D&D Beyond",
                        "sub": "askdnd shows the last good copy; check the character is Public", "href": where[0], "go": where[1]})
        elif oldest and datetime.now(UTC) - oldest > STALE_CHARACTERS:
            out.append({"text": f"Characters last refreshed {_ago(oldest)}", "sub": "Refresh them from D&D Beyond",
                        "href": where[0], "go": where[1]})
    if is_admin(user):
        b = backup_status(db)
        if b["attention"]:
            out.append({"text": b["text"], "sub": "Only admins see askdnd-wide items like this", "href": "/manage/backups",
                        "go": "Backups", "admin": True})
        u = usage_summary(db)
        if u["limit_reached"]:
            out.append({"text": f"Monthly limit of ${u['limit']:.2f} reached", "sub": "Drafting is paused until next month or a higher limit",
                        "href": "/manage/usage", "go": "Usage", "admin": True})
        elif u["balance"] is not None and u["balance"] < 5:
            out.append({"text": f"About ${u['balance']:.2f} of Claude credit left", "sub": "Top up on the Anthropic console, then record it",
                        "href": "/manage/usage", "go": "Usage", "admin": True})
    return out


@router.get("/manage")
def needs_you(request: Request, db: Session = Depends(get_db)):
    """The campaign's Manage home: what's waiting, as one list. Admins with no campaign role land on Campaigns."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    pages = pages_for(user, "/manage")
    if not any(p["key"] == "needs" for p in pages):
        if pages:
            return RedirectResponse(pages[0]["href"], status_code=303)
        return web.forbidden(request, "Manage is for the DM, reviewers and admins.")
    return templates.TemplateResponse(request, "manage.html", {
        "items": needs(db, user), "campaign": web.campaign(db),
        "pages": [p for p in pages if p["group"] == CAMPAIGN and p["key"] != "needs"]})


# ------------------------------------------------------------------ old addresses (Manage layout, 2026-10-23)

MOVED = (  # (old address, new address, a campaign page?, its sub-addresses move too)
    ("/admin/sessions", "/manage/sessions", True, True),  # every session's review page too
    ("/admin/notes/snapshots", "/manage/sessions/doc/snapshots", True, True),
    ("/admin/notes/images", "/manage/sessions/doc/images", True, True),
    ("/admin/notes", "/manage/sessions/doc", True, False),  # not /admin/notes/callback: Google sends people back there
    ("/suggestions", "/manage/inbox", True, False),
    ("/admin/history", "/manage/history", True, False),
    ("/admin/people", "/manage/table", True, False),
    ("/admin/characters", "/manage/table", True, False),
    ("/admin/import", "/manage/backups", False, False),
    ("/admin/usage", "/manage/usage", False, False),
)


def _mover(new: str, in_campaign: bool):
    def moved(request: Request, rest: str = ""):
        query = request.url.query
        return RedirectResponse((web.base() if in_campaign else "") + new + (f"/{rest}" if rest else "") + (f"?{query}" if query else ""),
                                status_code=307)
    return moved


for _old, _new, _here, _below in MOVED:
    router.add_api_route(_old, _mover(_new, _here), methods=["GET"], include_in_schema=False)
    if _below:
        router.add_api_route(_old + "/{rest:path}", _mover(_new, _here), methods=["GET"], include_in_schema=False)


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


# ------------------------------------------------------------------ the DM guide (Brett, 2026-10-22)


def backlog(db: Session) -> dict:
    """What's waiting in the campaign record, for the DM guide's checklist (live numbers, so it shrinks as she works)."""
    from app.extraction import session_label, timeline
    from app.models import Entity, EntityKind, Proposal, Status
    from app.suggestions import waiting_count

    campaign = web.campaign(db)
    if campaign is None:
        return {}
    sessions = timeline(db, campaign.id)
    rows = [(s, review.review_status(s, False)) for s in sessions]
    return {
        "to_draft": [s for s, st in rows if st == "no draft" and s.source == "notes"],
        "to_record": [s for s, st in rows if st == "no draft" and s.source == "transcript"],
        "to_review": [{"s": s, "label": session_label(s), "status": st} for s, st in rows if st in ("draft", "edited")],
        "published": sum(1 for _, st in rows if st == "published"),
        "total": len(rows),
        "proposals": db.scalar(select(func.count()).select_from(Proposal).where(Proposal.status == "pending")) or 0,
        "suggestions": waiting_count(db),
        "hidden": db.scalar(select(func.count()).select_from(Entity).where(
            Entity.campaign_id == campaign.id, Entity.status == Status.DRAFT, Entity.kind != EntityKind.PC)) or 0,
    }


@router.get("/manage/dm-guide")
def dm_guide(request: Request, db: Session = Depends(get_db)):
    """How the campaign record works for the DM, in plain words, with the notes backlog as a live checklist."""
    user = current_user(request)
    if not user:
        return RedirectResponse("/login", status_code=303)
    if not can_moderate(user):
        return web.forbidden(request, "The DM guide is for the DM, reviewers and admins.")
    return templates.TemplateResponse(request, "dm_guide.html", {"b": backlog(db)})
