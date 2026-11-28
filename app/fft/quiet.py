"""The quiet hours (Brett, Nov 28): from 11 PM to 7 AM, the table's time, Claude looks at claude.ai once an hour, not
every 10 minutes; askdnd still wakes Claude at once. One rule for both sides: the listener (scripts/feedback.py `wait`)
and Handoffs' "Claude's look at claude.ai" row (app/fft/handoffs.py), so a look isn't called missed in the night."""

from datetime import datetime, timedelta

from app.config import TABLE_TIME

FROM, TO = 23, 7  # (11 PM to 7 AM)
EVERY = timedelta(hours=1)  # (a look in the quiet hours)
DAY_EVERY = timedelta(minutes=10)  # (a look by day: the listener's --wake)


def quiet(at: datetime) -> bool:
    h = at.astimezone(TABLE_TIME).hour
    return h >= FROM or h < TO


def next_look(last: datetime, every: timedelta = DAY_EVERY) -> datetime:
    """When claude.ai is next due a look after `last` (aware): `every` later by day; when that falls in the quiet
    hours, an hour after the last look (or `every`, if longer), never past 7 AM, so the morning's first look is on time.
    Both choices are at or after `last + every`, so the quiet hours never make a look sooner."""
    due = last + every
    if not quiet(due):
        return due
    t = due.astimezone(TABLE_TIME)
    end = t.replace(hour=TO, minute=0, second=0, microsecond=0)
    if t.hour >= FROM:
        end += timedelta(days=1)
    return min(last + max(every, EVERY), end)
