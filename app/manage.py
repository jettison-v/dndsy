"""The Manage area: one list of its pages, in two groups, and the Needs you page.

- **The campaign** (the DM, reviewers, admins): pages about one campaign, always at its own address
  (/c/<campaign>/manage/…), so they can't act on the wrong one (app/campaign_paths.py sends plain addresses there).
- **askdnd** (admins): pages that are the same for every campaign, at /manage/….

Who may open each page is in app/access.py (`allows()`), through app/auth.py's checks. Old addresses (/admin/…,
/suggestions) are gone: since 2026-10-23 every page has one address.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, config, documents, review, vtt, web
from app.auth import (
    _allows,
    can_moderate,
    can_see_table,
    current_user,
    is_admin,
    is_reviewer,
)
from app.db import get_db
from app.templating import templates

router = APIRouter()

CAMPAIGN, ASKDND = "campaign", "askdnd"
# The one list of Manage's and the gear's pages (The Three Menus, Brett approved all six parts, Nov 13,
# docs/mockups/menus/; The DM's Workspace, Brett chose B, Nov 13, docs/mockups/dm-workspace/): (key, label, address,
# what it's for, group, section, who may open it, extra addresses that belong to it). Each menu, each page's list down
# the left and Manage's home are drawn from it: the same groups, names and order. A group shows its most used pages
# (IN_MENU) and the rest on its own line of small links. A campaign page's address is under the campaign's
# (/c/<campaign>/…). **Who may open a page is a rule's name** in app/access.py `allows()` (Brett, Nov 13: "make sure
# the permission structure is robust and flexible", since what an admin may see may need narrowing): changing who sees
# a page is one line there, and the Table's access chart, the menus and the pages' own checks all follow it.
AFTER, NEXT, TABLE = "After the game", "The next game", "The table"
PEOPLE, TUNING = "People", "Tuning"
PAGES = (
    ("needs", "Needs you", "/manage", "What's waiting, and what you're preparing", CAMPAIGN, AFTER, "moderate", ()),
    ("inbox", "Inbox", "/manage/inbox", "Suggestions from the table and Claude's drafts, waiting for your OK", CAMPAIGN, AFTER, "moderate", ()),
    ("sessions", "Sessions", "/manage/sessions", "Draft, review and publish recaps; the campaign doc", CAMPAIGN, AFTER, "review", ("/manage/proposals",)),
    ("dm-tools", "Items", "/dm", "The campaign's own magic items, played on Battle for whoever carries one", CAMPAIGN, NEXT, "house_rules", ()),
    ("scene-notes", "Scene notes", "/manage/scene-notes", "Your pins on each place of askdnd's table, only yours", CAMPAIGN, NEXT, "scene_notes", ()),
    ("places", "Places and maps", "/manage/places", "The places of askdnd's table and their maps", CAMPAIGN, NEXT, "run_table", ()),
    ("table", "Table", "/manage/table", "Who plays which character, roles, D&D Beyond links", CAMPAIGN, TABLE, "see_table", ()),
    ("house", "House rules", "/manage/house-rules", "Your rulings on how askdnd rolls things at this table", CAMPAIGN, TABLE, "house_rules", ()),
    ("settings", "Settings", "/manage/settings", "The campaign's name, the DM's name, its D&D Beyond id", CAMPAIGN, TABLE, "settings", ()),
    ("history", "History", "/manage/history", "This campaign's changes, with Restore", CAMPAIGN, TABLE, "review", ()),
    # (the DM guide is read, not run: it's in the account menu's Help, not Manage's list; UNLISTED)
    ("guide", "DM guide", "/manage/dm-guide", "How the campaign record works, and getting through the backlog", CAMPAIGN, TABLE, "moderate", ()),
    ("overview", "Overview", "/manage/askdnd", "How askdnd stands: spending, backups, accounts, tools", ASKDND, "", "admin", ()),
    ("feedback", "Feedback", "/manage/feedback", "Notes for Claude from any page, and where each stands", ASKDND, "", "admin", ()),
    ("documents", "Documents", "/manage/documents", "Every guide, plan and design made for askdnd, in one place", ASKDND, "", "admin", ()),
    ("usage", "Usage", "/manage/usage", "Claude spending and balance", ASKDND, "", "admin", ()),
    ("backups", "Backups", "/manage/backups", "Nightly backups, then imports", ASKDND, "", "admin", ()),
    ("accounts", "Accounts", "/manage/accounts", "Who can sign in, who's an admin, their campaigns", ASKDND, PEOPLE, "admin", ()),
    ("campaigns", "Campaigns", "/manage/campaigns", "Every campaign, and starting one", ASKDND, PEOPLE, "admin", ()),
    ("features", "Features", "/manage/features", "Which features the table uses, and on which page", ASKDND, TUNING, "admin", ()),
    ("askdnd-history", "askdnd history", "/manage/history", "Changes to accounts and askdnd as a whole", ASKDND, TUNING, "admin", ()),
    ("corrections", "Tool corrections", "/manage/tool-corrections", "Fixes to how askdnd reads D&D Beyond, for every character", ASKDND, TUNING, "admin", ()),
    ("dice", "Dice tuning", "/manage/dice", "How thrown dice move and how long they stay, for everyone", ASKDND, TUNING, "admin", ()),
    # the D&D Beyond bridge (app/ddb_bridge.py): only where it may run (DDB_BRIDGE=1)
    ("bridge", "D&D Beyond bridge", "/manage/bridge", "Whether it's awake and why, and its timers", ASKDND, TUNING,
     lambda user: config.DDB_BRIDGE and is_admin(user), ()),
    ("design", "Design system", "/manage/design", "Every component and token, for building askdnd", ASKDND, TUNING, "admin", ()),
)
IN_MENU = ("needs", "inbox", "sessions", "dm-tools", "scene-notes", "places", "table", "house", "settings", "history",
           "overview", "feedback", "documents", "usage", "backups", "accounts", "campaigns")  # a group's rows; the rest on its line
NEEDS = {"scene-notes": "vtt_table", "places": "vtt_table"}  # (a page that comes with a feature: listed only where it's on)
UNLISTED = ("guide",)  # (a page of the list that no menu or list down the left shows: the DM guide is the account menu's)
COUNTED = ("needs", "inbox", "feedback")  # with a count of what's waiting (filled in by /manage/counts as the menu opens)


def may(user: dict | None, allowed) -> bool:
    """Whether this person may open a page: its rule's name asked of app/access.py, or (the bridge) its own check."""
    return allowed(user) if callable(allowed) else _allows(user, allowed)


def pages_for(user: dict | None, path: str = "") -> list[dict]:
    """The Manage pages this person can open, with the one they're on marked. `path` is the address without
    /c/<campaign> (app/campaign_paths.py takes it off); a campaign page is "here" only at a campaign's address."""
    if not user:
        return []
    in_campaign = access.path_slug.get() is not None
    base = web.base()
    out = []
    for key, label, href, about, group, section, allowed, extra in PAGES:
        if not may(user, allowed) or (key in NEEDS and not vtt.on(access.current_campaign(), NEEDS[key])):
            continue
        same = path == href or (href != "/manage" and path.startswith(href + "/")) or any(path.startswith(p) for p in extra)
        out.append({"key": key, "label": label, "href": (base if group == CAMPAIGN else "") + href, "about": about,
                    "group": group, "section": section, "menu": key in IN_MENU, "counted": key in COUNTED,
                    "listed": key not in UNLISTED, "planned": False,
                    "here": same and (group == CAMPAIGN) == in_campaign})
        if key == "places" and may(user, "house_rules"):  # (what a DM will make next: listed, never a link, until built)
            from app.homebrew import PLANNED
            out += [{"key": f"planned:{k}", "label": name, "href": "", "about": what, "group": CAMPAIGN, "section": NEXT,
                     "menu": False, "counted": False, "listed": True, "planned": True, "here": False} for k, name, what in PLANNED]
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
    from app.admin_usage import usage_summary
    from app.extraction import session_label, timeline
    from app.models import CampaignCharacter, Character, CharacterSnapshot
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
        status = review.statuses(db, campaign.id)
        rows = [(s, status.get(s.id, "no draft")) for s in timeline(db, campaign.id)]
        ready = [s for s, st in rows if st in ("draft", "edited")]
        if ready:
            first = ready[0]
            out.append({"text": f"{session_label(first)} is ready to review" if len(ready) == 1
                        else f"{_plural(len(ready), 'session')} ready to review",
                        "sub": "Nothing reaches the table until you publish it",
                        "href": f"{base}/manage/sessions/{first.id}" if len(ready) == 1 else f"{base}/manage/sessions",
                        "go": "Review it" if len(ready) == 1 else "Sessions"})
        for s in [s for s, st in rows if st == "read"]:  # (a transcript read: its questions first, then Draft the recap)
            out.append({"text": f"{session_label(s)} has Claude's questions and suggestions",
                        "sub": "Settle them, then draft the recap", "href": f"{base}/manage/sessions/{s.id}", "go": "Open it"})
        undrafted = sum(1 for s, st in rows if st == "no draft" and s.source == "notes")
        if undrafted:
            out.append({"text": f"Backlog: {_plural(undrafted, 'session')} not drafted yet",
                        "sub": "Publishing a session drafts the next one", "href": f"{base}/manage/sessions", "go": "Sessions"})
        snaps = db.execute(select(CharacterSnapshot.status, CharacterSnapshot.fetched_at)  # (not the sheets themselves)
                           .join(CampaignCharacter, CampaignCharacter.character_id == CharacterSnapshot.character_id)
                           .join(Character, Character.id == CharacterSnapshot.character_id)
                           .where(CampaignCharacter.campaign_id == campaign.id, CampaignCharacter.left_on.is_(None),
                                  Character.ddb_id.is_not(None), Character.ddb_id != "")).all()
        failed = [s for s in snaps if s.status == "error"]
        oldest = min((s.fetched_at for s in snaps if s.fetched_at), default=None)
        where = (f"{base}/manage/table", "Table") if can_see_table(user) else ("/party", "Party")
        if failed:
            out.append({"text": f"{_plural(len(failed), 'character')} couldn't refresh from D&D Beyond",
                        "sub": "askdnd shows the last good copy; check the character is Public", "href": where[0], "go": where[1]})
        elif oldest and datetime.now(UTC) - oldest > STALE_CHARACTERS:
            out.append({"text": f"Characters last refreshed {_ago(oldest)}", "sub": "Refresh them from D&D Beyond",
                        "href": where[0], "go": where[1]})
    if is_admin(user):
        from app.tool_corrections_pages import open_count

        n = open_count(db)
        if n:
            out.append({"text": f"{n} tool correction{'s' if n != 1 else ''} to build into askdnd", "admin": True,
                        "sub": "Ask Claude to build them in; each is a patch until then", "href": "/manage/tool-corrections", "go": "Tool corrections"})
        from app import feedback

        notes = db.scalar(select(func.count()).select_from(feedback.Feedback).where(feedback.Feedback.status == "review")) or 0
        if notes:  # (the table's notes for Claude wait for an admin's approval, Brett, Nov 6)
            out.append({"text": f"{notes} note{'s' if notes != 1 else ''} from the table to approve", "admin": True,
                        "sub": "Approve sends one to Claude; Delete drops it", "href": "/manage/feedback?tab=review", "go": "Feedback"})
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
    from app import workspace

    campaign = web.campaign(db)
    return templates.TemplateResponse(request, "manage.html", {
        "items": needs(db, user), "campaign": campaign,
        "pages": [p for p in pages if p["group"] == CAMPAIGN and p["key"] != "needs" and p["listed"] and not p["planned"]],
        **(workspace.workbench(db, request, user, campaign) if campaign else {"tiles": []})})


@router.get("/manage/counts")  # under the campaign: /c/<campaign>/manage/counts
def counts(request: Request, db: Session = Depends(get_db)):
    """What's waiting, for the counts beside Needs you and Inbox (asked for when the Manage menu opens, and by Manage
    pages, so no other page waits for them)."""
    from app import feedback
    from app.suggestions import waiting_count

    user = current_user(request)
    mine = {"feedback": feedback.for_you(db)} if is_admin(user) else {}  # (notes waiting for an admin: to approve, or Claude's questions)
    if not user or not can_moderate(user) or web.campaign(db) is None:
        return JSONResponse(mine, headers={"Cache-Control": "no-store"})
    return JSONResponse({"needs": len(needs(db, user)), "inbox": waiting_count(db), **mine}, headers={"Cache-Control": "no-store"})


@router.get("/manage/askdnd")
def overview(request: Request, db: Session = Depends(get_db)):
    """Manage › askdnd › Overview: how each admin page stands, one card each, so most days none needs opening."""
    from app.admin_usage import usage_summary
    from app.models import Campaign, User
    from app.tool_corrections_pages import open_count

    user, stop = web.require(request, is_admin, "askdnd's admin pages are for admins.")
    if stop:
        return stop
    u = usage_summary(db)
    b = backup_status(db)
    people = [access.level(p.email) for p in db.scalars(select(User))]
    camps = list(db.scalars(select(Campaign)))
    fixes = open_count(db)
    state = {
        "usage": (f"${u['month']:.2f} of ${u['limit']:.2f} this month" if u["limit"] is not None else f"${u['month']:.2f} this month",
                  "warn" if u["limit_reached"] else "ok"),
        "backups": (b["text"], "warn" if b["attention"] else "ok"),
        "accounts": ((f"{_plural(sum(1 for p in people if p in (access.MEMBER, access.ADMIN)), 'person', 'people')}, "
                     f"{_plural(sum(1 for p in people if p == access.ADMIN), 'admin')}"), ""),
        "campaigns": (f"{_plural(len(camps), 'campaign')}" + (f", {sum(1 for c in camps if c.is_test)} test" if any(c.is_test for c in camps) else ""), ""),
        "corrections": (f"{fixes} to build into askdnd" if fixes else "Nothing to build in", "warn" if fixes else "ok"),
        "documents": (_plural(len(documents.library()), "document"), ""),
    }
    if config.DDB_BRIDGE:
        from app import ddb_bridge

        a = ddb_bridge.awake(db)
        state["bridge"] = ("Awake" if a["awake"] else "Asleep", "ok" if a["awake"] else "")
        db.commit()
    cards = [p | {"state": state.get(p["key"], ("", ""))} for p in pages_for(user, "/manage/askdnd")
             if p["group"] == ASKDND and p["key"] != "overview"]
    return templates.TemplateResponse(request, "manage_askdnd.html", {"cards": cards})


# ------------------------------------------------------------------ old addresses (Manage layout, 2026-10-23)


# ------------------------------------------------------------------ design system (roadmap step 9)

# Tokens shown on the component page, in the order of app.css's :root (the stylesheet is the source of truth)
COLOR_TOKENS = (
    ("Surfaces", ("--bg", "--surface", "--surface-2", "--line", "--line-strong", "--chrome")),
    ("Text", ("--text", "--text-strong", "--muted", "--faint", "--link")),
    ("Story", ("--story-bg", "--story-line", "--story-text")),
    ("Status", ("--red", "--amber", "--green", "--blue", "--violet")),
    ("Action economy", ("--k-action", "--k-bonus", "--k-reaction", "--k-other")),
    ("Conditions", tuple(f"--cond-{slug}" for slug in ("blinded", "charmed", "deafened", "exhaustion", "frightened", "grappled",
                                                       "incapacitated", "invisible", "paralyzed", "petrified", "poisoned", "prone",
                                                       "restrained", "stunned", "unconscious", "enlarged", "flying", "water-breathing",
                                                       "concentration", "dark", "dark-edge"))),
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
    status = review.statuses(db, campaign.id)
    rows = [(s, status.get(s.id, "no draft")) for s in sessions]
    return {
        "to_draft": [s for s, st in rows if st == "no draft" and s.source == "notes"],
        "to_record": [s for s, st in rows if st == "no draft" and s.source == "transcript"],
        "to_review": [{"s": s, "label": session_label(s), "status": st} for s, st in rows if st in ("read", "draft", "edited")],
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
