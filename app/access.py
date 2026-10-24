"""Who can sign in, and what they can do.

Two kinds of role (data organization step 2, docs/plans/2026-10-21-data-organization.md):
- **Tool roles**, about askdnd as a whole (users.access): owner, admin or member.
  Admins set up people, characters, spending and imports. Owners are ADMIN_EMAILS
  on Railway and are always admins, so nobody can lock them out.
- **Campaign roles**, about one table (campaign_members.role): DM, reviewer or player.
  Reviewers draft, edit and publish recaps and the campaign record. The DM does
  everything a reviewer does in their campaign and never sees the notes of the
  characters in it (CLAUDE.md).

Admins set tool roles on Manage › Accounts and campaign roles on each campaign's Manage › Table.
The Railway variables still act as a floor:
ALLOWED_EMAILS can sign in, REVIEWER_EMAILS are at least reviewers in every campaign.

`allows()` below is the one list of these rules: app/auth.py's checks use it, and
the chart on Manage › Table is drawn from it.

Access is checked on every request, so the rows are cached in memory for a few
seconds and reloaded after any change made on Accounts or Table.
"""

import time
from collections.abc import Callable
from contextvars import ContextVar

from sqlalchemy import select

from app import config

# Tool roles (users.access). "removed" can't sign in; None = not set here (imported, never invited).
MEMBER, ADMIN, REMOVED = "member", "admin", "removed"
TOOL_ROLES = [MEMBER, ADMIN]
TOOL_LABELS = {MEMBER: "Member", ADMIN: "Admin"}
# Campaign roles (campaign_members.role)
PLAYER, REVIEWER, DM = "player", "reviewer", "dm"
ROLES = [DM, REVIEWER, PLAYER]
ROLE_LABELS = {DM: "DM", REVIEWER: "Reviewer", PLAYER: "Player"}
CACHE_SECONDS = 10


def _load_from_db() -> dict[str, dict]:
    from app.db import SessionLocal, engine

    if engine is None:
        return {}
    with SessionLocal() as db:
        return rows_from(db)


def rows_from(db) -> dict[str, dict]:
    """{email: {"access": tool role, "roles": {campaign id: role}, "current": the campaign they last opened, "dice": their
    dice (app/dice.py)}}, plus
    CAMPAIGNS: [{"id", "slug", "name", "is_test", "vtt_pieces"}] (every campaign, oldest first)."""
    from app.models import Campaign, CampaignMember, User

    roles: dict[int, dict[int, str]] = {}
    for m in db.scalars(select(CampaignMember).where(CampaignMember.left_on.is_(None))):
        roles.setdefault(m.user_id, {})[m.campaign_id] = m.role.value
    from app.dice import prefs

    out: dict = {u.email.lower(): {"access": u.access, "roles": roles.get(u.id, {}), "current": u.current_campaign_id,
                                   "dice": prefs(u)} for u in db.scalars(select(User))}
    out[CAMPAIGNS] = [{"id": c.id, "slug": c.slug, "name": c.name, "is_test": c.is_test, "vtt_pieces": list(c.vtt_pieces or [])} for c in db.scalars(select(Campaign).order_by(Campaign.id))]
    return out


CAMPAIGNS = "@campaigns"  # not an email, so it never matches a person
loader: Callable[[], dict[str, dict]] = _load_from_db
_cache: dict = {"rows": {}, "at": 0.0}


def invalidate() -> None:
    _cache["at"] = 0.0


def _rows() -> dict[str, dict]:
    if time.monotonic() - _cache["at"] > CACHE_SECONDS:
        try:
            _cache["rows"] = loader()
        except Exception:
            pass  # database unavailable: keep the last rows; the env lists still work
        _cache["at"] = time.monotonic()
    return _cache["rows"]


# ------------------------------------------------------------------ the campaign you're in
# Set for each request by app/campaign_paths.py: who is asking, and the campaign in the address (/c/<slug>/…).
viewer: ContextVar[str] = ContextVar("viewer", default="")
path_slug: ContextVar[str | None] = ContextVar("path_slug", default=None)


def campaigns(rows: dict | None = None) -> list[dict]:
    return list(((_rows() if rows is None else rows).get(CAMPAIGNS)) or [])


def campaigns_for(email: str | None, rows: dict | None = None) -> list[dict]:
    """The campaigns this person can open: those they have a role in; every campaign for admins. People on the
    Railway lists with no role anywhere get the first campaign (as before there was more than one)."""
    rows = _rows() if rows is None else rows
    email = (email or "").strip().lower()
    every = campaigns(rows)
    if level(email, rows) is None:
        return []
    if level(email, rows) == ADMIN:
        return every
    mine = set(((rows.get(email) or {}).get("roles") or {}))
    if not mine and (config.is_allowed(email, config.ALLOWED_EMAILS) or config.is_allowed(email, config.REVIEWER_EMAILS)):
        return every[:1]
    return [c for c in every if c["id"] in mine]


def current_campaign(email: str | None = None, rows: dict | None = None) -> dict | None:
    """The campaign this person is in now: the one in the address if they may open it (None if not), else the one
    they last opened, else their first. None if they can't open any. With no one asking (background work, the
    upload API), the first campaign."""
    rows = _rows() if rows is None else rows
    email = (email if email is not None else viewer.get()).strip().lower()
    if not email:
        return (campaigns(rows) or [None])[0]
    mine = campaigns_for(email, rows)
    slug = path_slug.get()
    if slug is not None:
        return next((c for c in mine if c["slug"] == slug), None)
    last = (rows.get(email) or {}).get("current")
    return next((c for c in mine if c["id"] == last), None) or (mine[0] if mine else None)


def current_campaign_id(email: str | None = None) -> int | None:
    c = current_campaign(email)
    return c["id"] if c else None


def is_owner(email: str | None) -> bool:
    return config.is_allowed(email, config.ADMIN_EMAILS)


def level(email: str | None, rows: dict[str, dict] | None = None) -> str | None:
    """The person's tool role (member or admin), or None if they can't sign in."""
    if not email:
        return None
    email = email.strip().lower()
    if is_owner(email):
        return ADMIN
    stored = ((_rows() if rows is None else rows).get(email) or {}).get("access")
    if stored == REMOVED:
        return None  # removed on Manage › Accounts
    if stored in TOOL_ROLES:
        return stored
    listed = config.is_allowed(email, config.ALLOWED_EMAILS) or config.is_allowed(email, config.REVIEWER_EMAILS)
    return MEMBER if listed else None


def role(email: str | None, campaign_id: int | None = None, rows: dict[str, dict] | None = None) -> str | None:
    """The person's role in a campaign (the one they're in now if none is given), or None."""
    email = (email or "").strip().lower()
    rows = _rows() if rows is None else rows
    row = rows.get(email) or {}
    if campaign_id is None:
        here = current_campaign(email, rows)
        campaign_id = here["id"] if here else None
    r = (row.get("roles") or {}).get(campaign_id)
    if r in (None, PLAYER) and config.is_allowed(email, config.REVIEWER_EMAILS):
        return REVIEWER
    return r


def is_dm(email: str | None, campaign_id: int | None = None) -> bool:
    return role(email, campaign_id) == DM


# ------------------------------------------------------------------ what each role may do
# The single list of rules. app/auth.py (and pictures, suggestions) ask these, and the
# chart on Manage › Table is drawn from them, so the chart can't drift from the app.

def allows(rule: str, tool: str | None, campaign_role: str | None = None) -> bool:
    """May someone with this tool role and this role in the campaign do `rule`?"""
    if tool not in TOOL_ROLES:
        return False
    runs = campaign_role in (REVIEWER, DM) or tool == ADMIN  # the DM includes Reviewer (Brett, 2026-10-22)
    return {
        "read": True,                       # recaps, sessions, campaign record, map, every character sheet
        "suggest": True,                    # corrections and additions (the DM's go straight in)
        "player_notes": campaign_role != DM,  # players' notes, pins, reminders: never the campaign's DM, even an admin
        "moderate": runs,                   # decide on the table's suggestions
        "story_extras": runs,               # pictures on campaign pages, glossary entries
        "edit_entries": runs,               # campaign entries: names, spellings, descriptions, relationships
        "review": runs,                     # recaps, Claude's questions, key moments, character refresh
        "house_rules": campaign_role == DM or tool == ADMIN,  # the DM's rulings on how askdnd rolls and reads things
        "see_table": campaign_role == DM or tool == ADMIN,  # Manage › Table: who plays which character (Brett, 2026-10-23)
        "settings": campaign_role == DM or tool == ADMIN,   # the campaign's name, DM's name, D&D Beyond id (Brett, 2026-10-23)
        "admin": tool == ADMIN,             # accounts, roles, characters, Usage, backups, campaign doc, tool corrections
    }[rule]


# (group, what it covers, rule; "own" = only on the character the person plays)
CHART = [
    ("Read", "Recaps, sessions, the campaign record, the map", "read"),
    ("Read", "Every character's page (Battle and Sheet) and Party", "read"),
    ("Read", "Players' notes, pins, reminders and shortlists", "player_notes"),
    ("Contribute", "Suggest corrections and additions", "suggest"),
    ("Contribute", "Notes, pins, reminders, shortlists, the Wild Shape switch and table rolls", "own"),
    ("Run the table", "Decide on the table's suggestions", "moderate"),
    ("Run the table", "Add pictures and glossary entries", "story_extras"),
    ("Run the table", "Draft, edit and publish recaps; answer Claude's questions", "review"),
    ("Run the table", "Edit campaign entries (names, spellings, descriptions, relationships)", "edit_entries"),
    ("Run the table", "Refresh characters from D&D Beyond", "review"),
    ("Run the table", "House rules: how askdnd rolls things at this table", "house_rules"),
    ("Run the table", "See the Table: who plays which character, D&D Beyond links", "see_table"),
    ("Run the table", "Settings: the campaign's name, the DM's name, which finished VTT pieces the table gets", "settings"),
    ("Set up askdnd", "Table: roles, who plays which character, adding characters and D&D Beyond links", "admin"),
    ("Set up askdnd", "Accounts (who can sign in, admins), Campaigns, test campaigns, tool corrections", "admin"),
    ("Set up askdnd", "Usage (Claude spending), backups and imports, the campaign doc", "admin"),
]
# The chart's columns: the three campaign roles, then Admin (a tool role, on top of any campaign role)
COLUMNS = [("Player", MEMBER, PLAYER), ("Reviewer", MEMBER, REVIEWER), ("DM", MEMBER, DM), ("Admin", ADMIN, PLAYER)]
# Things askdnd doesn't do for anyone, so nobody expects them
NOT_INCLUDED = [
    "Change anything on D&D Beyond (prepare spells, learn Wild Shape forms, level up): do that there, then refresh",
    "Send email or invitations: tell people yourself once you've added them here",
    "Show anyone's Google account beyond their name, email and picture",
    "Let anyone remove or demote the owner (set on Railway)",
]


def chart() -> dict:
    """The access chart on Manage › Table: a cell per campaign role, plus Admin."""
    rows = []
    for group, what, rule in CHART:
        cells = ["own"] * len(COLUMNS) if rule == "own" else [
            "yes" if allows(rule, tool, r) else "no" for _, tool, r in COLUMNS]
        rows.append({"group": group, "what": what, "cells": cells})
    groups = [(g, [r for r in rows if r["group"] == g]) for g in dict.fromkeys(r["group"] for r in rows)]
    return {"columns": [c[0] for c in COLUMNS], "rows": rows, "groups": groups, "not_included": NOT_INCLUDED}


def summary(tool: str | None, campaign_role: str | None) -> str:
    """One line for a person's row on Table: what they can do in this campaign."""
    if tool not in TOOL_ROLES:
        return "Can't sign in."
    parts = {
        DM: "Runs this campaign (everything a reviewer does); never sees its players' notes, pins, shortlists or reminders",
        REVIEWER: "Reads everything; runs recaps, entries and suggestions",
        PLAYER: "Reads everything and suggests corrections",
        None: "No role in this campaign yet",
    }[campaign_role]
    if tool == ADMIN:
        parts += "; as admin, also sets up accounts, characters and spending"
    return parts + "."
