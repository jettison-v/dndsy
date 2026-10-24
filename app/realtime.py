"""The live table connection (VTT 0.3, docs/plans/2026-10-22-vtt-roadmap.md): every open page keeps a WebSocket to
askdnd, and when something changes at its campaign's table, askdnd tells every page there within a second.

A message says only *what* changed, never the change itself: {"type": "rolls"} (a table roll, its damage, reroll or
added die) or {"type": "character", "id": 7} (a character's D&D Beyond copy changed). The page then asks for it at the
usual addresses, which decide who may see what, so a DM-only roll's number never travels on the connection. Pages
still poll now and then (app.js "live connection"), so a dropped connection costs speed, never a roll.

Changes are announced after their database commit (`announce()` waits for it; a rollback drops them), so a page never
asks before the change is there. One process holds the connections (the app runs one uvicorn worker). During a
deploy the old and new copies overlap for a moment; pages reconnect to the new one and catch up as they do.
"""

import asyncio
import json
import threading

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import access
from app.auth import current_user

router = APIRouter()

_lock = threading.Lock()
# campaign id → the pages connected to it: (their event loop, their outbox)
_pages: dict[int, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}


def publish(campaign_id: int | None, kind: str, **data) -> None:
    """Tell every page open in this campaign that `kind` changed. Safe from any thread."""
    if campaign_id is None:
        return
    msg = json.dumps({"type": kind, **data})
    with _lock:
        pages = list(_pages.get(campaign_id, ()))
    for loop, outbox in pages:
        try:
            loop.call_soon_threadsafe(outbox.put_nowait, msg)
        except RuntimeError:
            pass  # that page's connection has just closed


def announce(db: Session, campaign_id: int | None, kind: str, **data) -> None:
    """publish() once `db` commits (nothing if it rolls back)."""
    db.info.setdefault("announce", []).append((campaign_id, kind, data))


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


def connected(campaign_id: int) -> int:
    with _lock:
        return len(_pages.get(campaign_id, ()))


@router.websocket("/live/connect")
async def connect(ws: WebSocket, c: int = 0):
    """A page's connection to its campaign's table: signed in, and the campaign one of theirs. The page sends a
    keep-alive now and then (proxies close quiet connections); nothing else comes in."""
    user = current_user(ws)
    await ws.accept()  # then refuse with our own code: closed before accepting, browsers only see 1006 and retry
    if not user or not any(x["id"] == c for x in access.campaigns_for(user.get("email"))):
        await ws.close(code=4403)  # the page stops reconnecting (app.js "live connection")
        return
    me = (asyncio.get_running_loop(), asyncio.Queue())
    with _lock:
        _pages.setdefault(c, set()).add(me)

    async def send():
        while True:
            await ws.send_text(await me[1].get())

    sender = asyncio.create_task(send())
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        sender.cancel()
        with _lock:
            _pages.get(c, set()).discard(me)
