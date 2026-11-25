"""When nobody's listening (Roadmap item 42, Brett's pick 1A on docs/mockups/talking-both-ways/, Nov 24): with no Claude
session open, what he does in askdnd waits, safe but silent; the bar says so only if he's looking at it. So askdnd emails
the admins once when something a person did has waited for Claude 30 minutes with nobody listening, and says nothing
more until a session has listened again.

Counts and a link only, as the Inbox digest (app/digest.py): never anyone's words, since an email can be forwarded or
kept by the mail service. Sent by Resend from askdnd's own address, where the key is set and never on staging; one copy
of the app at a time (a Postgres advisory lock)."""

import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import config
from app import mail as mail_out
from app.fft import rules, views
from app.fft.host import ToolSetting
from app.fft.models import FftEvent, FftListener

log = logging.getLogger(__name__)
WAIT = timedelta(minutes=30)  # (his pick: "Email me once after 30 minutes")
TICK = 300  # seconds between looks
KEY = "fft_nobody_mail"  # (a ToolSetting: {"sent_at"}, when the last email went)
LOCK = 72_042_042
SITE = "https://askdnd.ai"


def enabled() -> bool:
    return bool(config.RESEND_API_KEY) and not config.STAGING


def waiting(db: Session) -> list[FftEvent]:
    """What people did in askdnd that the main listener hasn't read yet, as Claude's inbox would show it."""
    read = db.scalar(select(func.max(FftListener.read_id)).where(FftListener.area_id.is_(None))) or 0
    rows = db.scalars(select(FftEvent).where(FftEvent.id > read, FftEvent.actor.like("user:%"), FftEvent.thing.not_in(rules.QUIET_THINGS))
                      .order_by(FftEvent.id).limit(500))
    return [e for e in rows if rules.heard(e, "claude")]


def _state(db: Session) -> dict:
    row = db.get(ToolSetting, KEY)
    try:
        return json.loads(row.value) if row is not None and row.value else {}
    except ValueError:
        return {}


def _save(db: Session, state: dict) -> None:
    row = db.get(ToolSetting, KEY) or ToolSetting(key=KEY)
    row.value = json.dumps(state)
    db.add(row)


def check(db: Session, now: datetime | None = None) -> str:
    """One look: "listening" (a session is), "nothing" (nothing has waited 30 minutes), "told" (already emailed since a
    session last listened) or "sent"."""
    now = now or rules.now()
    if views.listening(db):
        return "listening"
    late = [e for e in waiting(db) if e.at is not None and e.at <= now - WAIT]
    if not late:
        return "nothing"
    sent = _state(db).get("sent_at")
    heard = db.scalar(select(func.max(FftListener.heard_at)))
    if sent and (heard is None or heard <= datetime.fromisoformat(sent)):
        return "told"
    n = len(waiting(db))
    mail = {"subject": f"askdnd: {n} thing{'s' if n != 1 else ''} wait{'s' if n == 1 else ''} for Claude",
            "text": (f"{n} thing{'s' if n != 1 else ''} you did in askdnd {'wait' if n != 1 else 'waits'} for Claude, the oldest for "
                     f"{int((now - late[0].at).total_seconds() // 60)} minutes, and no Claude session is listening.\n\n"
                     "Open the Code tab and say \"check askdnd\". Nothing is lost meanwhile.\n\n"
                     f"Development: {SITE}/manage/work\n\nYou get this once; the next only after Claude has listened again.")}
    mail["html"] = "<p>" + mail["text"].replace("\n\n", "</p><p>").replace(f"{SITE}/manage/work", f'<a href="{SITE}/manage/work">{SITE}/manage/work</a>') + "</p>"
    for to in sorted(config.ADMIN_EMAILS):
        try:
            SEND(to, mail)
        except Exception:
            log.warning("The nobody's-listening email didn't go", exc_info=True)
    _save(db, {"sent_at": now.isoformat()})
    rules._event(db, "askdnd", "nobody_mail", "tool", 0, waiting=n)
    return "sent"


SEND = mail_out.send  # (tests replace it; app/mail.py, the one way to send)


def run_once() -> str:
    from app import single

    def look(db: Session) -> str:
        said = check(db)
        db.commit()
        return said

    return single.alone(LOCK, look, "elsewhere")


async def loop() -> None:
    """Started with the app (app/main.py) where email is set up: a look every TICK seconds, never stopping on an error."""
    from app import single

    await single.every(TICK, run_once, "The nobody's-listening look")
