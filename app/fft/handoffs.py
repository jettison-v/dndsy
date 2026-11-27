"""Handoffs: Development's tab of what passes between Brett, Workshop and Claude (Roadmap item 45; Brett's picks CQ1–CQ5,
all A, on docs/mockups/collaboration-queue/, Nov 25: "I was more looking for the queue to show item regarding our
collaboration").

A handoff is one thing passed along and the steps it needs, each with a time and whose turn is next: a note reaching
Claude and Claude's answer, a question Claude asked and Brett's answer read, a comment or pick made on claude.ai brought
in and read, a check waiting for its deploy then reaching For you and tried, a pull request merged then live, a line
of chat filed. Every row is read from what Workshop already keeps (its rows and its append-only events), so the record
is kept as long as they are (CQ5). A step past its usual time is missed: shown first, in the needs-you line and the
status bar's count (CQ4), with a button that does it, Wake Claude or Bring in now, recorded with who pressed it (CQ3).

Workshop's own work only: askdnd's game sync with D&D Beyond is its Sync page (Roadmap item 44), never mixed in."""

from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fft import host, rules
from app.fft.models import (
    FftChat,
    FftCheck,
    FftCheckWait,
    FftDocComment,
    FftEvent,
    FftLine,
    FftListener,
    FftNote,
    FftPull,
    FftQuestion,
    FftTry,
)

SHOWN = timedelta(days=14)  # (the list's reach: older handoffs are still kept, in the rows they're read from)
DONE_TODAY = timedelta(hours=24)  # (done in the last day: under the fold; older done ones only through search)
LOOKED = rules.CLAUDE_AI_LOOKED  # (a ToolSetting: when Claude last looked at claude.ai, from its sync in and out)
# How long a step usually takes, past which it's missed (the mockup's "Missed")
LATE = {"claude": timedelta(minutes=30), "claude.ai": timedelta(minutes=15), "askdnd": timedelta(minutes=10), "live": timedelta(minutes=30)}
AREAS = [("all", "All"), ("feedback", "Feedback"), ("testing", "Testing"), ("roadmap", "Roadmap"), ("code", "Code")]
ORDER = {"missed": 0, "you": 1, "claude": 2, "askdnd": 3, "done": 4}


def looked(db: Session) -> None:
    rules.claude_ai_looked(db)  # (the change itself is rules.py's, as every one in Workshop)


def _setting_at(db: Session, key: str) -> datetime | None:
    row = db.get(host.ToolSetting, key)
    try:
        return datetime.fromisoformat(row.value) if row and row.value else None
    except ValueError:
        return None


def _read_up_to(db: Session) -> int:
    """How far Claude has read Workshop's events (any listener's mark): an event at or below it has been read."""
    return db.scalar(select(func.max(FftListener.read_id))) or 0


def _took(start: datetime | None, end: datetime | None) -> str:
    if not start or not end:
        return ""
    m = max(0, int((end - start).total_seconds() // 60))
    d = m // 1440
    return "under a minute" if m < 1 else f"{m} min" if m < 60 else f"{m // 60} h {m % 60} min" if m < 1440 else f"{d} day{'s' if d != 1 else ''}"


def _row(key, area, start, title, steps, whose, now, late_after=None, link="", wake="", end=None):
    """One handoff. `steps`: [(label, done)]; `whose` the next turn ("" once done); `late_after` when it's missed (rows
    decides: a step of Claude's only while a session listens, as Development's waiting too long)."""
    return {"key": key, "area": area, "at": start, "title": title, "steps": steps, "whose": whose, "state": whose or "done",
            "took": _took(start, end or now), "end": end, "link": link, "wake": wake, "late": late_after}


def rows(db: Session, now: datetime | None = None) -> list[dict]:
    """Every handoff of the last two weeks: missed first, then yours, Claude's, askdnd's, then done (CQ2)."""
    from app.fft import views

    now = now or rules.now()
    since = now - SHOWN
    read = _read_up_to(db)
    listening = views.listening(db)
    out = _notes(db, now, since) + _questions(db, now, since, read) + _comments(db, now, since, read) + _checks(db, now, since) \
        + _pulls(db, now, since) + _chats(db, now, since)
    # (claude.ai can't wake Claude: Claude looks. Its clock counts from the last look or from when listening began
    # again, whichever is later: issue 178, a night without listening made it Missed the moment listening began)
    clock = max((t for t in (_setting_at(db, LOOKED), _setting_at(db, rules.LISTENING_SINCE)) if t), default=None)
    if listening and (clock is None or now - clock > LATE["claude.ai"]):
        out.append(_row("look", "roadmap", clock or now, "Claude's look at claude.ai for your comments and picks",
                        [("every 10 minutes while listening", False)], "claude", now, clock + LATE["claude.ai"] if clock else now - timedelta(seconds=1),
                        wake="look"))
    for r in out:
        if r["whose"] and r["late"] and now > r["late"] and (r["whose"] != "claude" or listening):
            r["state"] = "missed"
        if r["state"] != "missed" or r["whose"] != "claude":  # (a button only where Claude can do the step: the review of #527)
            r["wake"] = ""
        r["views"] = " ".join(["all", r["area"]] + (["open"] if r["state"] != "done" else []))
        r["later"] = r["state"] == "done"
    return sorted(out, key=lambda r: (ORDER[r["state"]], -(r["at"].timestamp() if r["at"] else 0)))


def missed(db: Session) -> list[dict]:
    return [r for r in rows(db) if r["state"] == "missed"]


def _first_events(db, thing: str, ids: list[int], kinds: tuple[str, ...]) -> dict[int, datetime]:
    """Each thing's first event of these kinds, in one query (the review of #527: a query a row slowed For you)."""
    if not ids:
        return {}
    return dict(db.execute(select(FftEvent.thing_id, func.min(FftEvent.at)).where(FftEvent.thing == thing, FftEvent.thing_id.in_(ids),
                                                                                   FftEvent.kind.in_(kinds)).group_by(FftEvent.thing_id)).all())


def _notes(db, now, since) -> list[dict]:
    """A note: sent → (an admin's OK, for a player's) → Claude's answer: a line from Claude on the note or its issue, or
    its filing as an idea or an answer (Claude answers those on the Roadmap item or in the answer itself)."""
    notes = list(db.scalars(select(FftNote).where(FftNote.created_at > since)))
    filed_at = _first_events(db, "note", [n.id for n in notes], ("note_filed", "note_joined", "note_declined"))
    lines = db.execute(select(FftLine.note_id, FftLine.issue_id, FftLine.created_at).where(
        FftLine.who == "claude", FftLine.created_at > since,
        (FftLine.note_id.in_([n.id for n in notes] or [0])) | (FftLine.issue_id.in_([n.issue_id for n in notes if n.issue_id] or [0])))).all()
    out = []
    for n in notes:
        mine = n.role == "admin"
        filed = filed_at.get(n.id)
        answered = min((at for nid, iid, at in lines if at >= n.created_at and (nid == n.id or (n.issue_id and iid == n.issue_id))), default=None) \
            if n.state == "filed" else None
        if n.state == "declined" or n.filed_as in ("answered", "idea"):
            answered = answered or filed or n.created_at
        steps = [("sent", True)] + ([] if mine else [("an admin's OK", bool(filed) or n.state == "declined")]) + [("Claude's answer", bool(answered))]
        whose = "" if answered else ("you" if n.state == "waiting" and not mine else "claude" if n.state == "filed" else "")
        start = filed if (filed and not mine) else n.created_at
        who = "Your note" if mine else f"A note from {n.first_name or 'someone'}"
        out.append(_row(f"n{n.id}", "feedback", n.created_at, f"{who}: “{(n.text or '')[:80]}”", steps, whose, now,
                        start + LATE["claude"] if whose == "claude" else None, link=f"/manage/feedback?open=N{n.id}",
                        wake="claude", end=answered))
    return out


def _questions(db, now, since, read) -> list[dict]:
    """A question: Claude asks → you answer → Claude reads it."""
    qs = list(db.scalars(select(FftQuestion).where(FftQuestion.created_at > since)))
    ids = [q.id for q in qs] or [0]
    answers = dict(db.execute(select(FftEvent.thing_id, func.max(FftEvent.id)).where(FftEvent.thing == "question", FftEvent.thing_id.in_(ids),
                                                                                     FftEvent.kind.in_(("question_answered", "picks_changed"))).group_by(FftEvent.thing_id)).all())
    gone = _first_events(db, "question", ids, ("question_withdrawn",))
    out = []
    for q in qs:
        ev = answers.get(q.id) if q.answered_at else None
        seen = bool(ev and ev <= read)
        done = gone.get(q.id) or (q.answered_at if seen else None)
        whose = "" if done else "you" if not q.answered_at else "claude"
        out.append(_row(f"q{q.id}", "roadmap" if q.about in ("document", "area") else "feedback", q.created_at,
                        f"Q{q.id}: {q.text[:90]}", [("asked", True), ("your answer", bool(q.answered_at)), ("read by Claude", seen)], whose, now,
                        q.answered_at + LATE["claude"] if whose == "claude" else None, link="/manage/for-you", wake="claude", end=done))
    return out


def _comments(db, now, since, read) -> list[dict]:
    """A comment made on claude.ai: made → brought in → read by Claude."""
    out = []
    ins = list(db.execute(select(FftEvent.id, FftEvent.at).where(FftEvent.kind == "doc_comments_in", FftEvent.at > since)).all())
    for c in db.scalars(select(FftDocComment).where(FftDocComment.origin == "claude.ai", FftDocComment.created_at > since)):
        ev = next((i for i, at in sorted(ins, key=lambda x: x[1]) if at >= c.created_at - timedelta(seconds=5)), None)
        seen = bool(ev and ev <= read)
        whose = "" if seen else "claude"
        out.append(_row(f"d{c.id}", "roadmap", c.made_at or c.created_at, f"Your comment on {c.doc.split('/')[-2] if '/' in c.doc else c.doc}: “{c.words[:70]}”",
                        [("made on claude.ai", True), ("brought in", True), ("read by Claude", seen)], whose, now,
                        c.created_at + LATE["claude"] if whose else None, link="/manage/documents", wake="claude",
                        end=c.created_at if seen else None))
    return out


def _checks(db, now, since) -> list[dict]:
    """A check: waits for its deploy → live → reaches For you → tried there (a try before then, a local one, doesn't
    count: the review of #527)."""
    waits = list(db.scalars(select(FftCheckWait).where(FftCheckWait.created_at > since)))
    ids = list({w.check_id for w in waits}) or [0]
    checks = {c.id: c for c in db.scalars(select(FftCheck).where(FftCheck.id.in_(ids)))}
    pulls = {f"/pull/{p.number}": p for p in db.scalars(select(FftPull).where(FftPull.created_at > since - SHOWN))}
    reached_at = _first_events(db, "check", ids, ("check_deployed",))
    retired_at = _first_events(db, "check", ids, ("check_retired",))
    tries = db.execute(select(FftTry.check_id, FftTry.created_at).where(FftTry.check_id.in_(ids), FftTry.actor == "person")).all()
    out = []
    for w in waits:
        c = checks.get(w.check_id)
        if c is None:
            continue
        p = next((v for k, v in pulls.items() if w.pr.rstrip("/").endswith(k)), None)
        live = p.live_at if p else None
        reached = reached_at.get(c.id)
        tried = min((at for cid, at in tries if cid == c.id and at >= reached), default=None) if reached else None
        retired = retired_at.get(c.id) if c.retired else None
        whose = "" if (tried or retired) else "you" if reached else "askdnd"
        late = live + LATE["askdnd"] if whose == "askdnd" and live else None
        out.append(_row(f"c{c.id}-{w.id}", "testing", w.created_at, f"C{c.id}: {c.title[:80]}",
                        [("waits for its deploy", True), ("live", bool(live)), ("on your For you", bool(reached)), ("tried", bool(tried))],
                        whose, now, late, link=f"/manage/work?tab=checks&open=C{c.id}", end=tried or retired))
    return out


def _pulls(db, now, since) -> list[dict]:
    """A pull request: opened → merged → live."""
    out = []
    for p in db.scalars(select(FftPull).where(FftPull.created_at > since, FftPull.by_bot.is_(False))):
        merged = p.closed_at if p.state == "merged" else None
        end = p.live_at or (p.closed_at if p.state == "closed" else None)
        whose = "" if end else "askdnd" if merged else "claude"
        out.append(_row(f"p{p.number}", "code", p.created_at, f"#{p.number} {p.title[:80]}",
                        [("opened", True), ("tests", p.tests == "passed" or bool(merged)), ("merged", bool(merged)), ("live", bool(p.live_at))],
                        whose, now, merged + LATE["live"] if whose == "askdnd" and merged else None, link="/manage/work", end=end))
    return out


def _chats(db, now, since) -> list[dict]:
    """A line of chat: said → filed onto its item or issue."""
    out = []
    for c in db.scalars(select(FftChat).where(FftChat.said_at > since)):
        whose = "" if c.filed_at else "claude"
        out.append(_row(f"t{c.id}", "roadmap", c.said_at, f"Your line in chat: “{c.words[:80]}”", [("said", True), ("filed", bool(c.filed_at))],
                        whose, now, c.said_at + LATE["claude"] if whose else None, wake="claude", end=c.filed_at))
    return out


def wake(db: Session, actor: str, what: str, key: str = "") -> None:
    rules.wake_claude(db, actor, what, key)
