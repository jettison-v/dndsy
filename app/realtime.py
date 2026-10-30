"""The live table connection (VTT 0.3, docs/plans/2026-10-22-vtt-roadmap.md): every open page keeps a WebSocket to
askdnd, and when something changes at its campaign's table, askdnd tells every page there within a second.

A message says only *what* changed, never the change itself: {"type": "rolls"} (a table roll, its damage, reroll or
added die) or {"type": "character", "id": 7} (a character's D&D Beyond copy changed). The page then asks for it at the
usual addresses, which decide who may see what, so a DM-only roll's number never travels on the connection. Pages
still poll now and then (app.js "live connection"), so a dropped connection costs speed, never a roll.

How a change travels:
1. `announce(db, …)` during the change; it goes out only after the database commit (a rollback drops it), so a page
   never asks before the change is there.
2. `publish()` sends it on Postgres's NOTIFY channel (`CHANNEL`). Every copy of the app LISTENs there (`listen()`,
   started with the app), so it reaches pages connected to any copy: several workers, several Railway replicas, or the
   old and new copies overlapping during a deploy. If the listener is down, a copy delivers to its own pages directly.
3. Each copy hands it to its pages for that campaign (`deliver()`). A page's outbox keeps each distinct message once,
   so a slow page holds at most one of each, never a growing backlog.

A page is checked when it connects (signed in, its own campaign, from askdnd's own pages) and again every
`RECHECK_SECONDS`, so someone removed from a campaign is cut off.
"""

import asyncio
import json
import logging
import threading
import time
from urllib.parse import urlparse

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app import access, config
from app.auth import current_user

router = APIRouter()
log = logging.getLogger(__name__)

CHANNEL = "askdnd_table"
RECHECK_SECONDS = 60  # how often an open connection checks its person may still see the campaign
REFUSED = 4403  # closing code app.js takes as "don't reconnect"


# ------------------------------------------------------------------ pages connected to this copy
class _Page:
    """One open page: its event loop and the distinct messages waiting for it."""

    def __init__(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.waiting: dict[str, None] = {}  # in order, each message once
        self.wake = asyncio.Event()

    def offer(self, msg: str) -> None:  # on the page's own loop
        self.waiting[msg] = None
        self.wake.set()

    def take(self) -> list[str]:
        out, self.waiting = list(self.waiting), {}
        self.wake.clear()
        return out


_lock = threading.Lock()
_pages: dict[int, set[_Page]] = {}  # campaign id → its pages connected here


def deliver(campaign_id: int, msg: str) -> None:
    """Hand a message to this copy's pages in the campaign. Safe from any thread."""
    with _lock:
        pages = list(_pages.get(campaign_id, ()))
    for page in pages:
        try:
            page.loop.call_soon_threadsafe(page.offer, msg)
        except RuntimeError:
            pass  # that page's connection has just closed


def connected(campaign_id: int) -> int:
    with _lock:
        return len(_pages.get(campaign_id, ()))


# ------------------------------------------------------------------ announcing a change
_bus = {"up": False}  # this copy's listener is on the channel


def publish(campaign_id: int | None, kind: str, **data) -> None:
    """Tell every page open in this campaign, on any copy of the app, that `kind` changed."""
    if campaign_id is None:
        return
    msg = json.dumps({"type": kind, **data})
    if _bus["up"]:
        try:
            from app.db import engine

            with engine.connect() as conn:
                conn.execute(text("SELECT pg_notify(:channel, :payload)"),
                             {"channel": CHANNEL, "payload": json.dumps({"c": campaign_id, "m": msg})})
                conn.commit()
            return
        except Exception:
            log.warning("Couldn't send a live update through Postgres; delivering it on this copy only", exc_info=True)
    deliver(campaign_id, msg)


def announce(db: Session, campaign_id: int | None, kind: str, **data) -> None:
    """publish() once `db` commits (nothing if it rolls back)."""
    db.info.setdefault("announce", []).append((campaign_id, kind, data))


# What the table sees of a character: a change to any of these, however it's made (a read of D&D Beyond, a condition,
# Concentration, Wild Shape, a rename, a change waiting for D&D Beyond or its log), tells every page in its campaign on
# save, and the pages showing it swap in their new copy (app.js showInPlace). Players' own pins, notes and reminders
# aren't here: they're theirs (the DM never sees them), and the page they were made on shows them at once.
TABLE_SEES = {"Character": ("name", "owner_id", "wild_shape", "concentration", "conditions"), "CharacterSnapshot": ("summary",),
              "CampaignCharacter": ("item_choices",),
              "BridgeIntent": ("state", "error"), "BridgeLog": ("text",)}
# And of the campaign itself: the fight heard from D&D Beyond's VTT (app/fight.py), announced as "game"
CAMPAIGN_SEES = {"Campaign": ("fight",)}


def _stored(value) -> str:
    """A value as the database gives it back (tuples become lists, number keys text), to compare two."""
    return json.dumps(json.loads(json.dumps(value, default=str)), sort_keys=True)


@event.listens_for(Session, "before_flush")
def _character_changes(db: Session, flush_context, instances) -> None:
    from sqlalchemy import inspect

    from app.models import Character

    def changed(obj, fields) -> bool:
        state = inspect(obj)
        return any(state.attrs[f].history.has_changes()
                   and _stored((state.attrs[f].history.deleted or [None])[0]) != _stored((state.attrs[f].history.added or [None])[0])
                   for f in fields)

    for obj in list(db.dirty):
        fields = CAMPAIGN_SEES.get(type(obj).__name__)
        if fields and changed(obj, fields):
            announce(db, obj.id, "game")
    for obj in list(db.new) + list(db.dirty):
        fields = TABLE_SEES.get(type(obj).__name__)
        if not fields or not changed(obj, fields):
            continue
        with db.no_autoflush:  # (a new copy knows its character before its character_id is filled in)
            character = obj if isinstance(obj, Character) else getattr(obj, "character", None) or (
                db.get(Character, obj.character_id) if obj.character_id else None)
        if character is not None and character.id is not None:
            announce(db, character.campaign_id, "character", id=character.id)


@event.listens_for(Session, "after_commit")
def _after_commit(db: Session) -> None:
    sent = set()
    for campaign_id, kind, data in db.info.pop("announce", []):
        key = (campaign_id, kind, json.dumps(data, sort_keys=True))
        if key not in sent:  # one message per change, however many rows it took
            sent.add(key)
            publish(campaign_id, kind, **data)


@event.listens_for(Session, "after_soft_rollback")
def _after_rollback(db: Session, previous_transaction) -> None:
    db.info.pop("announce", None)


# ------------------------------------------------------------------ the listener (one per copy, started with the app)
async def listen(url: str | None = None) -> None:
    """LISTEN on CHANNEL and deliver what arrives to this copy's pages; reconnect with growing waits if the
    connection drops, and check it's alive whenever it's been quiet (a dead connection can look idle)."""
    import psycopg

    url = url or config.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://", 1)
    wait = 1
    while True:
        try:
            async with await psycopg.AsyncConnection.connect(url, autocommit=True) as conn:
                await conn.execute(f"LISTEN {CHANNEL}")
                _bus["up"], wait = True, 1
                while True:
                    async for note in conn.notifies(timeout=30):
                        try:
                            got = json.loads(note.payload)
                            deliver(int(got["c"]), got["m"])
                        except (ValueError, KeyError, TypeError):
                            log.warning("Ignored a malformed live update: %r", note.payload[:200])
                    await conn.execute("SELECT 1")  # quiet for 30 s: make sure the connection is still there
        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("The live update listener lost Postgres; reconnecting in %s s", wait, exc_info=True)
        finally:
            _bus["up"] = False
        await asyncio.sleep(wait)
        wait = min(wait * 2, 30)


# ------------------------------------------------------------------ a page's connection
def _allowed(email: str, campaign_id: int) -> bool:
    return any(x["id"] == campaign_id for x in access.campaigns_for(email))


def _same_site(ws: WebSocket) -> bool:
    """Only askdnd's own pages connect (browsers send the page's Origin; another site's page can't pose as ours)."""
    origin = ws.headers.get("origin")
    return not origin or urlparse(origin).netloc == ws.headers.get("host", "")


@router.websocket("/live/connect")
async def connect(ws: WebSocket, c: int = 0):
    """A page's connection to its campaign's table. The page sends a keep-alive now and then (proxies close quiet
    connections); nothing else comes in."""
    user = current_user(ws)
    email = (user or {}).get("email", "")
    ok = bool(user) and _same_site(ws) and await asyncio.to_thread(_allowed, email, c)
    page = _Page()
    if ok:  # listed before the page hears it's connected, so nothing announced after that can miss it
        with _lock:
            _pages.setdefault(c, set()).add(page)
    await ws.accept()  # refused too: closed before accepting, browsers only see 1006 and retry
    if not ok:
        await ws.close(code=REFUSED)
        return

    async def send():
        while True:
            await page.wake.wait()
            for msg in page.take():
                await ws.send_text(msg)

    sender = asyncio.create_task(send())
    checked = time.monotonic()
    try:
        while True:
            try:
                await asyncio.wait_for(ws.receive_text(), timeout=RECHECK_SECONDS)
            except TimeoutError:
                pass
            if time.monotonic() - checked >= RECHECK_SECONDS:
                if not await asyncio.to_thread(_allowed, email, c):
                    await ws.close(code=REFUSED)
                    return
                checked = time.monotonic()
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with _lock:
            _pages.get(c, set()).discard(page)
