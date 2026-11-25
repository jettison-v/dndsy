"""Backstage › Tuning › Sync (Roadmap item 44; Brett, Nov 25: "visibility into the askdnd sync would be helpful.
Something like a processing queue. This queue could help with investigating any issues that arise or anything that is
missed."; his picks SQ1–SQ6, all A, on docs/mockups/sync-queue/).

Every piece of work between askdnd and D&D Beyond in one list, newest first: each read of a sheet (a job on the
queue, app/sheet_reads.py), each change sent to a sheet (a bridge intent, app/ddb_bridge.py), and Claude's recap
drafts (jobs too, app/drafts.py), each waiting, running, done, not yet or failed, and each opening to its story: when
and why it was asked, each try, the exact error. Retry and Cancel, each kept with who pressed it. What needs someone
(a failure, or a change waiting over 10 minutes) is said once at the top, and on Overview. Done work stays a day,
failed work 30 days (jobs' own sweep; a change's record isn't deleted, only no longer listed).

The game's sync only: what passes between Brett, askdnd and Claude is Roadmap item 45's, in Found, Fixed, Tried."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app import drafts, jobs, sheet_reads, web
from app.auth import is_admin
from app.db import get_db
from app.models import BridgeBatch, BridgeIntent, Campaign, CampaignCharacter, Character
from app.templating import templates

router = APIRouter()

DONE_FOR = timedelta(days=1)  # (Brett's pick SQ6: a day of done, 30 days of failed)
FAILED_FOR = timedelta(days=30)
LATE = timedelta(minutes=10)  # (a change waiting this long needs someone: SQ5)
LIMIT = 400  # (the newest; the rest are a day or a month old, and Search finds within these)
VIEWS = [("all", "All"), ("read", "Reads"), ("change", "Changes"), ("draft", "Drafts"), ("trouble", "Trouble", "Failed, not yet, or waiting too long")]
WHY = {sheet_reads.PRESS: "a press of Refresh", sheet_reads.PAGE: "a page opened", sheet_reads.PAGE + 1: "a page opened",
       sheet_reads.UNWATCHED: "nobody had it open", sheet_reads.UNWATCHED_TEST: "nobody had it open (a test campaign)"}
JOB_STATE = {"queued": "queued", "running": "running", "done": "done", "failed": "failed", "cancelled": "cancelled"}
CHANGE_STATE = {"waiting": "queued", "sending": "running", "live": "done", "not_yet": "not yet", "dismissed": "cancelled"}
TRIED = {"done": "Done", "again": "Didn't work: tries again", "failed": "Didn't work: gave up", "stopped": "Stopped by a deploy: back in line"}


def _now() -> datetime:
    return datetime.now(UTC)


def _took(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return ""
    s = max(0.0, (end - start).total_seconds())
    return f"{s:.1f} s" if s < 60 else f"{int(s // 60)} min {int(s % 60)} s" if s < 3600 else f"{s / 3600:.1f} h"


# A failed job whose work has since been done (a later job with its dedup_key finished done): listed, but nothing needs
# anyone (the review of #526: a 2 am failure the next read put right kept Overview red all day)
_PUT_RIGHT = ("EXISTS (SELECT 1 FROM jobs k WHERE k.dedup_key = j.dedup_key AND k.state = 'done' AND k.id <> j.id "
              "AND k.finished_at > j.finished_at)")
_JOBS = ("SELECT j.id, j.kind, j.state, j.label, j.requested_by, j.priority, j.attempts, j.created_at, j.started_at, j.finished_at, "
         "j.run_at, j.error, j.payload, c.name AS character, gs.number AS session, EXISTS (SELECT 1 FROM jobs k WHERE k.dedup_key = j.dedup_key "
         "AND k.state = 'done' AND k.id <> j.id AND k.finished_at > j.finished_at) AS put_right FROM jobs j "
         "LEFT JOIN characters c ON j.kind = :read AND c.id = CAST(j.payload->>'character_id' AS integer) "
         "LEFT JOIN game_sessions gs ON j.kind <> :read AND gs.id = CAST(j.payload->>'session_id' AS integer) WHERE j.kind = ANY(:kinds) AND ")  # (put_right: _PUT_RIGHT)


def _jobs(db: Session, now: datetime) -> list[dict]:
    """Everything still open and every failure in its 30 days, then the newest done work (the review of #526: one list cut
    at its newest few hundred lost a failure from earlier the same game night behind routine reads)."""
    kinds = [sheet_reads.KIND, *drafts.STEPS]
    args = {"read": sheet_reads.KIND, "kinds": kinds, "done": now - DONE_FOR, "failed": now - FAILED_FOR, "n": LIMIT}
    found = db.execute(text(_JOBS + "(j.state IN ('queued', 'running') OR (j.state IN ('failed', 'cancelled') AND j.finished_at > :failed)) "
                            "ORDER BY j.created_at DESC LIMIT 2000"), args).all()
    found += db.execute(text(_JOBS + "j.state = 'done' AND j.finished_at > :done ORDER BY j.created_at DESC LIMIT :n"), args).all()
    out = []
    for r in found:
        read = r.kind == sheet_reads.KIND
        waiting_again = r.state == "queued" and bool(r.error)  # (tried, didn't work, waiting out its backoff)
        out.append({
            "key": f"j{r.id}", "kind": "read" if read else "draft", "at": r.created_at,
            "who": (r.character or "A character") if read else _session(r.session),
            "what": "Read the sheet" if read else drafts_step(r.kind),
            "why": _why(read, r.priority, r.requested_by) + (" · since done" if r.state == "failed" and r.put_right else ""),
            "state": JOB_STATE.get(r.state, r.state), "tries": r.attempts, "took": _took(r.started_at, r.finished_at) if r.state in ("done", "failed") else "",
            "trouble": (r.state == "failed" and not r.put_right) or waiting_again, "dir": "←" if read else "✎"})
    return out


def _session(number: int | None) -> str:
    """A draft's session, as the table numbers it (the review of #526: never its row's id)."""
    return f"Session {number}" if number else "A session"


def _why(read: bool, priority: int, by: str) -> str:
    """Why it was asked, as the list says it: a person's press by their first name, else what asked it."""
    if not read:
        return f"asked by {by}" if by else ""
    if priority >= sheet_reads.PRESS:
        return f"asked by {by}" if by else WHY[sheet_reads.PRESS]
    return by or WHY.get(priority, "a page opened")  # (the look at unwatched sheets says its own reason in `by`)


def drafts_step(kind: str) -> str:
    return {"draft_notes": "Draft the session's notes", "read_transcript": "Read the transcript", "revise": "Revise the recap",
            "draft_recap": "Draft the recap"}.get(kind, kind.replace("_", " ").capitalize())


def _changes(db: Session, now: datetime) -> list[dict]:
    """Every change still open or not made, and every cancelled one, in their 30 days; then the newest made ones."""
    q = select(BridgeIntent, Character.name).join(Character, Character.id == BridgeIntent.character_id).order_by(BridgeIntent.created_at.desc())
    rows = db.execute(q.where(or_(BridgeIntent.state.in_(("waiting", "sending")),
                                  BridgeIntent.state.in_(("not_yet", "dismissed")) & (BridgeIntent.updated_at > now - FAILED_FOR))).limit(2000)).all()
    rows += db.execute(q.where(BridgeIntent.state == "live", BridgeIntent.updated_at > now - DONE_FOR).limit(LIMIT)).all()
    ids = [it.id for it, _ in rows]
    tries: dict[int, int] = {}  # (each change's tries: the attempts of every batch that carried it)
    if ids:
        wanted = set(ids)
        for b in db.scalars(select(BridgeBatch).where(BridgeBatch.character_id.in_({it.character_id for it, _ in rows}),
                                                      BridgeBatch.created_at > now - FAILED_FOR)):
            for i in set(b.intents or []) & wanted:
                tries[i] = tries.get(i, 0) + (b.attempts or 1)
    out = []
    for it, name in rows:
        late = it.state == "waiting" and now - it.created_at > LATE
        out.append({
            "key": f"c{it.id}", "kind": "change", "at": it.created_at, "who": name, "what": it.label,
            "why": "made through the DM" if (it.data or {}).get("by") == "dm" else "",
            "state": CHANGE_STATE.get(it.state, it.state), "tries": tries.get(it.id, 0),
            "took": _took(it.created_at, it.updated_at) if it.state == "live" else "",
            "trouble": it.state == "not_yet" or late, "late": late, "dir": "→"})
    return out


def rows(db: Session, now: datetime | None = None) -> list[dict]:
    """The list, newest first: reads, changes and drafts together (Brett's pick SQ2), each with its view keys."""
    now = now or _now()
    out = sorted(_jobs(db, now) + _changes(db, now), key=lambda r: r["at"], reverse=True)
    for r in out:
        r["views"] = " ".join(["all", r["kind"]] + (["trouble"] if r["trouble"] else []))
    return out


def needs(db: Session, now: datetime | None = None) -> dict | None:
    """What needs someone, said once (Brett's pick SQ5): failed work of the last day not since put right, changes not
    made yet, and changes waiting over 10 minutes; a test campaign's never (the review of #526: a live test's seat
    turned Overview red). {word, tone, says} or None. The same on Overview's Sync card."""
    now = now or _now()
    failed = db.scalar(text(f"SELECT count(*) FROM jobs j LEFT JOIN campaigns cp ON cp.id = j.campaign_id WHERE j.kind = ANY(:kinds) "  # noqa: S608 (a constant)
                            f"AND j.state = 'failed' AND j.finished_at > :since AND NOT {_PUT_RIGHT} AND NOT COALESCE(cp.is_test, false)"),
                       {"kinds": [sheet_reads.KIND, *drafts.STEPS], "since": now - DONE_FOR}) or 0
    played = (select(CampaignCharacter.character_id).join(Campaign, Campaign.id == CampaignCharacter.campaign_id)
              .where(CampaignCharacter.left_on.is_(None), Campaign.is_test.is_(True)))
    changes = select(func.count()).select_from(BridgeIntent).where(BridgeIntent.character_id.not_in(played))
    stuck = db.scalar(changes.where(BridgeIntent.state == "not_yet", BridgeIntent.updated_at > now - DONE_FOR)) or 0
    late = db.scalar(changes.where(BridgeIntent.state == "waiting", BridgeIntent.created_at < now - LATE)) or 0
    parts = ([f"{failed} failed in the last day"] if failed else []) + ([f"{stuck} change{'s' if stuck != 1 else ''} not made yet"] if stuck else []) \
        + ([f"{late} change{'s' if late != 1 else ''} waiting over 10 minutes"] if late else [])
    if not parts:
        return None
    return {"word": "Failed" if failed or stuck else "Waiting", "tone": "broken" if failed or stuck else "you",
            "says": "; ".join(parts) + ". Open one for what happened, then Retry it."}


def card_state(db: Session) -> tuple[str, str]:
    """Overview's Sync card: (words, ok | warn | bad)."""
    n = needs(db)
    if n:
        return n["says"].split(".")[0].capitalize(), "bad" if n["tone"] == "broken" else "warn"
    c = jobs.counts(db)
    return (f"{c.get('queued', 0) + c.get('running', 0)} under way" if c.get("queued") or c.get("running") else "Nothing waiting"), "ok"


def story(db: Session, key: str) -> dict | None:
    """One row's story: what it is, when and why it was asked, each try, the exact error, and what may be pressed."""
    kind, num = key[:1], key[1:]
    if not num.isdigit():
        return None
    if kind == "j":
        r = db.execute(text("SELECT j.*, c.name AS character, gs.number AS session FROM jobs j LEFT JOIN characters c ON j.kind = :read "
                            "AND c.id = CAST(j.payload->>'character_id' AS integer) LEFT JOIN game_sessions gs ON j.kind <> :read "
                            "AND gs.id = CAST(j.payload->>'session_id' AS integer) WHERE j.id = :id AND j.kind = ANY(:kinds)"),
                       {"id": int(num), "read": sheet_reads.KIND, "kinds": [sheet_reads.KIND, *drafts.STEPS]}).one_or_none()
        if r is None:
            return None
        read = r.kind == sheet_reads.KIND
        why = _why(read, r.priority, r.requested_by)
        steps = [{"at": r.created_at, "tone": "going", "words": "Asked" + (f": {why}" if why else "")}]
        for s in r.story or []:
            if s.get("did"):
                steps.append({"at": s.get("at"), "tone": "you", "words": f"{'Retried' if s['did'] == 'retry' else 'Cancelled'} by {s.get('by') or 'someone'}"})
            else:
                ended = s.get("ended", "")
                steps.append({"at": s.get("at"), "tone": "done" if ended == "done" else "broken" if ended in ("again", "failed") else "quiet",
                              "words": f"Try {s.get('n')}: {TRIED.get(ended, ended)}" + (f" after {s.get('took')} s" if s.get("took") else ""),
                              "error": s.get("error") or ""})
        if r.state == "running":
            steps.append({"at": r.started_at, "tone": "working", "words": f"Try {r.attempts}: running now"})
        elif r.state == "queued" and r.error:
            steps.append({"at": r.run_at, "tone": "you", "words": "Next try at this time"})
        return {"key": key, "title": f"{r.character or 'A character'} · Read the sheet" if read else f"{_session(r.session)} · {drafts_step(r.kind)}",
                "kind": "read" if read else "draft", "state": JOB_STATE.get(r.state, r.state), "error": r.error,
                "facts": [("Asked", r.created_at), ("Tries", f"{r.attempts} of {r.max_attempts}"), ("Took", _took(r.started_at, r.finished_at))],
                "steps": steps, "retry": r.state in ("failed", "cancelled") or (r.state == "queued" and bool(r.error)),
                "cancel": r.state == "queued",
                "link": f"/characters/{r.payload.get('character_id')}" if read and r.payload.get("character_id") else ""}
    if kind == "c":
        it = db.get(BridgeIntent, int(num))
        if it is None:
            return None
        ch = db.get(Character, it.character_id)
        steps = [{"at": it.created_at, "tone": "going", "words": "Asked" + (", made through the DM" if (it.data or {}).get("by") == "dm" else "")}]
        for b in db.scalars(select(BridgeBatch).where(BridgeBatch.character_id == it.character_id, BridgeBatch.created_at >= it.created_at - timedelta(seconds=5))
                            .order_by(BridgeBatch.id)):
            if it.id not in (b.intents or []):
                continue
            steps.append({"at": b.created_at, "tone": "done" if b.state == "done" else "broken" if b.state == "stopped" else "going",
                          "words": f"Sent to D&D Beyond{f', {b.attempts} tries' if (b.attempts or 1) > 1 else ''}: "
                                   + {"done": "made, and read back as asked", "stopped": "stopped", "replanned": "D&D Beyond changed meanwhile: worked out again",
                                      "sending": "on its way", "ready": "waiting to go again"}.get(b.state, b.state),
                          "error": b.error or ""})
        for s in (it.data or {}).get("sync") or []:
            steps.append({"at": s.get("at"), "tone": "you", "words": f"{'Retried' if s.get('did') == 'retry' else 'Cancelled'} by {s.get('by') or 'someone'}"})
        if it.state == "not_yet":
            steps.append({"at": it.updated_at, "tone": "you", "words": "Not made yet: the sheet shows Not yet, and the player decides on D&D Beyond", "error": it.error})
        return {"key": key, "title": f"{ch.name if ch else 'A character'} · {it.label}", "kind": "change",
                "state": CHANGE_STATE.get(it.state, it.state), "error": it.error,
                "facts": [("Asked", it.created_at), ("Last change", it.updated_at)],
                "steps": steps, "retry": it.state == "not_yet", "cancel": it.state in ("waiting", "not_yet"),
                "link": f"/characters/{it.character_id}"}
    return None


def _mark(it: BridgeIntent, did: str, by: str) -> None:
    it.data = {**(it.data or {}), "sync": [*(it.data or {}).get("sync", []), {"at": _now().isoformat(), "did": did, "by": by}]}


def act(db: Session, key: str, did: str, by: str) -> bool:
    """Retry or Cancel one row, kept in its story with who pressed it (Brett's pick SQ4)."""
    from app import ddb_bridge

    kind, num = key[:1], key[1:]
    if not num.isdigit() or did not in ("retry", "cancel"):
        return False
    if kind == "j":
        return jobs.retry(db, int(num), by) if did == "retry" else jobs.cancel(db, int(num), by)
    if kind == "c":
        it = db.get(BridgeIntent, int(num))
        if it is None or (did == "retry" and it.state != "not_yet") or (did == "cancel" and it.state not in ("waiting", "not_yet")):
            return False
        (ddb_bridge.retry if did == "retry" else ddb_bridge.dismiss)(db, it.id)
        _mark(it, did, by)
        ch = db.get(Character, it.character_id)
        if ch is not None and ch.campaign_id:  # (as the bridge's own Retry and Undo do: the extension told to make it now, open pages to show it)
            from app import realtime

            if did == "retry" and ch.ddb_id:
                realtime.announce(db, ch.campaign_id, "deliver", ddb=str(ch.ddb_id))
            realtime.announce(db, ch.campaign_id, "character", id=ch.id)
        return True
    return False


def _admin(request: Request):
    return web.require(request, is_admin, "The Sync page is for admins.")


@router.get("/manage/sync")
def sync_page(request: Request, db: Session = Depends(get_db)):
    """The list, its counts and what needs someone (Brett's picks SQ1–SQ6)."""
    _, stop = _admin(request)
    if stop:
        return stop
    now = _now()
    listed = rows(db, now)
    counts = {"waiting": sum(1 for r in listed if r["state"] == "queued"), "running": sum(1 for r in listed if r["state"] == "running"),
              "done": sum(1 for r in listed if r["state"] == "done"), "failed": sum(1 for r in listed if r["state"] in ("failed", "not yet"))}
    return templates.TemplateResponse(request, "manage_sync.html", {"rows": listed, "views": VIEWS, "counts": counts,
                                                                    "needs": needs(db, now), "start": "trouble" if any(r["trouble"] for r in listed) else "all"})


@router.get("/manage/sync/{key}")
def sync_story(request: Request, key: str, db: Session = Depends(get_db)):
    """One row's story, in the window over the list."""
    _, stop = _admin(request)
    if stop:
        return stop
    s = story(db, key)
    if s is None:
        return web.not_found(request, "That isn't on the Sync page any more.")
    return templates.TemplateResponse(request, "_sync_window.html", {"s": s})


@router.post("/manage/sync/{key}/{did}")
def sync_act(request: Request, key: str, did: str, db: Session = Depends(get_db)):
    """Retry or Cancel, then back to the list with a corner card saying what happened."""
    user, stop = _admin(request)
    if stop:
        return stop
    ok = act(db, key, did, sheet_reads.who(user) or "an admin")
    db.commit()
    request.session["toast"] = (web.notice("Trying it again now, first in line" if did == "retry" else "Cancelled: it won't run")
                                if ok else web.notice("That can't be done now: it may have just finished. The list shows where it stands.", "warn"))
    return RedirectResponse("/manage/sync", status_code=303)
