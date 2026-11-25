"""Workshop's reviews (Roadmap item 46, Brett's picks on docs/mockups/review-catalog/, version 6): the catalog
(app/fft/reviews.json, written once as templates; app/data/review_fills.json is what askdnd fills in), when each is next
due, and its runs over time. Read-only: a run's state changes only in app/fft/rules.py.

When a review runs (the pick "Where reviews run": A): a scheduled one at its slot (weekly, Monday 6:00; monthly, the 1st
at 4:00, the table's time), started by the hourly task in the Claude app on Brett's MacBook (`feedback.py review due`),
which also catches up once on the latest missed slot within 7 days; each phase, when Claude ends one; on demand, from
Run now or Run… on Development › Scheduled, within minutes while a session listens, else at that hourly task."""

import json
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.fft.models import FftReview, FftReviewRun

CATALOG = Path(__file__).resolve().parent / "reviews.json"
FILLS = Path(__file__).resolve().parent.parent / "data" / "review_fills.json"
CADENCES = ("weekly", "monthly", "phase", "on_demand", "off")
CADENCE_WORDS = {"weekly": "Weekly", "monthly": "Monthly", "phase": "Each phase", "on_demand": "On demand", "off": "Not now"}
STATES = ("asked", "starting", "running", "waiting", "done", "stopped", "skipped")
LIVE = ("starting", "running", "waiting")  # (one at a time: a run in one of these holds the others)
ENDED = ("done", "stopped", "skipped")
STATE_WORDS = {"asked": "Waiting its turn", "starting": "Starting", "running": "Running", "waiting": "Waiting on you",
               "done": "Done", "stopped": "Stopped", "skipped": "Skipped"}
CATCH_UP = timedelta(days=7)  # a missed slot older than this is skipped (the pick: one catch-up, within 7 days)
WEEKLY_AT, MONTHLY_AT = 6, 4  # the hour, the table's time


@cache
def catalog() -> dict:
    return json.loads(CATALOG.read_text())


@cache
def fills() -> dict:
    return json.loads(FILLS.read_text())


def review(key: str) -> dict | None:
    return next((r for r in catalog()["reviews"] if r["key"] == key), None)


def keys() -> list[str]:
    return [r["key"] for r in catalog()["reviews"]]


def buckets() -> list[dict]:
    """The six buckets, their questions in this product's words ({product}: app/data/review_fills.json)."""
    f = fills()
    return [{**b, "question": b["question"].replace("{product}", f["product"]).replace("{where}", f.get("where", "")).replace(" ?", "?")}
            for b in catalog()["buckets"]]


def setting(db: Session, key: str) -> FftReview | None:
    return db.scalar(select(FftReview).where(FftReview.key == key))


def cadence(db: Session, key: str) -> str:
    """How often it runs: the workspace's own pick, else the catalog's."""
    row = setting(db, key)
    return (row.cadence if row is not None and row.cadence else None) or review(key)["cadence"]


def _local(t: datetime) -> datetime:
    from app.config import TABLE_TIME

    return t.astimezone(TABLE_TIME)


def slot_before(how_often: str, t: datetime) -> datetime | None:
    """The latest slot at or before `t` (aware), or None for a review with no slots (each phase, on demand, not now)."""
    lt = _local(t)
    if how_often == "weekly":
        s = (lt - timedelta(days=lt.weekday())).replace(hour=WEEKLY_AT, minute=0, second=0, microsecond=0)
        return s if s <= lt else s - timedelta(days=7)
    if how_often == "monthly":
        s = lt.replace(day=1, hour=MONTHLY_AT, minute=0, second=0, microsecond=0)
        if s > lt:
            s = (s - timedelta(days=1)).replace(day=1)
        return s
    return None


def slot_after(how_often: str, t: datetime) -> datetime | None:
    """The first slot after `t`."""
    lt = _local(t)
    if how_often == "weekly":
        s = (lt - timedelta(days=lt.weekday())).replace(hour=WEEKLY_AT, minute=0, second=0, microsecond=0)
        return s if s > lt else s + timedelta(days=7)
    if how_often == "monthly":
        s = lt.replace(day=1, hour=MONTHLY_AT, minute=0, second=0, microsecond=0)
        if s > lt:
            return s
        return (s + timedelta(days=32)).replace(day=1)
    return None


def runs(db: Session, key: str | None = None, limit: int = 20) -> list[FftReviewRun]:
    q = select(FftReviewRun).order_by(FftReviewRun.id.desc()).limit(limit)
    if key:
        q = q.where(FftReviewRun.review == key)
    return list(db.scalars(q))


def live_run(db: Session) -> FftReviewRun | None:
    """The run that holds the others (one at a time)."""
    return db.scalar(select(FftReviewRun).where(FftReviewRun.state.in_(LIVE)).order_by(FftReviewRun.id))


def due(db: Session, now: datetime) -> list[str]:
    """The scheduled reviews whose latest slot (within CATCH_UP) has no run since: each is asked once, however many
    slots it missed (the pick: one catch-up for the latest missed time)."""
    out = []
    for key in keys():
        row = setting(db, key)
        if row is None or not row.scheduled:
            continue
        slot = slot_before(cadence(db, key), now)
        if slot is None or now - slot > CATCH_UP:
            continue
        last = db.scalar(select(FftReviewRun.created_at).where(FftReviewRun.review == key).order_by(FftReviewRun.id.desc()).limit(1))
        if last is None or last < slot:
            out.append(key)
    return out


def numbers_over_time(db: Session, key: str, limit: int = 6) -> list[dict]:
    """A review's finished runs, newest first, with the same few numbers (the pass's sixth change: results that line
    up over time)."""
    rows = db.scalars(select(FftReviewRun).where(FftReviewRun.review == key, FftReviewRun.state == "done")
                      .order_by(FftReviewRun.id.desc()).limit(limit))
    return [{"id": r.id, "at": r.ended_at, **{k: (r.result.get("numbers") or {}).get(k, 0) for k in ("found", "fixed", "picks", "open")}}
            for r in rows]


def quiet_streak(db: Session, key: str) -> int:
    """How many of its latest finished runs found nothing in a row (three comes up in Look back at how we work)."""
    n = 0
    for r in numbers_over_time(db, key, 10):
        if r["found"]:
            break
        n += 1
    return n
