"""What Found, Fixed, Tried uses of the app it lives in: the one door between the tool and askdnd (the backend
look-back's LB3, Brett's pick A, Nov 25; "FFT is a product", Nov 20: Brett's reusable tool, askdnd its first user).

Everything in app/fft/ that needs askdnd itself (who someone is, what they may do, View as, campaigns and characters,
the page library, settings, the backup's runs, route speeds) asks here, never askdnd's modules directly, so a second
app hosting the tool replaces this file and nothing else. The platform pieces every host has (the database, templates,
the page helpers, config, the live connection, file storage, errors, timing, the one-copy lock and email) are used
directly. tests/test_fft_boundary.py keeps it so. No table moves: the tool's tables stay in askdnd's database.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access as _access
from app import documents  # noqa: F401  (the page library, Backstage › Documents: the tool's questions open its pages)
from app.documents import doc_id, find  # noqa: F401  (a page's id in the library, and the page with that id)
from app.models import ToolSetting  # noqa: F401  (a key and a JSON value: the tool's own small settings)

ADMIN = _access.ADMIN


# ------------------------------------------------------------------ people and sign-in

def signed_in(request) -> dict | None:
    """The signed-in person ({email, name}) or None."""
    from app.auth import current_user

    return current_user(request)


def is_admin(user: dict | None) -> bool:
    from app.auth import is_admin as admin

    return admin(user)


def level(email: str | None):
    """Their access level (ADMIN for an admin), None for no account."""
    return _access.level(email)


def role(email: str | None) -> str | None:
    """Their role at the table (dm, player, reviewer), if any."""
    return _access.role(email)


def sends_feedback(email: str | None) -> bool:
    """Whether they may send a note (admins and the accounts switched on for it)."""
    return _access.sends_feedback(email)


def account(db: Session, user: dict | None):
    """Their account row (created on first sight), or None."""
    from app import picks

    return picks.user_row(db, user)


def account_by_id(db: Session, user_id: int | None):
    from app.models import User

    return db.get(User, user_id) if user_id else None


def first_name(name: str) -> str:
    """A first name only (Claude and the tool's pages never show a full name or an email)."""
    from app.extraction import first_name as first

    return first(name)


# ------------------------------------------------------------------ View as and campaigns

def viewing(session) -> dict | None:
    """Whom an admin is viewing as, if anyone."""
    from app import view_as

    return view_as.viewing(session)


def view_refusal(real_email: str, as_email: str) -> str:
    """Why View as may not show this person ("" when it may)."""
    from app import view_as

    return view_as.refusal(real_email, as_email)


def character_exists(db: Session, character_id: int) -> bool:
    from app.models import Character

    return db.get(Character, character_id) is not None


def character_player(db: Session, character_id: int):
    """The account that plays a character, or None (no character, or no player in askdnd)."""
    from app.models import Character

    ch = db.get(Character, character_id)
    return account_by_id(db, ch.owner_id) if ch is not None and ch.owner_id else None


def current_campaign(email: str) -> dict | None:
    """The campaign a person has open ({id, …}), if any."""
    return _access.current_campaign(email)


def remember_campaign(db: Session, email: str, campaign_id: int) -> None:
    """Open this campaign for them next (a test round goes back where it started)."""
    from app import campaign_paths

    campaign_paths.remember_in(db, email, campaign_id)


def test_campaign_name(db: Session, *, slug: str = "", character_id: int | None = None) -> str:
    """The name of the test campaign a page is in, by its address's slug or a character in it; "" when it isn't one."""
    from app.models import Campaign, CampaignCharacter

    if slug:
        camp = db.scalar(select(Campaign).where(Campaign.slug == slug))
        return camp.name if camp is not None and camp.is_test else ""
    if character_id is not None:
        camp = db.scalar(select(Campaign).join(CampaignCharacter, CampaignCharacter.campaign_id == Campaign.id)
                         .where(CampaignCharacter.character_id == character_id, CampaignCharacter.left_on.is_(None), Campaign.is_test.is_(True)))
        return camp.name if camp is not None else ""
    return ""


def review_characters(db: Session) -> list[str]:
    """The characters a review can look through (Dig into a feature's With which characters; Roadmap item 46): the
    table's own, in its real campaigns, by name; a test campaign's are "the test sheets" (app/data/review_fills.json)."""
    from app.models import Campaign, CampaignCharacter, Character

    return list(db.scalars(select(Character.name).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                           .join(Campaign, Campaign.id == CampaignCharacter.campaign_id)
                           .where(CampaignCharacter.left_on.is_(None), Campaign.is_test.is_(False))
                           .group_by(Character.name).order_by(func.min(Character.id))))


# ------------------------------------------------------------------ the host's jobs and speeds (Development › Scheduled)

def backup_runs(db: Session, name: str, limit: int = 1) -> list[dict]:
    """The backup's latest runs, newest first, as Scheduled shows them ({at, result, words}); it reports to its own table."""
    from app.models import JobRun

    return [{"at": r.finished_at, "result": "ok" if r.status == "ok" else "failed", "words": r.detail[:200] if r.status != "ok" else ""}
            for r in db.scalars(select(JobRun).where(JobRun.name == name).order_by(JobRun.id.desc()).limit(limit))]


def route_speeds(db: Session, days: int) -> dict:
    """Each route's time over the last `days` days, slowest tenth first, and the line a slow one crosses."""
    from app import speed

    return {"routes": speed.week(db, days), "slow_p90_ms": speed.SLOW_P90_MS}
