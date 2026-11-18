"""Every change to Found, Fixed, Tried goes through here (the v2 brief's rules R1–R18 and trust T1–T8,
docs/mockups/feedback-and-testing/index.html): each function checks its rule, changes the rows, and writes the event in
the same transaction (`_event`). Nothing else sets a state. Callers commit; a refused change raises `RuleError`.

Words: an actor is "user:<id>", "claude", "mini" (the Mac Mini's runs) or "askdnd" (askdnd by itself)."""

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.fft.models import (
    FftArea,
    FftCheck,
    FftCheckIssue,
    FftCheckVersion,
    FftEvent,
    FftIdea,
    FftIssue,
    FftItem,
    FftLine,
    FftListener,
    FftNote,
    FftQuestion,
    FftRound,
    FftTry,
    FftTryIssue,
)

KINDS = ("problem", "idea", "question")
ROLES = ("admin", "dm", "player", "member")
ISSUE_STATES = ("to_fix", "fixing", "asks", "merge_ok", "ready", "closed")
CLOSE_REASONS = ("works", "wont", "same", "cant_repro", "withdrawn")
DEVICES = ("laptop", "iphone", "ipad", "mac_mini")
WHERE = ("live", "staging", "local")
CANT = ("later", "blocked", "wrong")
# Whose turn each issue state is (the pill, brief §4): brett, claude, player (a player confirms), closed
ISSUE_TURN = {"to_fix": "claude", "fixing": "claude", "asks": "brett", "merge_ok": "brett", "ready": "brett", "closed": "closed"}
CONFIRM_DAYS = 3  # a player's fix is theirs to confirm, then Brett's (R5)
UNDO = timedelta(minutes=1)  # approving, and a pass's notices, wait this long (R5, Undo)
ROUND_IDLE = timedelta(hours=12)  # an open round ends itself (R11)
LOCK = timedelta(hours=6)  # an area's lock lapses unless renewed (R11)


class RuleError(ValueError):
    """A change a rule refuses: `code` for the caller (409 for a stale page, 400 otherwise), `words` for a person."""

    def __init__(self, code: str, words: str):
        super().__init__(words)
        self.code, self.words = code, words


def now() -> datetime:
    return datetime.now(UTC)


def _event(db: Session, actor: str, kind: str, thing: str, thing_id: int, area_id: int | None = None, **data) -> FftEvent:
    ev = FftEvent(actor=actor, kind=kind, thing=thing, thing_id=thing_id, area_id=area_id, data=data)
    db.add(ev)
    return ev


def _expect(row, attr: str, seen: str | None) -> None:
    """R14: a change made from a page that's out of date is refused with what changed, never applied over it."""
    if seen is not None and getattr(row, attr) != seen:
        raise RuleError("stale", f"It changed while you were looking: it's {getattr(row, attr)} now, not {seen}.")


def _clean_context(ctx: dict) -> dict:
    """T2: no email, ever, in what's kept about a note's page (who was signed in or viewing as, in full)."""
    out = {}
    for k, v in (ctx or {}).items():
        if "email" in k or k in ("signed_in_as",):
            continue
        if isinstance(v, str) and "@" in v:
            continue
        out[k] = v
    return out


# ------------------------------------------------------------------ notes (R1, R2)


def send_note(db: Session, *, user_id: int | None, first_name: str, role: str, kind: str, text: str, url: str = "",
              page: str = "", context: dict | None = None, html: str = "", staging: bool = False,
              try_id: int | None = None) -> FftNote:
    """R1: a player's note waits for an admin; an admin's is filed at once (a problem as an issue, an idea on the
    ideas list, a question for Claude to answer). A note relayed from staging always waits (T6): the relay names its
    sender but can't prove it."""
    if kind not in KINDS:
        raise RuleError("bad", "Say what it is: a problem, an idea or a question.")
    if not (text or "").strip():
        raise RuleError("bad", "Write what it's about.")
    if role not in ROLES:
        role = "member"
    note = FftNote(user_id=user_id, first_name=(first_name or "Someone").split(" ")[0][:60], role=role, kind=kind,
                   text=text.strip(), url=url[:1000], page=page[:120], context=_clean_context(context or {}),
                   html=html or "", staging=staging, try_id=try_id)
    db.add(note)
    db.flush()
    _event(db, f"user:{user_id}" if user_id else "askdnd", "note_sent", "note", note.id, note_kind=kind, role=role, staging=staging)
    if role == "admin" and not staging:
        _file_own(db, note, f"user:{user_id}")
    return note


def _file_own(db: Session, note: FftNote, actor: str) -> None:
    if note.kind == "problem":
        file_issue(db, actor, note)
    elif note.kind == "idea":
        file_idea(db, actor, note)
    else:
        note.state, note.filed_as = "filed", "question"
        _event(db, actor, "note_filed", "note", note.id, as_="question")


def _first_words(text: str, n: int = 90) -> str:
    t = " ".join((text or "").split())
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


def file_issue(db: Session, actor: str, note: FftNote, title: str = "") -> FftIssue:
    """A note becomes a new issue (Claude's: to fix)."""
    _waiting_or_own(note)
    issue = FftIssue(title=(title or _first_words(note.text))[:120], from_player=note.role != "admin")
    db.add(issue)
    db.flush()
    note.state, note.filed_as, note.issue_id = "filed", "issue", issue.id
    _approve_lines(db, note)
    _event(db, actor, "issue_new", "issue", issue.id, from_note=note.id)
    _event(db, actor, "note_filed", "note", note.id, as_="issue", issue=issue.id)
    return issue


def join_issue(db: Session, actor: str, note: FftNote, issue: FftIssue) -> FftIssue:
    """R2: "same as": the note joins an issue already filed; its sender hears that issue's outcome, never another
    reporter's words or the issue's title. Unjoin from the issue's history."""
    _waiting_or_own(note)
    if issue.state == "closed" and issue.close_reason == "same" and issue.same_as_id:
        issue = db.get(FftIssue, issue.same_as_id)
    note.state, note.filed_as, note.issue_id = "filed", "issue", issue.id
    if note.role != "admin":
        issue.from_player = True
    _approve_lines(db, note)
    _event(db, actor, "note_joined", "note", note.id, issue=issue.id, area_id=issue.area_id)
    return issue


def unjoin(db: Session, actor: str, note: FftNote) -> FftIssue:
    """A note joined by mistake leaves its issue and becomes an issue of its own."""
    if note.filed_as != "issue" or note.issue_id is None:
        raise RuleError("bad", "It isn't joined to an issue.")
    was = note.issue_id
    issue = FftIssue(title=_first_words(note.text)[:120], from_player=note.role != "admin")
    db.add(issue)
    db.flush()
    note.issue_id = issue.id
    _event(db, actor, "note_unjoined", "note", note.id, was=was, issue=issue.id)
    return issue


def file_idea(db: Session, actor: str, note: FftNote, idea: FftIdea | None = None) -> FftIdea:
    _waiting_or_own(note)
    if idea is None:
        idea = FftIdea(title=_first_words(note.text)[:120])
        db.add(idea)
        db.flush()
    note.state, note.filed_as, note.idea_id = "filed", "idea", idea.id
    _approve_lines(db, note)
    _event(db, actor, "note_filed", "note", note.id, as_="idea", idea=idea.id)
    return idea


def answer_note(db: Session, actor: str, note: FftNote, words: str, user_id: int | None = None) -> FftLine:
    """A question someone sent, answered (its sender reads the answer)."""
    if not words.strip():
        raise RuleError("bad", "Write the answer.")
    if note.state == "waiting":
        _approve_lines(db, note)
    note.state, note.filed_as = "filed", "answered"
    line = add_line(db, actor, words, note=note, to="sender", user_id=user_id)
    _event(db, actor, "note_filed", "note", note.id, as_="answered")
    return line


def decline(db: Session, actor: str, note: FftNote, words: str = "") -> None:
    if note.state != "waiting":
        raise RuleError("stale", "It's already been decided.")
    note.state = "declined"
    if words.strip():
        add_line(db, actor, words, note=note, to="sender")
    _event(db, actor, "note_declined", "note", note.id)


def undo_decision(db: Session, actor: str, note: FftNote) -> None:
    """Undo an approve or decline within a minute, while nothing else has happened to what it made."""
    last = db.scalar(select(FftEvent).where(FftEvent.thing == "note", FftEvent.thing_id == note.id,
                                            FftEvent.kind.in_(("note_filed", "note_joined", "note_declined"))).order_by(FftEvent.id.desc()))
    if last is None or now() - (last.at or now()) > UNDO:
        raise RuleError("late", "It's too late to undo that; change it from its page.")
    if note.filed_as == "issue" and note.issue_id:
        issue = db.get(FftIssue, note.issue_id)
        others = db.scalar(select(func.count()).select_from(FftNote).where(FftNote.issue_id == issue.id, FftNote.id != note.id))
        later = db.scalar(select(func.count()).select_from(FftEvent).where(FftEvent.thing == "issue", FftEvent.thing_id == issue.id,
                                                                           FftEvent.kind != "issue_new"))
        if not others and not later:
            db.delete(issue)
    note.state, note.filed_as, note.issue_id, note.idea_id = "waiting", "", None, None
    _event(db, actor, "note_undone", "note", note.id)


def _waiting_or_own(note: FftNote) -> None:
    """Only a note still waiting can be decided (an admin's is decided as it's sent)."""
    if note.state != "waiting":
        raise RuleError("stale", "It's already been decided.")


def add_line(db: Session, actor: str, text: str, *, note: FftNote | None = None, issue: FftIssue | None = None,
             to: str = "", who: str | None = None, user_id: int | None = None, approved: bool = True) -> FftLine:
    """A line of conversation. A player's own line (who="sender", not an admin) waits for approval (T1)."""
    if not (text or "").strip():
        raise RuleError("bad", "Write something first.")
    who = who or ("claude" if actor == "claude" else "admin" if actor.startswith("user:") else "askdnd")
    line = FftLine(note_id=note.id if note else None, issue_id=issue.id if issue else None, who=who, user_id=user_id,
                   to=to, text=text.strip(), approved=approved)
    db.add(line)
    db.flush()
    _event(db, actor, "line_added", "note" if note else "issue", (note or issue).id, line=line.id, to=to, approved=approved)
    return line


def _approve_lines(db: Session, note: FftNote) -> None:
    for line in db.scalars(select(FftLine).where(FftLine.note_id == note.id, FftLine.approved.is_(False))):
        line.approved = True


def approve_line(db: Session, actor: str, line: FftLine) -> None:
    """A player's added words (or "still broken") approved: now Claude may read them."""
    line.approved = True
    _event(db, actor, "line_approved", "note", line.note_id or 0, line=line.id)


# ------------------------------------------------------------------ issues (R4, R8, R9, R13, R17)


def _set_issue(db: Session, actor: str, issue: FftIssue, to: str, kind: str, **data) -> None:
    was = issue.state
    issue.state = to
    _event(db, actor, kind, "issue", issue.id, area_id=issue.area_id, **{"from": was, "to": to}, **data)


def new_issue(db: Session, actor: str, title: str, area_id: int | None = None, origin_try_id: int | None = None) -> FftIssue:
    if not title.strip():
        raise RuleError("bad", "Give it a title.")
    issue = FftIssue(title=title.strip()[:120], area_id=area_id, origin_try_id=origin_try_id)
    db.add(issue)
    db.flush()
    _event(db, actor, "issue_new", "issue", issue.id, area_id=area_id, origin_try=origin_try_id)
    return issue


def move_issue(db: Session, actor: str, issue: FftIssue, area_id: int | None) -> None:
    """R8: moved to another area; its checks are worked out again (check_state reads issues live)."""
    was = issue.area_id
    issue.area_id = area_id
    _event(db, actor, "issue_moved", "issue", issue.id, area_id=area_id, was=was)


def start_fixing(db: Session, actor: str, issue: FftIssue) -> None:
    if issue.state != "to_fix":
        raise RuleError("stale", f"It's {issue.state}, not waiting to be fixed.")
    _set_issue(db, actor, issue, "fixing", "issue_fixing")


def fix_ready(db: Session, actor: str, issue: FftIssue, pr: str) -> None:
    """Claude's fix is in a pull request. R17: one a player's words prompted waits for Brett's OK to merge."""
    if issue.state not in ("to_fix", "fixing"):
        raise RuleError("stale", f"It's {issue.state}.")
    if not pr.startswith("https://"):
        raise RuleError("bad", "The fix's pull request is an https:// link.")
    issue.pr = pr
    if issue.from_player:
        _set_issue(db, actor, issue, "merge_ok", "issue_merge_ok", pr=pr)
    else:
        _event(db, actor, "issue_pr", "issue", issue.id, area_id=issue.area_id, pr=pr)


def ok_merge(db: Session, actor: str, issue: FftIssue) -> None:
    """Brett's OK on a player-prompted fix (R17): it may merge."""
    if issue.state != "merge_ok":
        raise RuleError("stale", f"It's {issue.state}, not waiting for your OK.")
    _set_issue(db, actor, issue, "fixing", "issue_merge_okd")


def may_merge(db: Session, issue: FftIssue) -> tuple[bool, str]:
    """R11 and R17: may this issue's fix merge to askdnd.ai now?"""
    if issue.state == "merge_ok":
        return False, "It waits for Brett's OK to merge (a player's words prompted it)."
    if round_open(db) and not stops_round(db, issue):
        return False, "Brett's round is open: nothing merges until it ends (only an issue that stops his round may)."
    return True, ""


def fix_live(db: Session, actor: str, issue: FftIssue, commit: str) -> None:
    """R4: merged and live: ready to try. A player who reported it confirms it (R5)."""
    if issue.state not in ("fixing", "to_fix"):
        raise RuleError("stale", f"It's {issue.state}.")
    issue.fixed_in = commit[:40]
    reporter = db.scalar(select(FftNote.user_id).where(FftNote.issue_id == issue.id, FftNote.role != "admin", FftNote.user_id.isnot(None)))
    if reporter:
        issue.confirm_by, issue.confirm_since = reporter, now()
    _set_issue(db, actor, issue, "ready", "issue_live", commit=commit)


def rollback(db: Session, actor: str, commit: str) -> list[int]:
    """R9: a fix rolled back: its issues are Claude's again; checks waiting on them leave To try."""
    back = list(db.scalars(select(FftIssue).where(FftIssue.fixed_in == commit, FftIssue.state == "ready")))
    for issue in back:
        issue.fixed_in, issue.confirm_by, issue.confirm_since = "", None, None
        _set_issue(db, actor, issue, "fixing", "issue_rolled_back", commit=commit)
    return [i.id for i in back]


def close(db: Session, actor: str, issue: FftIssue, reason: str, words: str = "", same_as: FftIssue | None = None,
          seen: str | None = None) -> None:
    """Closing needs a reason its senders read. "Same as" moves its notes to the other issue (R2, R8)."""
    _expect(issue, "state", seen)
    if reason not in CLOSE_REASONS:
        raise RuleError("bad", "Say why: works now, won't do, same as, can't reproduce, or withdrawn.")
    if issue.state == "closed":
        raise RuleError("stale", "It's already closed.")
    if reason == "same":
        if same_as is None or same_as.id == issue.id:
            raise RuleError("bad", "Same as which issue?")
        issue.same_as_id = same_as.id
        for note in db.scalars(select(FftNote).where(FftNote.issue_id == issue.id)):
            note.issue_id = same_as.id
    issue.close_reason, issue.close_words = reason, words.strip()
    _set_issue(db, actor, issue, "closed", "issue_closed", reason=reason)


def reopen(db: Session, actor: str, issue: FftIssue) -> None:
    """A closed issue came back: Claude's to fix again, and it says so."""
    if issue.state != "closed":
        raise RuleError("stale", "It isn't closed.")
    issue.reopened += 1
    issue.close_reason = issue.close_words = ""
    issue.fixed_in, issue.confirm_by, issue.confirm_since = "", None, None
    _set_issue(db, actor, issue, "to_fix", "issue_reopened")


def confirm_due(db: Session, actor: str = "askdnd") -> list[int]:
    """R5: a player's confirmation unanswered for three days becomes Brett's."""
    late = list(db.scalars(select(FftIssue).where(FftIssue.state == "ready", FftIssue.confirm_by.isnot(None),
                                                 FftIssue.confirm_since < now() - timedelta(days=CONFIRM_DAYS))))
    for issue in late:
        issue.confirm_by = None
        _event(db, actor, "issue_confirm_brett", "issue", issue.id, area_id=issue.area_id)
    return [i.id for i in late]


def player_confirms(db: Session, actor: str, issue: FftIssue, works: bool, words: str = "", user_id: int | None = None) -> None:
    """Does it work now? Yes closes it; still broken sends it back to Claude, the words waiting for approval (T1)."""
    if issue.state != "ready" or issue.confirm_by != user_id:
        raise RuleError("stale", "It isn't yours to confirm now.")
    if works:
        issue.close_reason = "works"
        _set_issue(db, actor, issue, "closed", "issue_confirmed", by="player")
        return
    note = db.scalar(select(FftNote).where(FftNote.issue_id == issue.id, FftNote.user_id == user_id))
    if note is not None and words.strip():
        add_line(db, actor, "Still broken. " + words, note=note, to="claude", who="sender", user_id=user_id, approved=False)
    issue.confirm_by = issue.confirm_since = None
    _set_issue(db, actor, issue, "to_fix", "issue_still_broken", by="player")


# ------------------------------------------------------------------ checks (R7, R16, R18)


def write_check(db: Session, actor: str, *, title: str, steps: list[str], expect: str, path: str = "", why: str = "",
                area_id: int | None = None, devices: list[str] | None = None, issue_ids: list[int] | None = None,
                minutes: int = 2) -> FftCheck:
    if not title.strip() or not steps:
        raise RuleError("bad", "A check needs its title and steps.")
    devices = [d for d in (devices or ["laptop"]) if d in DEVICES] or ["laptop"]
    check = FftCheck(title=title.strip()[:160], area_id=area_id, devices=devices, minutes=max(1, min(60, minutes)))
    db.add(check)
    db.flush()
    db.add(FftCheckVersion(check_id=check.id, version=1, path=path[:500], steps=steps, expect=expect, why=why))
    for iid in issue_ids or []:
        db.add(FftCheckIssue(check_id=check.id, issue_id=iid))
    _event(db, actor, "check_written", "check", check.id, area_id=area_id, issues=issue_ids or [])
    return check


def new_version(db: Session, actor: str, check: FftCheck, *, steps: list[str], expect: str, path: str = "", why: str) -> int:
    """R7: every edit is a new version; earlier tries keep theirs. Its pre-flight starts again (R18)."""
    if not why.strip():
        raise RuleError("bad", "Say why it changed.")
    check.version += 1
    check.preflight = ""
    db.add(FftCheckVersion(check_id=check.id, version=check.version, path=path[:500], steps=steps, expect=expect, why=why))
    _event(db, actor, "check_version", "check", check.id, area_id=check.area_id, version=check.version)
    return check.version


def preflight(db: Session, actor: str, check: FftCheck, passed: bool, why: str = "") -> None:
    """R18: a check is tried automatically before it reaches Brett; one that fails it never does."""
    check.preflight = "passed" if passed else "failed"
    _event(db, actor, "check_preflight", "check", check.id, area_id=check.area_id, passed=passed, why=why[:300])


def retire(db: Session, actor: str, check: FftCheck, why: str = "") -> None:
    check.retired = True
    _event(db, actor, "check_retired", "check", check.id, area_id=check.area_id, why=why[:300])


def link_issue(db: Session, actor: str, check: FftCheck, issue: FftIssue) -> None:
    if db.get(FftCheckIssue, (check.id, issue.id)) is None:
        db.add(FftCheckIssue(check_id=check.id, issue_id=issue.id))
        _event(db, actor, "check_linked", "check", check.id, area_id=check.area_id, issue=issue.id)


# ------------------------------------------------------------------ tries (R3, R5, R6, R7, R10)


@dataclass
class Found:
    """One issue a failed try names: an existing one still happening (`issue_id`), or a new one (`title`)."""

    issue_id: int | None = None
    title: str = ""
    blocking: bool = True
    stops_round: bool = False
    words: list[str] = field(default_factory=list)


def _blocking_issues(db: Session, check: FftCheck) -> list[FftIssue]:
    """The issues that hold a check: those it tries the fix of, and those a live try named as stopping it."""
    linked = set(db.scalars(select(FftCheckIssue.issue_id).where(FftCheckIssue.check_id == check.id)))
    named = db.execute(select(FftTryIssue.issue_id, FftTryIssue.blocking).join(FftTry, FftTry.id == FftTryIssue.try_id)
                       .where(FftTry.check_id == check.id, FftTry.replaced.is_(False))).all()
    nonblocking = {i for i, b in named if not b}
    ids = (linked | {i for i, b in named if b}) - (nonblocking - linked)
    return list(db.scalars(select(FftIssue).where(FftIssue.id.in_(ids)))) if ids else []


def record_try(db: Session, actor: str, check: FftCheck, *, result: str, device: str = "laptop", where: str = "live",
               app_version: str = "", user_id: int | None = None, round_id: int | None = None,
               found: list[Found] | None = None, cant_kind: str = "", blocked_by: int | None = None, why: str = "",
               seen: dict | None = None) -> FftTry:
    """One go at a check. Passed: R5. Failed: R3 (each issue new or still happening; blocking or not). Can't try: R7.
    The Mac Mini's pass is recorded but confirms nothing (R10, R16)."""
    if check.retired:
        raise RuleError("stale", "That check is retired.")
    if result not in ("passed", "failed", "cant"):
        raise RuleError("bad", "Passed, failed, or can't try.")
    if device not in DEVICES or where not in WHERE:
        raise RuleError("bad", "Which device, and where?")
    if seen is not None:
        state = check_state(db, check)["devices"].get(device)
        if state is not None and seen.get(device) is not None and state != seen[device]:
            raise RuleError("stale", f"It changed while you were looking: it's {state} on your {device} now.")
    if result == "failed" and not found:
        raise RuleError("bad", "Say what's wrong.")
    if result == "cant" and cant_kind not in CANT:
        raise RuleError("bad", "Later, blocked by an issue, or the check is wrong?")
    if cant_kind == "blocked" and blocked_by is None:
        raise RuleError("bad", "Blocked by which issue?")
    t = FftTry(check_id=check.id, version=check.version, user_id=user_id, actor="mini" if actor == "mini" else "person",
               device=device, where=where, app_version=app_version[:40], result=result, cant_kind=cant_kind,
               blocked_by=blocked_by, why=why, round_id=round_id)
    db.add(t)
    db.flush()
    if round_id:
        r = db.get(FftRound, round_id)
        if r is not None:
            r.last_at = now()
    _event(db, actor, "try_" + result, "try", t.id, area_id=check.area_id, check=check.id, device=device, where=where)
    if result == "failed":
        for f in found or []:
            _name_issue(db, actor, check, t, f)
    elif result == "passed":
        _passed(db, actor, check, t, user_id)
    elif cant_kind == "wrong":
        check.asks = False
        _event(db, actor, "check_wrong", "check", check.id, area_id=check.area_id)
    return t


def still_happening(db: Session, actor: str, issue: FftIssue, check: FftCheck | None = None) -> None:
    """A fixed issue seen again: Claude's to fix (a closed one reopens, saying it came back)."""
    if issue.state == "closed":
        reopen(db, actor, issue)
    elif issue.state in ("ready", "merge_ok", "fixing"):
        issue.fixed_in, issue.confirm_by, issue.confirm_since = "", None, None
        _set_issue(db, actor, issue, "to_fix", "issue_still_happening", check=check.id if check else None)


def _name_issue(db: Session, actor: str, check: FftCheck, t: FftTry, f: Found) -> FftIssue:
    if f.issue_id:
        issue = db.get(FftIssue, f.issue_id)
        how = "still"
        still_happening(db, actor, issue, check)
    else:
        issue = new_issue(db, actor, f.title, area_id=check.area_id, origin_try_id=t.id)
        how = "new"
    db.add(FftTryIssue(try_id=t.id, issue_id=issue.id, blocking=f.blocking, how=how, stops_round=f.stops_round))
    if f.blocking:
        link_issue(db, actor, check, issue)
    for w in f.words:
        add_line(db, actor, w, issue=issue, to="claude", who="admin")
    return issue


def add_found(db: Session, actor: str, t: FftTry, f: Found) -> FftIssue:
    """Another issue on a try already failed (✗ Another…: the same button again, screen 4)."""
    if t.result != "failed" or t.replaced:
        raise RuleError("stale", "That try isn't a failed one any more.")
    check = db.get(FftCheck, t.check_id)
    if f.issue_id and db.scalar(select(FftTryIssue).where(FftTryIssue.try_id == t.id, FftTryIssue.issue_id == f.issue_id)):
        raise RuleError("bad", "This try already named that issue.")
    issue = _name_issue(db, actor, check, t, f)
    _event(db, actor, "try_found", "try", t.id, area_id=check.area_id, issue=issue.id)
    return issue


def note_on_issue(db: Session, actor: str, issue: FftIssue, *, user_id: int | None, first_name: str, text: str, url: str = "",
                  page: str = "", context: dict | None = None, html: str = "", try_id: int | None = None) -> FftNote:
    """What an admin saw while trying a check, kept as their note on the issue it found (an admin's words need no
    approval, R1): the words, the page, the pictures (kept by the caller)."""
    if not (text or "").strip():
        raise RuleError("bad", "Say what's wrong.")
    note = FftNote(user_id=user_id, first_name=(first_name or "Someone").split(" ")[0][:60], role="admin", kind="problem",
                   text=text.strip(), url=url[:1000], page=page[:120], context=_clean_context(context or {}), html=html or "",
                   state="filed", filed_as="issue", issue_id=issue.id, try_id=try_id)
    db.add(note)
    db.flush()
    _event(db, actor, "note_sent", "note", note.id, note_kind="problem", role="admin", staging=False)
    _event(db, actor, "note_joined", "note", note.id, issue=issue.id, area_id=issue.area_id)
    return note


def _failing_elsewhere(db: Session, issue: FftIssue, check: FftCheck, device: str) -> bool:
    """Is this issue still failing on another check, or on another device this check requires?"""
    rows = db.execute(select(FftTry.check_id, FftTry.device, FftTry.id).join(FftTryIssue, FftTryIssue.try_id == FftTry.id)
                      .where(FftTryIssue.issue_id == issue.id, FftTryIssue.blocking.is_(True), FftTry.replaced.is_(False))).all()
    for cid, dev, _tid in rows:
        if cid == check.id and dev == device:
            continue
        other = db.get(FftCheck, cid)
        if other is None or other.retired:
            continue
        if check_state(db, other)["devices"].get(dev) == "failed":
            return True
    return False


def _passed(db: Session, actor: str, check: FftCheck, t: FftTry, user_id: int | None) -> None:
    """R5: only blocking issues, fixed and live, with no failing try left elsewhere, close: works now (or wait for the
    player who reported it). An automated pass confirms nothing (R16)."""
    if actor == "mini":
        return
    for issue in _blocking_issues(db, check):
        if issue.state != "ready" or _failing_elsewhere(db, issue, check, t.device):
            continue
        if issue.confirm_by and issue.confirm_by != user_id:
            continue  # (a player's to confirm first; Brett's after three days)
        issue.close_reason = "works"
        _set_issue(db, actor, issue, "closed", "issue_closed", reason="works", by_try=t.id)


def correct_try(db: Session, actor: str, t: FftTry, result: str, why: str, user_id: int | None = None) -> FftTry:
    """R6: a correction is a new try that replaces the old, both kept. An issue the old try alone created (no note, no
    fix, named by no other try) closes as withdrawn; one it marked still happening goes back to ready to try."""
    if t.replaced:
        raise RuleError("stale", "That try was already corrected.")
    if result not in ("passed", "cant", "untried"):
        raise RuleError("bad", "Passed, can't try, or back to to try.")
    if not why.strip():
        raise RuleError("bad", "Say why, for the history.")
    t.replaced = True
    new = FftTry(check_id=t.check_id, version=t.version, user_id=user_id, actor=t.actor, device=t.device, where=t.where,
                 app_version=t.app_version, result=result, why=why, replaces_id=t.id, round_id=t.round_id,
                 cant_kind="later" if result == "cant" else "")
    db.add(new)
    db.flush()
    check = db.get(FftCheck, t.check_id)
    _event(db, actor, "try_corrected", "try", new.id, area_id=check.area_id, replaces=t.id, result=result)
    for ti in db.scalars(select(FftTryIssue).where(FftTryIssue.try_id == t.id)):
        issue = db.get(FftIssue, ti.issue_id)
        if ti.how == "new" and issue.origin_try_id == t.id and issue.state != "closed":
            used = db.scalar(select(func.count()).select_from(FftNote).where(FftNote.issue_id == issue.id,  # (the tester's own note with this try doesn't count)
                                                                              or_(FftNote.try_id.is_(None), FftNote.try_id != t.id))) or issue.pr \
                or db.scalar(select(func.count()).select_from(FftTryIssue).where(FftTryIssue.issue_id == issue.id, FftTryIssue.try_id != t.id))
            if not used:
                issue.close_reason = "withdrawn"
                _set_issue(db, actor, issue, "closed", "issue_closed", reason="withdrawn", by_correction=new.id)
                db.execute(FftCheckIssue.__table__.delete().where(FftCheckIssue.check_id == check.id, FftCheckIssue.issue_id == issue.id))
        elif ti.how == "still" and issue.state == "to_fix":
            prior = db.scalar(select(FftEvent.data).where(FftEvent.thing == "issue", FftEvent.thing_id == issue.id,
                                                          FftEvent.kind.in_(("issue_still_happening", "issue_reopened"))).order_by(FftEvent.id.desc()))
            back = (prior or {}).get("from", "ready")
            if back == "closed":
                issue.close_reason = "works"
            _set_issue(db, actor, issue, back if back in ISSUE_STATES else "ready", "issue_unmarked", by_correction=new.id)
    if result == "passed":
        _passed(db, actor, check, new, user_id)
    return new


def check_state(db: Session, check: FftCheck) -> dict:
    """Where a check stands, per required device and overall, worked out from its live tries and its issues (never
    kept): to_try (first time, or `again` once a fix is live), passed, failed (a try failed and its issues aren't
    fixed), fixing (its fix isn't live yet), later, blocked, wrong (the check must be rewritten), preflight (Claude
    hasn't tried this version itself yet, R18), retired; and whose turn it is."""
    if check.retired:
        return {"state": "retired", "turn": "closed", "devices": {}, "again": False}
    blocking = _blocking_issues(db, check)
    open_claude = [i for i in blocking if i.state in ("to_fix", "fixing", "asks", "merge_ok")]
    devices = {}
    again = False
    for dev in check.devices or ["laptop"]:
        last = db.scalar(select(FftTry).where(FftTry.check_id == check.id, FftTry.device == dev, FftTry.replaced.is_(False),
                                              FftTry.actor == ("mini" if dev == "mac_mini" else "person")).order_by(FftTry.id.desc()))
        if last is None or last.result == "untried":
            devices[dev] = "fixing" if open_claude else "to_try"
        elif last.result == "failed":
            named = set(db.scalars(select(FftTryIssue.issue_id).where(FftTryIssue.try_id == last.id, FftTryIssue.blocking.is_(True))))
            still = [i for i in blocking if i.id in named and i.state != "ready" and i.state != "closed"]
            devices[dev] = "failed" if still or open_claude else "to_try"
            again = again or devices[dev] == "to_try"
        elif last.result == "passed":
            devices[dev] = "fixing" if open_claude else "passed"
        elif last.cant_kind == "blocked":
            b = db.get(FftIssue, last.blocked_by) if last.blocked_by else None
            devices[dev] = "to_try" if b is None or b.state in ("ready", "closed") else "blocked"
        elif last.cant_kind == "wrong":
            devices[dev] = "to_try" if last.version < check.version else "wrong"
        else:
            devices[dev] = "later"
    vals = list(devices.values())
    state = next((s for s in ("failed", "fixing", "wrong", "blocked", "to_try", "later") if s in vals), "passed")
    if check.asks and state != "passed":
        state = "asks"
    turn = {"failed": "claude", "fixing": "claude", "wrong": "claude", "blocked": "claude", "to_try": "brett", "later": "brett",
            "asks": "brett", "passed": "closed"}[state]
    if turn == "brett" and not any(d != "mac_mini" for d in check.devices or ["laptop"]):
        turn = "claude"  # (only the Mac Mini runs it: Claude's, never Brett's)
    if state == "to_try" and check.preflight != "passed":  # (R18: it never reaches Brett until it passes its own try)
        state, turn = ("wrong" if check.preflight == "failed" else "preflight"), "claude"
    return {"state": state, "turn": turn, "devices": devices, "again": again}


# ------------------------------------------------------------------ rounds, areas, the one order (R11, R12, R15)


def open_round(db: Session, actor: str, user_id: int | None, area_id: int | None = None) -> FftRound:
    _expire_rounds(db)
    r = db.scalar(select(FftRound).where(FftRound.ended_at.is_(None), FftRound.user_id == user_id))
    if r is None:
        r = FftRound(user_id=user_id, area_id=area_id)
        db.add(r)
        db.flush()
        _event(db, actor, "round_opened", "round", r.id, area_id=area_id)
    return r


def end_round(db: Session, actor: str, r: FftRound) -> None:
    if r.ended_at is None:
        r.ended_at = now()
        _event(db, actor, "round_ended", "round", r.id, area_id=r.area_id)


def _expire_rounds(db: Session) -> None:
    for r in db.scalars(select(FftRound).where(FftRound.ended_at.is_(None), FftRound.last_at < now() - ROUND_IDLE)):
        end_round(db, "askdnd", r)


def round_open(db: Session) -> FftRound | None:
    _expire_rounds(db)
    return db.scalar(select(FftRound).where(FftRound.ended_at.is_(None)).order_by(FftRound.id.desc()))


def stops_round(db: Session, issue: FftIssue) -> bool:
    return bool(db.scalar(select(func.count()).select_from(FftTryIssue).where(FftTryIssue.issue_id == issue.id, FftTryIssue.stops_round.is_(True))))


def lock_area(db: Session, owner: str, area: FftArea) -> None:
    """R11: one area is Claude's at a time; the lock has an owner and lapses."""
    held = db.scalar(select(FftArea).where(FftArea.lock_owner != "", FftArea.lock_until > now(), FftArea.id != area.id))
    if held is not None:
        raise RuleError("busy", f"{held.title} is already in hand ({held.lock_owner}); one area at a time.")
    area.lock_owner, area.lock_until = owner[:60], now() + LOCK
    _event(db, owner, "area_locked", "area", area.id, area_id=area.id)


def unlock_area(db: Session, owner: str, area: FftArea) -> None:
    area.lock_owner, area.lock_until = "", None
    _event(db, owner, "area_unlocked", "area", area.id, area_id=area.id)


def area_open_issues(db: Session, area: FftArea) -> list[FftIssue]:
    return list(db.scalars(select(FftIssue).where(FftIssue.area_id == area.id, FftIssue.state != "closed")))


def area_checks(db: Session, area: FftArea) -> list[FftCheck]:
    return list(db.scalars(select(FftCheck).where(FftCheck.area_id == area.id, FftCheck.retired.is_(False))))


def area_done(db: Session, area: FftArea) -> bool:
    """R12: done when its issues are all closed and its checks passed or retired."""
    return not area_open_issues(db, area) and all(check_state(db, c)["state"] == "passed" for c in area_checks(db, area))


def area_turn(db: Session, area: FftArea) -> str:
    """Whose turn an area is: claude (issues to fix, checks failed or wrong), brett (checks to try, questions), done."""
    issues = area_open_issues(db, area)
    states = [check_state(db, c)["state"] for c in area_checks(db, area)]
    if any(i.state in ("to_fix", "fixing") for i in issues) or any(s in ("failed", "fixing", "wrong", "blocked") for s in states):
        return "claude"
    if any(i.state in ("asks", "merge_ok", "ready") for i in issues) or any(s in ("to_try", "later", "asks") for s in states):
        return "brett"
    return "done"


def in_open_round(db: Session, area: FftArea) -> bool:
    r = round_open(db)
    if r is None:
        return False
    if r.area_id is not None:
        return r.area_id == area.id
    return any(check_state(db, c)["turn"] == "brett" for c in area_checks(db, area))


@dataclass
class Pick:
    area: FftArea | None
    why: str
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (what, why)
    blocker: bool = False


def pick_next(db: Session) -> Pick:
    """R15: a blocker first (an issue that stops Brett's round); otherwise the Roadmap from the top, each item's areas
    in his order, skipping an item whose next step is his and an area in his open round; the first that's Claude's."""
    r = round_open(db)
    if r is not None:
        stop = db.scalar(select(FftIssue).join(FftTryIssue, FftTryIssue.issue_id == FftIssue.id)
                         .where(FftTryIssue.stops_round.is_(True), FftIssue.state.in_(("to_fix", "fixing"))))
        if stop is not None and stop.area_id:
            return Pick(db.get(FftArea, stop.area_id), f"Blocker: “{stop.title}” stops Brett's round.", blocker=True)
    skipped = []
    items = db.scalars(select(FftItem).where(FftItem.section.in_(("now", "next", "later"))).order_by(FftItem.place, FftItem.id))
    for item in items:
        if item.next_whose == "brett":
            skipped.append((item.title, f"its next step is Brett's ({item.next_step})" if item.next_step else "its next step is Brett's"))
            continue
        for area in db.scalars(select(FftArea).where(FftArea.item_id == item.id, FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id)):
            turn = area_turn(db, area)
            if turn != "claude":
                continue
            if in_open_round(db, area):
                skipped.append((f"{item.title} › {area.title}", "in Brett's open round"))
                continue
            return Pick(area, f"{item.title} › {area.title}", skipped)
    return Pick(None, "Nothing is Claude's turn.", skipped)


# ------------------------------------------------------------------ questions (R13)


def ask(db: Session, actor: str, *, about: str, about_id: int | None, text: str, choices: list[dict] | None = None,
        mine: int | None = None, doc_path: str = "", doc_version: str = "") -> FftQuestion:
    if about not in ("issue", "check", "area", "document"):
        raise RuleError("bad", "About an issue, a check, an area, or a document.")
    if not text.strip():
        raise RuleError("bad", "Ask something.")
    choices = choices or []
    if choices and not 2 <= len(choices) <= 4:
        raise RuleError("bad", "Two to four answers to tap.")
    if mine is not None and not 0 <= mine < len(choices):
        raise RuleError("bad", "Your pick is one of the answers.")
    q = FftQuestion(about=about, about_id=about_id, text=text.strip(), choices=choices, mine=mine, doc_path=doc_path, doc_version=doc_version)
    db.add(q)
    db.flush()
    if about == "issue" and about_id:
        issue = db.get(FftIssue, about_id)
        if issue is not None and issue.state in ("to_fix", "fixing"):
            _set_issue(db, actor, issue, "asks", "issue_asks", question=q.id)
    if about == "check" and about_id:
        c = db.get(FftCheck, about_id)
        if c is not None:
            c.asks = True
    _event(db, actor, "question_asked", "question", q.id, about=about, about_id=about_id)
    return q


def answer(db: Session, actor: str, q: FftQuestion, *, choice: int | None, text: str = "", user_id: int | None = None) -> None:
    """R13: the answer names its question, so a newer one can't take it; it moves the thing back to Claude."""
    if q.answered_at is not None:
        raise RuleError("stale", "It's already answered.")
    if choice is None and not text.strip():
        raise RuleError("bad", "Pick an answer or write one.")
    if choice is not None and not 0 <= choice < len(q.choices or []):
        raise RuleError("bad", "That isn't one of its answers.")
    q.answer_choice, q.answer_text, q.answered_at, q.answered_by = choice, text.strip(), now(), user_id
    if q.about == "issue" and q.about_id:
        issue = db.get(FftIssue, q.about_id)
        if issue is not None and issue.state == "asks":
            open_q = db.scalar(select(func.count()).select_from(FftQuestion).where(FftQuestion.about == "issue", FftQuestion.about_id == issue.id,
                                                                                   FftQuestion.answered_at.is_(None), FftQuestion.id != q.id))
            if not open_q:
                _set_issue(db, actor, issue, "to_fix", "issue_answered", question=q.id)
    if q.about == "check" and q.about_id:
        c = db.get(FftCheck, q.about_id)
        if c is not None:
            c.asks = False
    _event(db, actor, "question_answered", "question", q.id, choice=choice)


# ------------------------------------------------------------------ listeners (T8)

SETTLE = timedelta(seconds=5)  # read only events this old, so one saved out of order isn't skipped


def listener(db: Session, name: str, area_id: int | None = None) -> FftListener:
    li = db.scalar(select(FftListener).where(FftListener.name == name))
    if li is None:
        li = FftListener(name=name[:60], area_id=area_id)
        db.add(li)
        db.flush()
    return li


def unread(db: Session, li: FftListener, peek: bool = False) -> list[FftEvent]:
    """What this listener hasn't read (one area's only, for an area's own chat); marked read unless `peek`."""
    q = select(FftEvent).where(FftEvent.id > li.read_id, FftEvent.at <= func.now() - SETTLE).order_by(FftEvent.id)
    if li.area_id is not None:
        q = q.where(FftEvent.area_id == li.area_id)
    rows = list(db.scalars(q.limit(500)))
    li.heard_at = now()
    if rows and not peek:
        li.read_id = rows[-1].id
    return rows
