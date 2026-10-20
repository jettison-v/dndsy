"""Who can sign in, and what they can do.

Access levels: player < reviewer < admin.
- Player: reads everything for the table and suggests corrections.
- Reviewer: also drafts, edits and publishes sessions and the campaign record,
  and refreshes characters.
- Admin: also People, Characters, Usage, Data (import) and the campaign doc.

Admins set people's access on Manage › People (users.access; blank means "not
set here", e.g. someone imported but not invited yet). The Railway
variables still work and act as a floor: ADMIN_EMAILS are owners who are always
admin (so nobody can lock the owner out), REVIEWER_EMAILS are at least reviewers,
ALLOWED_EMAILS can at least sign in.

Separately, a person can be marked as the DM. The DM never sees character
notes, whatever their access level (CLAUDE.md), and decides on suggestions and
adds pictures and glossary entries whatever their level.

`allows()` below is the one list of these rules: app/auth.py's checks use it, and
the chart on Manage › People is drawn from it.

Access is checked on every request, so the rows are cached in memory for a few
seconds and reloaded after any change made on the People page.
"""

import time
from collections.abc import Callable

from sqlalchemy import select

from app import config

PLAYER, REVIEWER, ADMIN, REMOVED = "player", "reviewer", "admin", "removed"
LEVELS = [PLAYER, REVIEWER, ADMIN]
LABELS = {PLAYER: "Player", REVIEWER: "Reviewer", ADMIN: "Admin"}
RANK = {None: -1, PLAYER: 0, REVIEWER: 1, ADMIN: 2}
CACHE_SECONDS = 10


def _load_from_db() -> dict[str, dict]:
    from app.db import SessionLocal, engine

    if engine is None:
        return {}
    with SessionLocal() as db:
        return rows_from(db)


def rows_from(db) -> dict[str, dict]:
    from app.models import CampaignMember, Role, User

    dms = set(db.scalars(select(CampaignMember.user_id).where(CampaignMember.role == Role.DM)))
    return {
        u.email.lower(): {"access": u.access, "is_dm": u.is_dm or u.id in dms}
        for u in db.scalars(select(User))
    }


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
    """The person's access level, or None if they can't sign in."""
    if not email:
        return None
    email = email.strip().lower()
    if is_owner(email):
        return ADMIN
    stored = ((_rows() if rows is None else rows).get(email) or {}).get("access")
    if stored == REMOVED:
        return None  # removed on the People page
    floor = REVIEWER if config.is_allowed(email, config.REVIEWER_EMAILS) else (
        PLAYER if config.is_allowed(email, config.ALLOWED_EMAILS) else None)
    stored = stored if stored in LEVELS else None
    return max(floor, stored, key=lambda x: RANK[x])


def is_dm(email: str | None) -> bool:
    row = _rows().get((email or "").strip().lower())
    return bool(row and row["is_dm"])


# ------------------------------------------------------------------ what each level may do
# The single list of rules. app/auth.py (and pictures, suggestions) ask these, and the
# chart on Manage › People is drawn from them, so the chart can't drift from the app.

def allows(rule: str, lvl: str | None, dm: bool = False) -> bool:
    """May someone with this access level (and DM tick) do `rule`?"""
    if lvl not in LEVELS:
        return False
    staff = lvl in (REVIEWER, ADMIN)
    return {
        "read": True,                       # recaps, sessions, campaign record, map, every character sheet
        "suggest": True,                    # corrections and additions (the DM's go straight in)
        "player_notes": not dm,             # read players' notes, stars, reminders and shortlists
        "moderate": staff or dm,            # decide on the table's suggestions
        "story_extras": staff or dm,        # pictures on campaign pages, glossary entries
        "review": staff,                    # recaps, Claude's questions, entries (names, descriptions), character refresh
        "admin": lvl == ADMIN,              # People, Characters, Usage, Data, campaign doc, regrouping
    }[rule]


# (group, what it covers, rule; "own" = only on the character the person plays)
CHART = [
    ("Read", "Recaps, sessions, the campaign record, the map", "read"),
    ("Read", "Every character's page (Play and Sheet) and Party", "read"),
    ("Read", "Players' notes, stars, reminders and shortlists", "player_notes"),
    ("Contribute", "Suggest corrections and additions", "suggest"),
    ("Contribute", "Notes, stars, reminders, shortlists and the Wild Shape switch", "own"),
    ("Run the table", "Decide on the table's suggestions", "moderate"),
    ("Run the table", "Add pictures and glossary entries", "story_extras"),
    ("Run the table", "Draft, edit and publish recaps; answer Claude's questions", "review"),
    ("Run the table", "Edit entries (names, spellings, descriptions); refresh characters", "review"),
    ("Set up", "People: invite, access, DM tick, who plays which character", "admin"),
    ("Set up", "Characters: D&D Beyond links and regrouping", "admin"),
    ("Set up", "Usage (Claude spending), Data (import), the campaign doc", "admin"),
]
# Things askdnd doesn't do for anyone, so nobody expects them
NOT_INCLUDED = [
    "Change anything on D&D Beyond (prepare spells, learn Wild Shape forms, level up): do that there, then refresh",
    "Send email or invitations: tell people yourself once you've added them here",
    "Show anyone's Google account beyond their name, email and picture",
    "Let anyone remove or demote the owner (set on Railway)",
]


def chart() -> dict:
    """The People page's access chart: a cell per level, and what the DM tick changes."""
    rows = []
    for group, what, rule in CHART:
        if rule == "own":
            cells = ["own"] * len(LEVELS)
            dm = "never"
        else:
            cells = ["yes" if allows(rule, lv) else "no" for lv in LEVELS]
            gains = allows(rule, PLAYER, True) and not allows(rule, PLAYER)
            loses = allows(rule, ADMIN) and not allows(rule, ADMIN, True)
            dm = "gains" if gains else "never" if loses else "same"
        rows.append({"group": group, "what": what, "cells": cells, "dm": dm})
    groups = [(g, [r for r in rows if r["group"] == g]) for g in dict.fromkeys(r["group"] for r in rows)]
    return {"levels": [LABELS[lv] for lv in LEVELS], "rows": rows, "groups": groups, "not_included": NOT_INCLUDED}


def summary(lvl: str | None, dm: bool) -> str:
    """One line for a person's row on People: what this access lets them do."""
    if lvl not in LEVELS:
        return "Can't sign in."
    parts = {
        ADMIN: "Everything, including setting up people and characters",
        REVIEWER: "Reads everything; runs recaps, entries and suggestions",
        PLAYER: "Reads everything and suggests corrections",
    }[lvl]
    if dm:
        parts += ("; as DM, decides on suggestions and adds pictures and glossary entries, " if lvl == PLAYER else "; as DM, ") + \
            "never sees players' notes, stars or reminders"
    return parts + "."

