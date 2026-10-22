"""Who can sign in, and what they can do.

Two kinds of role (data organization step 2, docs/plans/2026-10-21-data-organization.md):
- **Tool roles**, about askdnd as a whole (users.access): owner, admin or member.
  Admins set up people, characters, spending and imports. Owners are ADMIN_EMAILS
  on Railway and are always admins, so nobody can lock them out.
- **Campaign roles**, about one table (campaign_members.role): DM, reviewer or player.
  Reviewers draft, edit and publish recaps and the campaign record. The DM does
  everything a reviewer does in their campaign and never sees the notes of the
  characters in it (CLAUDE.md).

Admins set both on Manage › People. The Railway variables still act as a floor:
ALLOWED_EMAILS can sign in, REVIEWER_EMAILS are at least reviewers in every campaign.

`allows()` below is the one list of these rules: app/auth.py's checks use it, and
the chart on Manage › People is drawn from it.

Access is checked on every request, so the rows are cached in memory for a few
seconds and reloaded after any change made on the People page.
"""

import time
from collections.abc import Callable

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
    """{email: {"access": tool role, "roles": {campaign id: role}, "first": the first campaign's id}}."""
    from app.models import Campaign, CampaignMember, User

    first = db.scalar(select(Campaign.id).order_by(Campaign.id))
    roles: dict[int, dict[int, str]] = {}
    for m in db.scalars(select(CampaignMember).where(CampaignMember.left_on.is_(None))):
        roles.setdefault(m.user_id, {})[m.campaign_id] = m.role.value
    return {u.email.lower(): {"access": u.access, "roles": roles.get(u.id, {}), "first": first} for u in db.scalars(select(User))}


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
        return None  # removed on the People page
    if stored in TOOL_ROLES:
        return stored
    listed = config.is_allowed(email, config.ALLOWED_EMAILS) or config.is_allowed(email, config.REVIEWER_EMAILS)
    return MEMBER if listed else None


def role(email: str | None, campaign_id: int | None = None, rows: dict[str, dict] | None = None) -> str | None:
    """The person's role in a campaign (the first campaign if none is given), or None."""
    email = (email or "").strip().lower()
    row = (_rows() if rows is None else rows).get(email) or {}
    r = (row.get("roles") or {}).get(campaign_id or row.get("first"))
    if r in (None, PLAYER) and config.is_allowed(email, config.REVIEWER_EMAILS):
        return REVIEWER
    return r


def is_dm(email: str | None, campaign_id: int | None = None) -> bool:
    return role(email, campaign_id) == DM


# ------------------------------------------------------------------ what each role may do
# The single list of rules. app/auth.py (and pictures, suggestions) ask these, and the
# chart on Manage › People is drawn from them, so the chart can't drift from the app.

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
        "admin": tool == ADMIN,             # People, Characters, Usage, Data, campaign doc, regrouping
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
    ("Set up askdnd", "People: invite, roles, who plays which character", "admin"),
    ("Set up askdnd", "Characters: D&D Beyond links and tool corrections", "admin"),
    ("Set up askdnd", "Usage (Claude spending), Data (import), the campaign doc", "admin"),
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
    """The People page's access chart: a cell per campaign role, plus Admin."""
    rows = []
    for group, what, rule in CHART:
        cells = ["own"] * len(COLUMNS) if rule == "own" else [
            "yes" if allows(rule, tool, r) else "no" for _, tool, r in COLUMNS]
        rows.append({"group": group, "what": what, "cells": cells})
    groups = [(g, [r for r in rows if r["group"] == g]) for g in dict.fromkeys(r["group"] for r in rows)]
    return {"columns": [c[0] for c in COLUMNS], "rows": rows, "groups": groups, "not_included": NOT_INCLUDED}


def summary(tool: str | None, campaign_role: str | None) -> str:
    """One line for a person's row on People: what they can do in this campaign."""
    if tool not in TOOL_ROLES:
        return "Can't sign in."
    parts = {
        DM: "Runs this campaign (everything a reviewer does); never sees its players' notes, pins, shortlists or reminders",
        REVIEWER: "Reads everything; runs recaps, entries and suggestions",
        PLAYER: "Reads everything and suggests corrections",
        None: "No role in this campaign yet",
    }[campaign_role]
    if tool == ADMIN:
        parts += "; as admin, also sets up people, characters and spending"
    return parts + "."
