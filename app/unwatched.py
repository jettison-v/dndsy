"""Sheets no extension watches, read every 30 seconds (roadmap, Brett Nov 6): a sheet changed where no askdnd extension
sees it (the D&D Beyond app on a phone, a laptop without it) used to reach askdnd only at the next 2.5-minute page sync.
While the bridge is awake (app/ddb_bridge.py `awake`: someone is playing, a fight runs or a change waits), the server
reads each such character itself every TICK, the pace the extension keeps for open sheets. The server decides, so open
pages can't multiply it, and one copy of the app does it at a time (a Postgres advisory lock). Faster wouldn't help:
D&D Beyond's public copy can trail a save by a minute or two.

A character counts as watched while its own sheet was heard by its player's extension in the last live.REACH; those
are read by the extension itself. Test copies share a real sheet, so they're never read here (the real one is).
"""

import asyncio
import logging
import os
from datetime import timedelta

from sqlalchemy import func, select
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
    return [c for c in rows if not ddb_bridge.own_sheet(c)]


def tick(db: Session) -> list[int]:
    """One round: read every unwatched character not read in the last MIN_AGE, while the bridge is awake. Returns the
    ids read."""
    from app import ddb_bridge, live

    if not config.DDB_BRIDGE or not ddb_bridge.awake(db)["awake"]:
        return []
    read = []
    for ch in unwatched(db):
        if live.maybe_refresh(db, ch, MIN_AGE):
            read.append(ch.id)
    return read


def run_once() -> list[int]:
    """A tick on its own connection, only when this copy of the app holds the lock (another copy may be reading)."""
    from app.db import SessionLocal, engine

    with engine.connect() as hold:
        got = hold.execute(select(func.pg_try_advisory_lock(LOCK))).scalar()
        hold.commit()  # (the lock outlives the transaction: nothing stays open while D&D Beyond answers)
        if not got:
            return []
        try:
            with SessionLocal() as db:
                return tick(db)
        finally:
            hold.execute(select(func.pg_advisory_unlock(LOCK)))
            hold.commit()


async def loop() -> None:
    """Started with the app (app/main.py) where the bridge runs: a tick every TICK seconds, never stopping on an error."""
    while True:
        await asyncio.sleep(TICK)
        try:
            await asyncio.to_thread(run_once)
        except Exception:  # noqa: BLE001 - D&D Beyond or the database away for a moment: the next tick tries again
            log.warning("Reading unwatched sheets failed this time", exc_info=True)
