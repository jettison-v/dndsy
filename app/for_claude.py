"""What's waiting for Claude: askdnd's half of the loop between askdnd and the Claude app (Working with Claude, Brett's
picks Nov 17, docs/mockups/working-together/ Board 7).

Whatever Brett (or a player) does in askdnd that Claude should know of is written here as it happens (`tell`): a note
sent or added to, a check passed, failed or skipped, a player's answer to Does it work now?, the areas' order. Claude
reads it with the feedback key:

- `feedback.py inbox` reads what's after Claude's last read (`/api/claude/inbox`) and marks it read
  (`/api/claude/inbox/read`); the mark is kept here, so any session, a fresh one included, starts where the last stopped.
- `feedback.py wait` asks every minute and returns once something's there. Claude runs it in the background, so a
  turn starts by itself when Brett does something in askdnd: nothing he does there needs telling in chat.

Each ask also says Claude is listening (`heard`): Testing's Where it stands shows it, so Brett can see whether a
session is waiting on askdnd or none is open (then he says "check askdnd" in the Claude app).
"""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config, web
from app.db import get_db
from app.models import InboxItem, ToolSetting

router = APIRouter()

# What happened (InboxItem.what)
WHATS = {
    "note": "A note was sent", "added": "A note was added to", "check": "A check was marked", "works": "A player answered Does it work now?",
    "answer": "An answer to Claude's question", "order": "The areas' order changed", "closed": "A note was closed or deleted",
}
READ, HEARD = "claude_read", "claude_heard"  # (ToolSetting keys: the last item Claude read, when it last asked)
LISTENING = timedelta(minutes=3)  # (`wait` asks every minute: longer than this and no session is waiting)
PAGE = 200


def tell(db: Session, what: str, text: str, feedback_id: int | None = None, check_id: int | None = None, area_id: int | None = None) -> None:
    """Put something in Claude's inbox (committed with the change it's about, by the caller)."""
    if what not in WHATS:
        raise ValueError(what)
    db.add(InboxItem(what=what, text=text[:400], feedback_id=feedback_id, check_id=check_id, area_id=area_id))


def _setting(db: Session, key: str) -> ToolSetting:
    """The setting's row, made if it isn't there (two asks at once on a fresh database never collide)."""
    from sqlalchemy.dialects.postgresql import insert

    db.execute(insert(ToolSetting).values(key=key, value="").on_conflict_do_nothing(index_elements=["key"]))
    return db.get(ToolSetting, key)


def read_upto(db: Session) -> int:
    row = db.get(ToolSetting, READ)
    return int(row.value) if row is not None and row.value.isdigit() else 0


def listening(db: Session) -> dict:
    """Whether a Claude session is waiting on askdnd now (it asked within LISTENING), and when it last asked."""
    row = db.get(ToolSetting, HEARD)
    try:
        heard = datetime.fromisoformat(row.value) if row is not None and row.value else None
    except ValueError:
        heard = None
    return {"heard": heard, "on": heard is not None and datetime.now(UTC) - heard < LISTENING,
            "unread": db.scalar(select(func.count()).select_from(InboxItem).where(InboxItem.id > read_upto(db))) or 0}


def _claude(key: str | None) -> None:
    if not config.FEEDBACK_KEY or not key or not secrets.compare_digest(key, config.FEEDBACK_KEY):
        raise HTTPException(404)


def item(i: InboxItem) -> dict:
    return {"id": i.id, "at": i.at.isoformat(timespec="seconds") if i.at else "", "what": i.what, "text": i.text,
            "feedback_id": i.feedback_id, "check_id": i.check_id, "area_id": i.area_id}


@router.get("/api/claude/inbox")
def inbox(after: int | None = None, listening: bool = False, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """What's waiting for Claude: everything after its last read (or after `after`), oldest first. `feedback.py wait`
    asks with `listening`: that's how askdnd knows a session is waiting on it (`heard`); a one-off read isn't."""
    _claude(x_feedback_key)
    upto = read_upto(db) if after is None else max(0, after)
    rows = db.scalars(select(InboxItem).where(InboxItem.id > upto).order_by(InboxItem.id).limit(PAGE)).all()
    if listening:
        _setting(db, HEARD).value = datetime.now(UTC).isoformat(timespec="seconds")
        db.commit()
    return JSONResponse({"read": read_upto(db), "items": [item(i) for i in rows], "more": len(rows) == PAGE},
                        headers={"Cache-Control": "no-store"})


@router.post("/api/claude/inbox/read")
def mark_read(body=web.JsonBody, x_feedback_key: str | None = Header(default=None), db: Session = Depends(get_db)):
    """Claude has read up to `upto` (never back: a second session reading older items leaves the mark where it is)."""
    _claude(x_feedback_key)
    upto = (body or {}).get("upto") if isinstance(body, dict) else None
    if type(upto) is not int or upto < 0:
        raise HTTPException(400, "upto: the last item read")
    prev = read_upto(db)
    row = _setting(db, READ)
    row.value = str(max(upto, prev))
    db.commit()
    return JSONResponse({"read": int(row.value)})
