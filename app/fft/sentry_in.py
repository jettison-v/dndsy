"""Errors at the table, filed (Roadmap item 42, Brett's pick 4A on docs/mockups/talking-both-ways/, Nov 24): Sentry
records every error, but it reached Claude only when Claude looked. Once a day askdnd asks Sentry for new unresolved
errors and files each as an issue in Behind the scenes › Errors, so it's on the Board and Claude's to take up.

Reads Sentry with a read-only key (SENTRY_READ_TOKEN, a Railway variable; SENTRY_ORG and SENTRY_PROJECT say which
project); off without it and never on staging. Each Sentry issue is filed once (its id kept), with a line saying how
often it happened and its link; its run is a scheduled job (app/data/jobs.json "sentry") on Development › Scheduled."""

import json
import logging
import os
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app import config
from app.fft import rules
from app.models import ToolSetting

log = logging.getLogger(__name__)
KEY = "fft_sentry_in"  # (a ToolSetting: {"ran_at", "seen": [Sentry issue ids already filed]})
EVERY = timedelta(hours=20)  # (about once a day)
TICK = 3600
LOCK = 72_042_043
API = "https://sentry.io/api/0"
SEEN_KEEP = 500


def _token() -> str:
    return os.getenv("SENTRY_READ_TOKEN", "").strip()


def enabled() -> bool:
    return bool(_token() and os.getenv("SENTRY_ORG") and os.getenv("SENTRY_PROJECT")) and not config.STAGING


def _fetch() -> list[dict]:
    q = urllib.parse.urlencode({"query": "is:unresolved firstSeen:-2d", "statsPeriod": "24h", "limit": 25})
    url = f"{API}/projects/{os.getenv('SENTRY_ORG')}/{os.getenv('SENTRY_PROJECT')}/issues/?{q}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_token()}", "User-Agent": "askdnd"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


FETCH = _fetch  # (tests replace it)


def _state(db: Session) -> dict:
    row = db.get(ToolSetting, KEY)
    try:
        return json.loads(row.value) if row is not None and row.value else {}
    except ValueError:
        return {}


def run(db: Session, now: datetime | None = None, force: bool = False) -> list[int]:
    """One look, if a day has passed since the last: each new Sentry error filed as an issue. Returns the issues made."""
    from app.fft import work_page

    now = now or rules.now()
    state = _state(db)
    if not force and state.get("ran_at") and now - datetime.fromisoformat(state["ran_at"]) < EVERY:
        return []
    try:
        found = FETCH()
    except Exception as e:
        work_page.report_job(db, "askdnd", "sentry", "failed", f"Sentry didn't answer: {type(e).__name__}")
        state["ran_at"] = now.isoformat()
        _save(db, state)
        return []
    seen = list(state.get("seen") or [])
    made = []
    for s in found if isinstance(found, list) else []:
        sid = str(s.get("id") or "")
        if not sid or sid in seen:
            continue
        title = " ".join(str(s.get("title") or "An error").split())
        i = rules.new_issue(db, "askdnd", f"Error: {title}"[:120], feature="errors", kind="fix")
        rules.add_line(db, "askdnd", f"From Sentry: {s.get('count', '?')} times, {s.get('userCount', 0)} people, first {str(s.get('firstSeen', ''))[:16]} UTC"
                       f"{' · ' + str(s.get('culprit')) if s.get('culprit') else ''} · {s.get('permalink', '')}", issue=i, to="claude")
        seen.append(sid)
        made.append(i.id)
    state.update({"ran_at": now.isoformat(), "seen": seen[-SEEN_KEEP:]})
    _save(db, state)
    work_page.report_job(db, "askdnd", "sentry", "ok", f"{len(made)} new error{'s' if len(made) != 1 else ''} filed" if made else "No new errors")
    return made


def _save(db: Session, state: dict) -> None:
    row = db.get(ToolSetting, KEY) or ToolSetting(key=KEY)
    row.value = json.dumps(state)
    db.add(row)


def run_once() -> list[int]:
    from app import single

    def look(db: Session) -> list[int]:
        made = run(db)
        db.commit()
        return made

    return single.alone(LOCK, look, [])


async def loop() -> None:
    """Started with the app (app/main.py) where the key is set: a look every TICK seconds, filing once a day."""
    from app import single

    await single.every(TICK, run_once, "The Sentry look")
