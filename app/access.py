"""Who can sign in, and what they can do.

Access levels: player < reviewer < admin.
- Player: reads everything for the table and suggests corrections.
- Reviewer: also drafts, edits and publishes sessions and the campaign record,
  and refreshes characters.
- Admin: also Notes sync, Import, Usage and People.

Admins set people's access on Manage › People (users.access; blank means "not
set here", e.g. someone imported but not invited yet). The Railway
variables still work and act as a floor: ADMIN_EMAILS are owners who are always
admin (so nobody can lock the owner out), REVIEWER_EMAILS are at least reviewers,
ALLOWED_EMAILS can at least sign in.

Separately, a person can be marked as the DM. The DM never sees character
notes, whatever their access level (CLAUDE.md).

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
