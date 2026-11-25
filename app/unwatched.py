"""Sheets no extension watches, read every 30 seconds (roadmap, Brett Nov 6): a sheet changed where no askdnd extension
sees it (the D&D Beyond app on a phone, a laptop without it) used to reach askdnd only at the next 2.5-minute page sync.
While the bridge is awake (app/ddb_bridge.py `awake`: someone is playing, a fight runs or a change waits), the server
reads each such character itself every TICK, the pace the extension keeps for open sheets. The server decides, so open
pages can't multiply it, and one copy of the app does it at a time (a Postgres advisory lock). Faster wouldn't help:
D&D Beyond's public copy can trail a save by a minute or two.

A character counts as watched while its own sheet was heard by its player's extension in the last live.REACH; those
are read by the extension itself. One read from its sheet (or through the DM's browser) in the last
characters.PUBLIC_TRAILS isn't read either: D&D Beyond's public copy can be behind it, and `characters.store` would keep
the sheet's own anyway (Nov 8: these reads put spent uses back). Test copies share a real sheet, so they're never read
here (the real one is).
"""

import logging
import os
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config

log = logging.getLogger(__name__)

TICK = int(os.getenv("UNWATCHED_SECONDS", "30") or 0)  # 0: off (the browser tests' servers)
MIN_AGE = timedelta(seconds=25)  # (a little under TICK, so each tick reads each character once)
LOCK = 0x61736B64  # "askd": one copy of the app reads at a time


def unwatched(db: Session) -> list:
    """The characters to read now: in a campaign with Sync with D&D Beyond on, linked to a sheet, at the table now, not
    a test copy, and their own sheet not open with the extension."""
    from app import ddb_bridge, vtt
    from app.models import Campaign, CampaignCharacter, Character

    on = {c.id for c in db.scalars(select(Campaign)) if vtt.on(c, "ddb_bridge")}
    if not on:
        return []
    rows = db.scalars(select(Character).join(CampaignCharacter, CampaignCharacter.character_id == Character.id)
                      .where(CampaignCharacter.campaign_id.in_(on), CampaignCharacter.left_on.is_(None), Character.copy_of_id.is_(None),
                             Character.ddb_id.is_not(None), Character.ddb_id != "").order_by(Character.id))
    from app import characters

    return [c for c in rows if not ddb_bridge.own_sheet(c) and not characters.trails(c.snapshot)]


def tick(db: Session) -> list[int]:
    """One round: ask for every unwatched character not read in the last MIN_AGE (last in line on the jobs queue, a test
    campaign's behind the table's), while the bridge is awake. Returns the ids asked for."""
    from app import ddb_bridge

    if not config.DDB_BRIDGE or not ddb_bridge.awake(db)["awake"]:
        return []
    from app import sheet_reads
    from app.models import Campaign

    tests = set(db.scalars(select(Campaign.id).where(Campaign.is_test.is_(True))))
    # (a test campaign's sheets after the table's: they share the one line, and 13 of them made the table's 4 wait about 2
    # minutes a round; at the back they fill the gaps, Brett Nov 25)
    read = [ch.id for ch in unwatched(db)
            if sheet_reads.request_read(db, ch, min_age=MIN_AGE, by="nobody had it open",
                                        priority=sheet_reads.UNWATCHED_TEST if ch.campaign_id in tests else sheet_reads.UNWATCHED) is not None]
    db.commit()
    return read


def run_once() -> list[int]:
    """A tick on its own connection, only when this copy of the app holds the lock (another copy may be reading)."""
    from app import single

    return single.alone(LOCK, tick, [])


async def loop() -> None:
    """Started with the app (app/main.py) where the bridge runs: a tick every TICK seconds, never stopping on an error."""
    from app import single

    await single.every(TICK, run_once, "Reading unwatched sheets")
