"""The monthly Claude spending limit (CLAUDE.md: "set and respect a monthly spend limit").

The admin sets it on Manage › Usage (campaigns.monthly_limit_usd; blank means no
limit). Every Claude call (drafting a session, checking a written account,
rewriting a description) calls check() first, so once this month's spending
reaches the limit askdnd refuses new calls and says why, instead of spending
more. The Anthropic workspace limit still applies on top of this.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import web
from app.models import ExtractionRun


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent_this_month(db: Session, now: datetime | None = None) -> float:
    q = select(func.coalesce(func.sum(ExtractionRun.cost_usd), 0.0)).where(ExtractionRun.created_at >= month_start(now))
    return float(db.scalar(q) or 0.0)


def limit(db: Session) -> float | None:
    c = web.campaign(db)
    return c.monthly_limit_usd if c else None


def reached(db: Session, now: datetime | None = None) -> str | None:
    """Why askdnd won't call Claude right now, or None if it may."""
    cap = limit(db)
    if cap is None:
        return None
    spent = spent_this_month(db, now)
    if spent < cap:
        return None
    return (f"This month's Claude spending (${spent:.2f}) has reached the ${cap:.2f} monthly limit. "
            "An admin can raise it on Manage › Usage; it resets on the 1st.")


def check(db: Session) -> None:
    """Raise ExtractionError when the limit is reached (the callers record it on the run)."""
    from app.extraction import ExtractionError

    why = reached(db)
    if why:
        raise ExtractionError(why)
