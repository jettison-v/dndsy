"""Drops to 0 Hit Points and deaths, seen as askdnd reads a sheet (Brett, Nov 10: recorded from then on, for Trophy
Case's "downed" numbers). askdnd keeps only a sheet's latest copy, so it can't look back: a drop is noticed when a read
shows Hit Points at 0 that the copy before showed above 0, and a death when a read shows a third failed death save.

D&D Beyond can serve two copies of a sheet for a while after a save (the live test saw it, Nov 10), so a read can show
the old Hit Points again a moment later; a drop of the same kind within WINDOW of the last is the same drop.
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Character, CharacterDown

WINDOW = timedelta(minutes=2)


def _hp(summary: dict | None) -> int | None:
    return ((summary or {}).get("hit_points") or {}).get("current")


def _fails(summary: dict | None) -> int:
    return ((summary or {}).get("death_saves") or {}).get("fail") or 0


def seen(db: Session, character: Character, old: dict | None, new: dict | None, at: datetime) -> list[str]:
    """Compare the copy kept with a new read; keep a drop to 0 or a death. Returns the kinds kept."""
    if not old or not new or _hp(old) is None or _hp(new) is None:
        return []  # (a first read, or one with no Hit Points: nothing to compare)
    kinds = (["down"] if _hp(old) > 0 and _hp(new) == 0 else []) + (["dead"] if _fails(old) < 3 <= _fails(new) else [])
    kept = []
    for kind in kinds:
        last = db.scalar(select(CharacterDown.at).where(CharacterDown.character_id == character.id, CharacterDown.kind == kind)
                         .order_by(CharacterDown.at.desc()).limit(1))
        if last is not None and at - last < WINDOW:
            continue
        db.add(CharacterDown(character_id=character.id, kind=kind, at=at))
        kept.append(kind)
    return kept
