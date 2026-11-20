"""Every change to Found, Fixed, Tried goes through here (the v2 brief's rules R1–R18 and trust T1–T8,
docs/mockups/feedback-and-testing/index.html): each function checks its rule, changes the rows, and writes the event in
the same transaction (`_event`). Nothing else sets a state. Callers commit; a refused change raises `RuleError`.

Words: an actor is "user:<id>", "claude", "mini" (the Mac Mini's runs) or "askdnd" (askdnd by itself)."""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, func, or_, select
from sqlalchemy.orm import Session

from app.fft import taxonomy
from app.fft.models import (
    FftAddition,
    FftArea,
    FftCheck,
    FftCheckIssue,
    FftCheckVersion,
    FftCheckWait,
    FftEvent,
    FftIdea,
    FftIssue,
    FftItem,
    FftLine,
    FftListener,
    FftLocalTry,
    FftNote,
    FftQuestion,
    FftRound,
    FftScope,
    FftStep,
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
    """T2: no email and no full name, ever, in what's kept about a note's page (who was signed in or viewing as), at any
    depth."""
    def clean(v):
        if isinstance(v, dict):
            return {k: clean(x) for k, x in v.items() if "email" not in k and k != "signed_in_as" and not (isinstance(x, str) and "@" in x)}
        if isinstance(v, list):
            return [clean(x) for x in v if not (isinstance(x, str) and "@" in x)]
        return v
    out = clean(ctx or {})
    if isinstance(out.get("viewing_as"), str):
        out["viewing_as"] = out["viewing_as"].split(" ")[0]  # (a first name only)
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
    first_name = "" if "@" in (first_name or "") else (first_name or "").split(" ")[0]
    note = FftNote(user_id=user_id, first_name=(first_name or "Someone")[:60], role=role, kind=kind,
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


def file_issue(db: Session, actor: str, note: FftNote, title: str = "", kind: str = "") -> FftIssue:
    """A note becomes a new issue (Claude's: to fix): a fix, or an improvement (by default as its sender called it)."""
    _waiting_or_own(note)
    kind = kind or ("improvement" if note.kind == "idea" else "fix")
    if kind not in ISSUE_KINDS:
        raise RuleError("bad", "A fix or an improvement.")
    issue = FftIssue(title=(title or _first_words(note.text))[:120], from_player=note.role != "admin", **({"kind": kind} if kind != "fix" else {}))
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
    made_player = held = False
    if note.role != "admin":  # (R17 retired, Nov 19: approving a player's note is the OK for its fix; nothing is held)
        made_player, issue.from_player = not issue.from_player, True
    _approve_lines(db, note)
    _event(db, actor, "note_joined", "note", note.id, issue=issue.id, area_id=issue.area_id,
           **({"made_player": True} if made_player else {}), **({"held": True} if held else {}))  # (what Undo puts back)
    return issue


def unjoin(db: Session, actor: str, note: FftNote) -> FftIssue:
    """A note joined by mistake leaves its issue and becomes an issue of its own."""
    if note.filed_as != "issue" or note.issue_id is None:
        raise RuleError("bad", "It isn't joined to an issue.")
    was = db.get(FftIssue, note.issue_id)
    issue = new_issue(db, actor, _first_words(note.text)[:120], feature=was.feature if was else "")  # (its own issue_new, and
    issue.from_player = note.role != "admin"                                                      # the Feature it came from)
    note.issue_id = issue.id
    _event(db, actor, "note_unjoined", "note", note.id, was=was.id if was else None, issue=issue.id)
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
        others = list(db.scalars(select(FftNote).where(FftNote.issue_id == issue.id, FftNote.id != note.id)))
        if last.kind == "note_filed":  # (an issue this note made: gone if nothing else came to it)
            later = db.scalar(select(func.count()).select_from(FftEvent).where(FftEvent.thing == "issue", FftEvent.thing_id == issue.id,
                                                                               FftEvent.kind != "issue_new"))
            if not others and not later:
                db.delete(issue)
        else:  # (joined to an issue that was there before: it stays, as it was before the join; the review of PR #417)
            said = last.data or {}
            if said.get("made_player"):
                issue.from_player = False
            if said.get("held") and issue.state == "merge_ok":
                _set_issue(db, actor, issue, "fixing", "issue_unmarked", undone=note.id)
    if note.filed_as == "idea" and note.idea_id and (idea := db.get(FftIdea, note.idea_id)):
        others = db.scalar(select(func.count()).select_from(FftNote).where(FftNote.idea_id == idea.id, FftNote.id != note.id))
        if not others:  # (a Roadmap idea this note made: gone with it, while nothing was added to it since)
            it = db.get(FftItem, idea.item_id) if idea.item_id else None
            if it is not None and latest_scope(db, it) is None and not db.scalar(select(func.count()).select_from(FftStep).where(FftStep.item_id == it.id)) \
                    and db.scalar(select(func.count()).select_from(FftAddition).where(FftAddition.item_id == it.id)) <= 1:
                note.idea_id = None
                db.flush()
                db.delete(idea)
                db.delete(it)
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


ISSUE_KINDS = ("fix", "improvement")  # (Brett, Nov 20: a change to a Product Area is a fix, it's broken, or an improvement,
# make it better; an idea that needs discussion is the Roadmap's)


def new_issue(db: Session, actor: str, title: str, area_id: int | None = None, origin_try_id: int | None = None,
              feature: str = "", kind: str = "fix") -> FftIssue:
    if not title.strip():
        raise RuleError("bad", "Give it a title.")
    if kind not in ISSUE_KINDS:
        raise RuleError("bad", "A fix or an improvement.")
    issue = FftIssue(title=title.strip()[:120], area_id=area_id, origin_try_id=origin_try_id, **({"kind": kind} if kind != "fix" else {}))
    db.add(issue)
    db.flush()
    _event(db, actor, "issue_new", "issue", issue.id, area_id=area_id, origin_try=origin_try_id)
    if feature:
        set_feature(db, actor, issue, feature)
    return issue


def set_kind(db: Session, actor: str, issue: FftIssue, kind: str) -> None:
    """A fix or an improvement (Nov 20), with its event."""
    if kind not in ISSUE_KINDS:
        raise RuleError("bad", "A fix or an improvement.")
    if issue.kind != kind:
        was, issue.kind = issue.kind, kind
        _event(db, actor, "issue_kind", "issue", issue.id, area_id=issue.area_id, was=was, became=kind)  # (never "to": that's a state)


def retitle(db: Session, actor: str, issue: FftIssue, title: str) -> None:
    """A new title, with its event (the page's Rename… and Claude's do=title alike; the review of PR #417)."""
    if not title.strip():
        raise RuleError("bad", "Give it a title.")
    issue.title = title.strip()[:120]
    _event(db, actor, "issue_title", "issue", issue.id, area_id=issue.area_id)


def set_feature(db: Session, actor: str, issue: FftIssue, key: str) -> None:
    """The Feature an issue is about (the Product Taxonomy; Brett, Nov 18). A fix goes into its Product Area's batch;
    one in a Roadmap build's batch stays there. Its checks with no batch yet follow it."""
    f = taxonomy.feature(key)
    if f is None:
        raise RuleError("bad", f"There's no Feature “{key}”: feedback.py features lists them.")
    was = issue.feature
    issue.feature = f.key
    area = db.get(FftArea, issue.area_id) if issue.area_id else None
    if area is None or area.key or area.archived:
        into = taxonomy.batch(db, f.area)
        if issue.area_id != into.id:
            move_issue(db, actor, issue, into.id)
    for c in db.scalars(select(FftCheck).join(FftCheckIssue, FftCheckIssue.check_id == FftCheck.id)
                        .where(FftCheckIssue.issue_id == issue.id, FftCheck.area_id.is_(None))):
        c.area_id = issue.area_id
    _event(db, actor, "issue_feature", "issue", issue.id, area_id=issue.area_id, was=was, feature=f.key)  # (never "to": that's a state)


def move_issue(db: Session, actor: str, issue: FftIssue, area_id: int | None) -> None:
    """R8: moved to another area; its checks are worked out again (check_state reads issues live). A check follows it
    when every issue the check tries is now in that area (The Work Pages, Nov 20: a plan's test round holds its
    issues' checks; check 33 stayed behind its issue 8); one trying issues in other plans too stays where it is."""
    was = issue.area_id
    issue.area_id = area_id
    db.flush()
    for c in db.scalars(select(FftCheck).join(FftCheckIssue, FftCheckIssue.check_id == FftCheck.id)
                        .where(FftCheckIssue.issue_id == issue.id, FftCheck.retired.is_(False))):
        theirs = set(db.scalars(select(FftIssue.area_id).join(FftCheckIssue, FftCheckIssue.issue_id == FftIssue.id).where(FftCheckIssue.check_id == c.id)))
        if c.area_id != area_id and c.area_id in (was, None) and theirs == {area_id}:
            c.area_id = area_id
            _event(db, actor, "check_moved", "check", c.id, area_id=area_id, was=was, issue=issue.id)
    _event(db, actor, "issue_moved", "issue", issue.id, area_id=area_id, was=was)


def start_fixing(db: Session, actor: str, issue: FftIssue) -> None:
    if issue.state != "to_fix":
        raise RuleError("stale", f"It's {issue.state}, not waiting to be fixed.")
    _set_issue(db, actor, issue, "fixing", "issue_fixing")


def fix_ready(db: Session, actor: str, issue: FftIssue, pr: str) -> None:
    """Claude's fix is in a pull request. (R17 retired, Brett's pick 5, Nov 19: approving a player's note is the OK
    for its fix, and its plan's lane decides the testing; nothing waits for a second OK.)"""
    if issue.state not in ("to_fix", "fixing"):
        raise RuleError("stale", f"It's {issue.state}.")
    if not pr.startswith("https://"):
        raise RuleError("bad", "The fix's pull request is an https:// link.")
    issue.pr = pr
    _event(db, actor, "issue_pr", "issue", issue.id, area_id=issue.area_id, pr=pr)


def ok_merge(db: Session, actor: str, issue: FftIssue) -> None:
    """Brett's OK on a player-prompted fix (R17, retired Nov 19: kept for an issue still held from before)."""
    if issue.state != "merge_ok":
        raise RuleError("stale", f"It's {issue.state}, not waiting for your OK.")
    _set_issue(db, actor, issue, "fixing", "issue_merge_okd")


def may_merge(db: Session, issue: FftIssue) -> tuple[bool, str]:
    """R11 and Deploys: may this issue's fix merge to askdnd.ai now? Not while deploys are paused; not while Brett's
    sitting is testing its area (a lighter round, Nov 19: a round holds only its own area, ▶ Try it nothing)."""
    if issue.state == "merge_ok":
        return False, "It waits for Brett's OK to merge (held from before R17 was retired)."
    if frozen(db):
        return False, "Deploys are paused: nothing merges until Brett chooses another (a fix for something broken at the table, with his OK)."
    if issue.area_id:
        held = in_open_round(db, db.get(FftArea, issue.area_id))
    else:  # (in no area: held only by a round over every area)
        r = holding_round(db)
        held = r is not None and r.area_id is None
    if held and not stops_round(db, issue):  # (only its own area: a lighter round, Brett's pick Nov 19)
        return False, "Brett's round is testing this area: it merges when the round ends (only an issue that stops his round may)."
    return True, ""



# ------------------------------------------------------------------ lanes, incidents and the freeze (the work flow, slice 3)

LANES = ("ship", "look", "careful")  # (Brett's picks, Nov 19: how much of his testing a plan needs)
LANE_SAID = {"ship": "Ship", "look": "Look", "careful": "Careful", "": "No lane yet"}
INCIDENT_DAYS = 30
FREEZE = "fft_freeze"  # (a ToolSetting: who turned it on and when, or empty; Brett, Nov 19: a switch, kept by hand)


def lane_of(area: FftArea) -> str:
    """The lane its plan takes: Careful while an incident's 30 days run, whatever was picked."""
    if area.careful_until and area.careful_until > now():
        return "careful"
    return area.lane or ""


def set_lane(db: Session, actor: str, area: FftArea, lane: str, why: str = "", admin: bool = False) -> None:
    """A plan's lane: up by anyone (rules, Claude, Brett), saying why; down only on an admin's word; never below
    Careful while an incident's days run. Kept with who and why, and an event."""
    if lane not in LANES:
        raise RuleError("bad", "Ship, Look or Careful.")
    was = area.lane or ""
    if was and LANES.index(lane) < LANES.index(was) and not admin:
        raise RuleError("bad", f"It's {LANE_SAID[was]}: only Brett moves a plan down a lane.")
    if lane != "careful" and lane_of(area) == "careful" and area.careful_until and area.careful_until > now():
        raise RuleError("bad", f"An incident keeps it Careful until {area.careful_until:%b %-d}.")
    if lane == was:
        return
    area.lane, area.lane_by, area.lane_why = lane, actor[:80], why.strip()[:300]
    _event(db, actor, "area_lane", "area", area.id, area_id=area.id, **{"from": was, "to": lane, "why": area.lane_why})


def incident(db: Session, actor: str, area: FftArea, why: str = "") -> None:
    """It broke at the table (a leak, a broken game night): only that Product Area is Careful for 30 days."""
    area.careful_until = now() + timedelta(days=INCIDENT_DAYS)
    was = area.lane or ""
    area.lane, area.lane_by, area.lane_why = "careful", actor[:80], (why.strip() or "An incident at the table")[:300]
    _event(db, actor, "area_incident", "area", area.id, area_id=area.id, **{"from": was, "until": area.careful_until.isoformat(), "why": area.lane_why})


def freeze_state(db: Session) -> dict:
    """The game-night freeze: {"on": bool, "by": who, "since": iso}."""
    from app.models import ToolSetting

    row = db.get(ToolSetting, FREEZE)
    try:
        data = json.loads(row.value) if row is not None and row.value else {}
    except ValueError:
        data = {}
    return {"on": bool(data), "by": data.get("by", ""), "since": data.get("since", ""), "why": data.get("why", "")}


def frozen(db: Session) -> bool:
    return freeze_state(db)["on"]


def set_freeze(db: Session, actor: str, on: bool, by: str = "", why: str = "") -> None:
    """Brett's switch (Nov 19): on before a game, off after. While it's on, nothing merges and GitHub's tests stop a
    deploy (the Server tests' first step asks /api/fft/freeze); a fix for something broken at the table may go."""
    from app.models import ToolSetting

    if frozen(db) == on:
        return
    row = db.get(ToolSetting, FREEZE) or ToolSetting(key=FREEZE)
    row.value = json.dumps({"by": by or actor, "since": now().isoformat(), "why": why.strip()[:120]}) if on else ""  # (why: Brett, Nov 19, optional)
    db.merge(row)
    _event(db, actor, "freeze_on" if on else "freeze_off", "tool", 0, **({"why": why.strip()[:120]} if on and why.strip() else {}))
    if on and available_state(db)["on"]:  # (game night: nobody is trying things locally; Brett chose it, so no why to show)
        set_available(db, actor, False)


def _set_freeze_why(db: Session, actor: str, why: str) -> None:
    """A new reason for a pause already on (Brett's pick, Nov 19): the bar says it; when it began stays."""
    from app.models import ToolSetting

    row = db.get(ToolSetting, FREEZE)
    data = json.loads(row.value)
    data["why"] = why.strip()[:120]
    row.value = json.dumps(data)
    _event(db, actor, "freeze_why", "tool", 0, why=data["why"])


# ------------------------------------------------------------------ Available (Brett, Nov 19: local tries while he's around)

AVAILABLE = "fft_available"  # (a ToolSetting: {"by", "since", "until"} while on; {"off_at", "why"} after)
AVAILABLE_HOURS = 2  # (his pick: the backstop)
QUIET_MINUTES = 30  # (his pick of three signals: quiet in askdnd, a try unanswered, game night)


def available_state(db: Session) -> dict:
    """{"on", "by", "since", "until", "off_at", "why"}: whether Brett is around to try Look work on his Mac."""
    from app.models import ToolSetting

    row = db.get(ToolSetting, AVAILABLE)
    try:
        data = json.loads(row.value) if row is not None and row.value else {}
    except ValueError:
        data = {}
    return {"on": bool(data.get("since")), "by": data.get("by", ""), "actor": data.get("actor", ""), "since": data.get("since", ""), "until": data.get("until", ""),
            "off_at": data.get("off_at", ""), "why": data.get("why", "")}


def set_available(db: Session, actor: str, on: bool, by: str = "", why: str = "") -> None:
    """Brett's switch. On: Look work waits for his try on his Mac (a local try in For you) until it's off. Off, by
    hand or by itself (`why`): every local try still waiting is left, and merges as Look work does."""
    from app.models import ToolSetting

    st = available_state(db)
    if st["on"] == on:
        return
    row = db.get(ToolSetting, AVAILABLE) or ToolSetting(key=AVAILABLE)
    t = now()
    if on:
        row.value = json.dumps({"by": by or actor, "actor": actor, "since": t.isoformat(), "until": (t + timedelta(hours=AVAILABLE_HOURS)).isoformat()})
    else:
        row.value = json.dumps({"off_at": t.isoformat(), "why": why})
        for lt in db.scalars(select(FftLocalTry).where(FftLocalTry.answer == "")):
            lt.answer, lt.answered_at = "left", t
            _event(db, "askdnd", "local_left", "local", lt.id, area_id=lt.area_id, why=why or "turned off")
    db.merge(row)
    _event(db, actor, "available_on" if on else "available_off", "tool", 0, **({"why": why} if why else {}))


MODES = ("available", "independent", "frozen")  # (Brett, Nov 19: one choice, "Deploys": After my local try, When tests pass, Paused)


def mode_of(db: Session) -> str:
    """How Claude works now: frozen (game night), available (Brett tries visible work on his Mac first), or
    independent (the default: it merges, he tries it after)."""
    return "frozen" if frozen(db) else "available" if available_state(db)["on"] else "independent"


def set_mode(db: Session, actor: str, mode: str, by: str = "", why: str = "") -> None:
    """Brett's one choice. Each mode turns the others off: Frozen ends Available, Available ends the freeze."""
    if mode not in MODES:
        raise RuleError("bad", "After my local try, When tests pass, or Paused.")
    if mode == "frozen":
        if frozen(db):  # (paused again: only its reason changes, and it stays paused since when it was)
            _set_freeze_why(db, actor, why)
        else:
            set_freeze(db, actor, True, by=by, why=why)  # (it ends local tries)
    else:
        set_freeze(db, actor, False)
        set_available(db, actor, mode == "available", by=by)


def check_available(db: Session, last_seen: datetime | None = None) -> dict:
    """Turns Available off by itself (Brett, Nov 19: "smarter … the duration can be the back stop"): quiet in askdnd for
    30 minutes, a local try unanswered for 30 minutes, or the 2 hours are up. Read wherever it's shown or asked."""
    st = available_state(db)
    if not st["on"]:
        return st
    t = now()
    quiet = timedelta(minutes=QUIET_MINUTES)
    since = datetime.fromisoformat(st["since"])
    acted = db.scalar(select(func.max(FftEvent.at)).where(FftEvent.actor == st["actor"])) if st["actor"] else None  # (his own presses)
    if last_seen is None and st["actor"].startswith("user:") and st["actor"][5:].isdigit():  # (his pages: the gear's count marks them)
        from app.models import User

        u = db.get(User, int(st["actor"][5:]))
        last_seen = u.last_seen_at if u is not None else None
    seen = max([x for x in (last_seen, acted, since) if x is not None])
    waiting = db.scalar(select(func.min(FftLocalTry.created_at)).where(FftLocalTry.answer == ""))
    why = ("the 2 hours are up" if t >= datetime.fromisoformat(st["until"]) else
           "a try waited 30 minutes" if waiting is not None and t - waiting >= quiet else
           "quiet for 30 minutes" if t - seen >= quiet else "")
    if why:
        set_available(db, "askdnd", False, why=why)
    return available_state(db)


def new_local_try(db: Session, actor: str, title: str, area: FftArea | None, changed: list[str], look_at: str, path: str,
                  pr: str = "") -> FftLocalTry:
    """Claude's change, waiting for Brett's try on his Mac. Only while he's Available."""
    if not available_state(db)["on"]:
        raise RuleError("bad", "Deploys aren't set to After my local try: Look work merges, and Brett tries it after it's live.")
    if not title.strip() or not changed:
        raise RuleError("bad", "Say what it is and what changed.")
    if not path.startswith("/"):
        raise RuleError("bad", "The page to open is a path on askdnd, like /party.")
    lt = FftLocalTry(title=title.strip()[:120], area_id=area.id if area else None, changed=[c.strip()[:300] for c in changed if c.strip()][:8],
                     look_at=look_at.strip()[:1000], path=path[:300], pr=pr[:300])
    db.add(lt)
    db.flush()
    _event(db, actor, "local_new", "local", lt.id, area_id=lt.area_id)
    return lt


def answer_local_try(db: Session, actor: str, lt: FftLocalTry, answer: str, words: str = "") -> None:
    """Looks good (it may merge) or Something's off (his words go to Claude; it goes back to its plan)."""
    if lt.answer:
        raise RuleError("stale", "It's been answered already.")
    if answer not in ("good", "off"):
        raise RuleError("bad", "Looks good, or something's off.")
    if answer == "off" and not words.strip():
        raise RuleError("bad", "Say what's off.")
    lt.answer, lt.words, lt.answered_at = answer, words.strip()[:4000], now()
    _event(db, actor, "local_" + answer, "local", lt.id, area_id=lt.area_id, **({"words": lt.words} if lt.words else {}))


def wait_for_deploy(db: Session, actor: str, check: FftCheck, pr: str) -> None:
    """The check reaches For you only once a deploy carrying this pull request is live (Brett, Nov 20)."""
    if not pr.strip():
        raise RuleError("bad", "Which pull request is its change in?")
    db.add(FftCheckWait(check_id=check.id, pr=pr.strip()[:300]))
    _event(db, actor, "check_waits", "check", check.id, area_id=check.area_id, pr=pr.strip()[:300])


def deployed(db: Session, actor: str, prs: list[str]) -> list[int]:
    """A deploy is live with these pull requests: the checks waiting for them are let through (to For you)."""
    out = []
    for w in db.scalars(select(FftCheckWait).where(FftCheckWait.pr.in_(prs))):
        out.append(w.check_id)
        db.delete(w)
        _event(db, actor, "check_deployed", "check", w.check_id, pr=w.pr)
    return out


def fix_live(db: Session, actor: str, issue: FftIssue, commit: str) -> None:
    """R4: merged and live: ready to try. A player who reported it confirms it (R5)."""
    if issue.state not in ("fixing", "to_fix"):
        raise RuleError("stale", f"It's {issue.state}.")
    issue.fixed_in = commit[:40]
    reporter = db.scalar(select(FftNote.user_id).where(FftNote.issue_id == issue.id, FftNote.role != "admin", FftNote.user_id.isnot(None)))
    if reporter:
        issue.confirm_by, issue.confirm_since = reporter, now()
    _set_issue(db, actor, issue, "ready", "issue_live", commit=commit)
    db.flush()
    _after_live(db, actor)  # (Brett's round, if it waited for this to go live)


def rollback(db: Session, actor: str, commit: str) -> list[int]:
    """R9: a fix rolled back: its issues are Claude's again; checks waiting on them leave To try."""
    back = list(db.scalars(select(FftIssue).where(FftIssue.fixed_in == commit, FftIssue.state == "ready")))
    for issue in back:
        issue.fixed_in, issue.confirm_by, issue.confirm_since = "", None, None
        _set_issue(db, actor, issue, "fixing", "issue_rolled_back", commit=commit)
    return [i.id for i in back]


def _relink(db: Session, issue: FftIssue, to: FftIssue) -> None:
    """Every check and try that named `issue` names `to` instead (Same as)."""
    for ci in list(db.scalars(select(FftCheckIssue).where(FftCheckIssue.issue_id == issue.id))):
        if db.get(FftCheckIssue, (ci.check_id, to.id)) is None:
            db.add(FftCheckIssue(check_id=ci.check_id, issue_id=to.id))
        db.delete(ci)
    for ti in list(db.scalars(select(FftTryIssue).where(FftTryIssue.issue_id == issue.id))):
        if db.get(FftTryIssue, (ti.try_id, to.id)) is None:
            db.add(FftTryIssue(try_id=ti.try_id, issue_id=to.id, blocking=ti.blocking, how=ti.how, stops_round=ti.stops_round))
        db.delete(ti)
    db.flush()


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
        if issue.from_player and not same_as.from_player:  # (a player's words now share it; R17 retired, nothing held)
            same_as.from_player = True
        for note in db.scalars(select(FftNote).where(FftNote.issue_id == issue.id)):
            note.issue_id = same_as.id
        _relink(db, issue, same_as)  # (R8: a check this one held is now held by the other, never released early)
    issue.close_reason, issue.close_words = reason, words.strip()
    _set_issue(db, actor, issue, "closed", "issue_closed", reason=reason)


def reopen(db: Session, actor: str, issue: FftIssue, by_try: int | None = None) -> None:
    """A closed issue came back: Claude's to fix again, and it says so (`by_try`: the try that saw it again, so a
    correction of that try puts back only what it changed)."""
    if issue.state != "closed":
        raise RuleError("stale", "It isn't closed.")
    issue.reopened += 1
    issue.close_reason = issue.close_words = ""
    issue.fixed_in, issue.confirm_by, issue.confirm_since = "", None, None
    _set_issue(db, actor, issue, "to_fix", "issue_reopened", **({"by_try": by_try} if by_try else {}))


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


IDEA_STATES = ("new", "roadmap", "shipped", "declined")


def idea_state(db: Session, actor: str, idea: FftIdea, to: str, words: str = "") -> None:
    """An idea taken onto the Roadmap, built, back to new, or declined with why (its senders read it)."""
    if to not in IDEA_STATES:
        raise RuleError("bad", "On the Roadmap, built, back to new, or declined.")
    was, idea.state = idea.state, to
    if to == "declined":
        idea.reason = words.strip()[:500]
    _event(db, actor, "idea_" + to, "idea", idea.id, **{"from": was, "to": to})


def new_area(db: Session, actor: str, item: FftItem, title: str) -> FftArea:
    """A Roadmap build's own batch (fixes are batched by Product Area: taxonomy.batch)."""
    if item.standing:
        raise RuleError("bad", "Fixes are batched by Product Area: give each issue its Feature (do: feature).")
    if not title.strip():
        raise RuleError("bad", "Give it a title.")
    place = (db.scalar(select(func.max(FftArea.place)).where(FftArea.item_id == item.id)) or 0) + 1
    a = FftArea(item_id=item.id, title=title.strip()[:80], place=place)
    db.add(a)
    db.flush()
    _event(db, actor, "area_new", "area", a.id, area_id=a.id, item=item.id)
    return a


def new_item(db: Session, actor: str, title: str, section: str = "next", standing: bool = False) -> FftItem:
    if section not in ("now", "next", "later"):
        raise RuleError("bad", "section: now, next or later")
    if not title.strip():
        raise RuleError("bad", "Give it a title.")
    it = FftItem(title=title.strip()[:120], section=section, standing=standing, place=(db.scalar(select(func.max(FftItem.place))) or 0) + 1)
    db.add(it)
    db.flush()
    _event(db, actor, "item_new", "item", it.id)
    return it


def item_next(db: Session, actor: str, item: FftItem, step: str, whose: str) -> None:
    """A Roadmap item's next step and whose it is."""
    if whose not in ("brett", "claude", ""):
        raise RuleError("bad", 'whose: "brett", "claude" or ""')
    item.next_step, item.next_whose = step[:200], whose
    _event(db, actor, "item_next", "item", item.id, whose=whose)


# ------------------------------------------------------------------ the Roadmap (Brett's picks, Nov 20, docs/mockups/roadmap-in-askdnd/)
#
# An idea that needs discussion is a Roadmap item: its scope is worked out as versions (Claude writes each, saying what
# changed), Brett's additions are kept on it in his words with Claude's answer, he gives one OK (Scope looks right), and
# its steps, each his or Claude's, carry it out; the plans building it are its areas, in Development. Done (shipped,
# not doing) leaves the list for its History.

ROADMAP_SECTIONS = ("now", "next", "later", "paused")  # (what's open, in this order; shipped and not_doing are History)
SIZES = ("", "S", "M", "L")
ANSWERS = ("in", "later", "question")


def item_rank():
    """The one order: Now, Next, Later, then the rest; Brett's drag within each (R15 and Development follow it)."""
    from sqlalchemy import case

    return case((FftItem.section == "now", 0), (FftItem.section == "next", 1), (FftItem.section == "later", 2), else_=3)


def new_idea(db: Session, actor: str, title: str, words: str = "", section: str = "next", where: str = "askdnd",
             user_id: int | None = None) -> FftItem:
    """A Roadmap idea: an item with no scope yet, its first addition the idea in its maker's words."""
    if section not in ("now", "next", "later"):
        raise RuleError("bad", "Now, Next or Later.")
    it = new_item(db, actor, title, section)
    if words.strip():
        add_to_item(db, actor, it, words, where=where, user_id=user_id)
    return it


def set_item(db: Session, actor: str, item: FftItem, *, title: str | None = None, why: str | None = None,
             size: str | None = None, status: str | None = None) -> None:
    """A Roadmap item's title, why it matters, size (S, M, L) or status line."""
    if title is not None:
        if not title.strip():
            raise RuleError("bad", "Give it a title.")
        item.title = title.strip()[:120]
    if why is not None:
        item.why = why.strip()[:2000]
    if size is not None:
        if size not in SIZES:
            raise RuleError("bad", "S, M or L.")
        item.size = size
    if status is not None:
        item.status = status.strip()[:200]
    _event(db, actor, "item_set", "item", item.id, **{k: True for k, v in (("title", title), ("why", why), ("size", size), ("status", status)) if v is not None})


def move_item(db: Session, actor: str, item: FftItem, section: str) -> None:
    """Now, Next, Later or Paused (a shipped item comes back with this too: Reopen)."""
    if section not in ROADMAP_SECTIONS:
        raise RuleError("bad", "Now, Next, Later or Paused.")
    if item.standing:
        raise RuleError("bad", "Fixes and polish stays where it is.")
    was, item.section = item.section, section
    if section != "shipped":
        item.shipped_at = None
    _event(db, actor, "item_moved", "item", item.id, was=was, section=section)


def ship_item(db: Session, actor: str, item: FftItem, not_doing: bool = False) -> None:
    """Shipped (or Not doing): off the list, into its History, with the day."""
    if item.standing:
        raise RuleError("bad", "Fixes and polish never ships.")
    item.section, item.shipped_at = ("not_doing" if not_doing else "shipped"), now()
    _event(db, actor, "item_not_doing" if not_doing else "item_shipped", "item", item.id)


def add_to_item(db: Session, actor: str, item: FftItem, words: str, where: str = "askdnd", user_id: int | None = None) -> FftAddition:
    """Brett's addition, in his words: said in chat (Claude writes it down, `where="chat"`) or added in askdnd. It
    reaches Claude's inbox; Claude answers it on the item and writes the scope's next version."""
    if not words.strip():
        raise RuleError("bad", "Say what to add.")
    if where not in ("askdnd", "chat"):
        raise RuleError("bad", "In askdnd, or in chat.")
    a = FftAddition(item_id=item.id, words=words.strip()[:8000], where=where, user_id=user_id)
    db.add(a)
    db.flush()
    _event(db, actor, "item_addition", "item", item.id, addition=a.id, where=where)
    return a


def answer_addition(db: Session, actor: str, addition: FftAddition, answer: str, words: str = "", scope_version: int | None = None) -> None:
    """Claude's answer to an addition: in scope (in which version), later, or a question back."""
    if answer not in ANSWERS:
        raise RuleError("bad", "In scope, later, or a question.")
    addition.answer, addition.answer_words, addition.scope_version = answer, words.strip()[:2000], scope_version
    _event(db, actor, "item_answered", "item", addition.item_id, addition=addition.id, answer=answer)


def latest_scope(db: Session, item: FftItem) -> FftScope | None:
    return db.scalar(select(FftScope).where(FftScope.item_id == item.id).order_by(FftScope.version.desc()))


def write_scope(db: Session, actor: str, item: FftItem, *, what: str, inside: list[str], not_now: list[str] | None = None,
                questions: list[str] | None = None, changed: str = "") -> FftScope:
    """The scope's next version: what it is, what's in, what's not now, open questions, and what changed. Brett's OK
    is on a version: a new one waits for it again."""
    if not what.strip() or not [x for x in inside if x.strip()]:
        raise RuleError("bad", "Say what it is and what's in.")
    last = latest_scope(db, item)
    sc = FftScope(item_id=item.id, version=(last.version + 1) if last else 1, what=what.strip()[:4000],
                  inside=[x.strip()[:400] for x in inside if x.strip()], not_now=[x.strip()[:400] for x in (not_now or []) if x.strip()],
                  questions=[x.strip()[:400] for x in (questions or []) if x.strip()], changed=changed.strip()[:2000], actor=actor)
    db.add(sc)
    db.flush()
    _event(db, actor, "item_scope", "item", item.id, version=sc.version)
    return sc


def agree_scope(db: Session, actor: str, item: FftItem, user_id: int | None = None, seen: int | None = None) -> FftScope:
    """Scope looks right: Brett's one OK, on the version he read (R14: a newer one written meanwhile is refused)."""
    sc = latest_scope(db, item)
    if sc is None:
        raise RuleError("bad", "There's no scope yet.")
    if seen is not None and sc.version != seen:
        raise RuleError("stale", f"Claude wrote version {sc.version} while you were reading: read it first.")
    if sc.agreed_at is None:
        sc.agreed_at, sc.agreed_by = now(), user_id
        _event(db, actor, "item_agreed", "item", item.id, version=sc.version)
    return sc


def _next_from_steps(db: Session, item: FftItem) -> None:
    """The item's next step is its first not done (R15 skips an item whose next step is Brett's)."""
    first = db.scalar(select(FftStep).where(FftStep.item_id == item.id, FftStep.done_at.is_(None)).order_by(FftStep.place, FftStep.id))
    item.next_step, item.next_whose = (first.text, first.whose) if first else ("", "")


def add_step(db: Session, actor: str, item: FftItem, text: str, whose: str = "claude") -> FftStep:
    if whose not in ("brett", "claude"):
        raise RuleError("bad", "Brett's or Claude's.")
    if not text.strip():
        raise RuleError("bad", "Say what the step is.")
    place = (db.scalar(select(func.max(FftStep.place)).where(FftStep.item_id == item.id)) or 0) + 1
    st = FftStep(item_id=item.id, text=text.strip()[:200], whose=whose, place=place)
    db.add(st)
    db.flush()
    _next_from_steps(db, item)
    _event(db, actor, "item_step", "item", item.id, step=st.id, whose=whose)
    return st


def tick_step(db: Session, actor: str, step: FftStep, done: bool = True) -> None:
    item = db.get(FftItem, step.item_id)
    step.done_at = now() if done else None
    db.flush()
    _next_from_steps(db, item)
    _event(db, actor, "item_step_done" if done else "item_step_open", "item", item.id, step=step.id)


def remove_step(db: Session, actor: str, step: FftStep) -> None:
    item = db.get(FftItem, step.item_id)
    db.delete(step)
    db.flush()
    _next_from_steps(db, item)
    _event(db, actor, "item_step_removed", "item", item.id)


def file_roadmap_idea(db: Session, actor: str, note: FftNote, title: str = "") -> FftItem:
    """A note that needs discussion becomes a Roadmap idea (Brett, Nov 20: the second type of work). Its idea record
    keeps the note's senders tied to the item, so they hear when it ships."""
    idea = file_idea(db, actor, note)
    it = new_idea(db, actor, title or idea.title, note.text, where="askdnd")
    idea.item_id, idea.state = it.id, "roadmap"
    return it


def idea_to_roadmap(db: Session, actor: str, idea: FftIdea) -> FftItem:
    """An idea from before the Roadmap was in askdnd, made a Roadmap idea (its notes' words its first additions)."""
    if idea.item_id:
        return db.get(FftItem, idea.item_id)
    notes = list(db.scalars(select(FftNote).where(FftNote.idea_id == idea.id).order_by(FftNote.id)))
    it = new_idea(db, actor, idea.title, notes[0].text if notes else "")
    idea.item_id, idea.state = it.id, "roadmap"
    _event(db, actor, "idea_roadmap", "idea", idea.id, item=it.id)
    return it


def idea_to_issue(db: Session, actor: str, idea: FftIdea, kind: str = "improvement") -> FftIssue:
    """An idea that's really a change to a Product Area: an issue (an improvement, as a rule) its notes now belong to."""
    issue = new_issue(db, actor, idea.title, kind=kind)
    for n in db.scalars(select(FftNote).where(FftNote.idea_id == idea.id)):
        n.filed_as, n.issue_id, n.idea_id = "issue", issue.id, None
        issue.from_player = issue.from_player or n.role != "admin"
    idea.state, idea.reason = "declined", f"Now issue {issue.id}"
    _event(db, actor, "idea_issue", "idea", idea.id, issue=issue.id)
    return issue


def test_campaign_of(db: Session, path: str) -> str:
    """The test campaign a check's page is in (its name), or "": `/c/<slug>/…`, or a character in one."""
    import re

    from app.models import Campaign, CampaignCharacter

    m = re.match(r"^/c/([^/?#]+)", path or "")
    if m:
        camp = db.scalar(select(Campaign).where(Campaign.slug == m.group(1)))
        return camp.name if camp is not None and camp.is_test else ""
    m = re.match(r"^/characters/(\d+)", path or "")
    if m:
        camp = db.scalar(select(Campaign).join(CampaignCharacter, CampaignCharacter.campaign_id == Campaign.id)
                         .where(CampaignCharacter.character_id == int(m.group(1)), CampaignCharacter.left_on.is_(None), Campaign.is_test.is_(True)))
        return camp.name if camp is not None else ""
    return ""


def write_check(db: Session, actor: str, *, title: str, steps: list[str], expect: str, path: str = "", why: str = "",
                area_id: int | None = None, devices: list[str] | None = None, issue_ids: list[int] | None = None,
                minutes: int = 2, makes: bool = False, as_character: int | None = None) -> FftCheck:
    """A check: what to try, version 1. One that `makes` something runs in a test campaign, never the table's
    (docs/testing-guide.md; the old tool refused it, and the review of PR #417 found the new one didn't).
    `as_character`: tried through that character's player's eyes (View as)."""
    if not title.strip() or not steps:
        raise RuleError("bad", "A check needs its title and steps.")
    if makes and not test_campaign_of(db, path):
        raise RuleError("bad", "A check that makes something runs in a test campaign: give it a page in one (/c/<test campaign>/…).")
    devices = [d for d in (devices or ["laptop"]) if d in DEVICES] or ["laptop"]
    if area_id is None and issue_ids:  # (a check is tried with the batch its issues are in)
        area_id = db.scalar(select(FftIssue.area_id).where(FftIssue.id.in_(issue_ids), FftIssue.area_id.is_not(None)).order_by(FftIssue.id))
    check = FftCheck(title=title.strip()[:160], area_id=area_id, devices=devices, minutes=max(1, min(60, minutes)), makes=makes,
                     as_character=as_character)
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
    if check.makes and not test_campaign_of(db, path):
        raise RuleError("bad", "A check that makes something runs in a test campaign: give it a page in one (/c/<test campaign>/…).")
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


def restore(db: Session, actor: str, check: FftCheck, why: str) -> None:
    """A check retired by mistake, back as it was (its versions and tries untouched)."""
    if not check.retired:
        raise RuleError("stale", "It isn't retired.")
    if not why.strip():
        raise RuleError("bad", "Say why it's back.")
    check.retired = False
    _event(db, actor, "check_restored", "check", check.id, area_id=check.area_id, why=why[:300])


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


# ------------------------------------------------------------------ what check_state reads, loaded once (Nov 20)
#
# A page asks where many checks stand (For you, Development, a plan, the counts on every Backstage page), and each used
# to read its own links, tries and issues: 150 to 500 small queries a page, about a second on askdnd.ai where each query
# crosses Railway's network. Now the first ask in a request reads them all in four queries and keeps them on the
# session (`db.info`); any change drops them (a flush, a commit or rollback, an UPDATE or DELETE run on the session),
# and pending changes are flushed first, as autoflush would, so nothing is ever read stale.

FACTS = "fft_check_facts"


def _facts(db: Session) -> dict:
    if db.new or db.dirty or db.deleted:
        db.flush()
    f = db.info.get(FACTS)
    if f is not None:
        return f
    links: dict[int, set[int]] = {}
    for c, i in db.execute(select(FftCheckIssue.check_id, FftCheckIssue.issue_id)):
        links.setdefault(c, set()).add(i)
    last: dict[tuple, FftTry] = {}
    by_check: dict[int, list[FftTry]] = {}
    for t in db.scalars(select(FftTry).where(FftTry.replaced.is_(False)).order_by(FftTry.id)):
        last[(t.check_id, t.device, t.actor)] = t
        by_check.setdefault(t.check_id, []).append(t)
    named: dict[int, list[tuple[int, bool]]] = {}  # (a live try's id → the issues it named, and whether each blocks)
    for t_id, i, b in db.execute(select(FftTryIssue.try_id, FftTryIssue.issue_id, FftTryIssue.blocking)
                                 .join(FftTry, FftTry.id == FftTryIssue.try_id).where(FftTry.replaced.is_(False))):
        named.setdefault(t_id, []).append((i, b))
    issues = {i.id: i for i in db.scalars(select(FftIssue))}
    versions = {(v.check_id, v.version): v for v in db.scalars(select(FftCheckVersion))}
    waiting = set(db.scalars(select(FftCheckWait.check_id)))
    f = {"waiting": waiting, "links": links, "last": last, "by_check": by_check, "named": named, "issues": issues, "versions": versions, "memo": {}}
    db.info[FACTS] = f
    return f


def check_issues(db: Session, check: FftCheck) -> list[FftIssue]:
    """The issues a check tries the fix of, oldest first (from the request's facts: no query per check)."""
    f = _facts(db)
    return [f["issues"][i] for i in sorted(f["links"].get(check.id, ())) if i in f["issues"]]


def check_version(db: Session, check: FftCheck) -> FftCheckVersion | None:
    return _facts(db)["versions"].get((check.id, check.version))


def _memo(db: Session, key: str, make):
    """A value worked out once per request until anything changes (kept with the facts, dropped with them)."""
    m = _facts(db)["memo"]
    if key not in m:
        m[key] = make()
    return m[key]


def _forget(session, *_) -> None:
    session.info.pop(FACTS, None)


for _when in ("after_flush", "after_commit", "after_soft_rollback"):
    event.listen(Session, _when, _forget)


@event.listens_for(Session, "do_orm_execute")
def _forget_on_write(state) -> None:
    if not state.is_select:  # (an UPDATE, DELETE or INSERT run on the session, not through the ORM's flush)
        state.session.info.pop(FACTS, None)


def _blocking_issues(db: Session, check: FftCheck) -> list[FftIssue]:
    """The issues that hold a check: those it tries the fix of, and those a live try named as stopping it."""
    f = _facts(db)
    linked = f["links"].get(check.id, set())
    named = [x for t in f["by_check"].get(check.id, []) for x in f["named"].get(t.id, [])]
    nonblocking = {i for i, b in named if not b}
    ids = (linked | {i for i, b in named if b}) - (nonblocking - linked)
    return sorted((f["issues"][i] for i in ids if i in f["issues"]), key=lambda i: i.id)


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


def still_happening(db: Session, actor: str, issue: FftIssue, check: FftCheck | None = None, by_try: int | None = None) -> None:
    """A fixed issue seen again: Claude's to fix (a closed one reopens, saying it came back). `by_try`: the try that saw
    it, kept on the event so correcting that try undoes only this (the review of PR #417)."""
    if issue.state == "closed":
        reopen(db, actor, issue, by_try=by_try)
    elif issue.state in ("ready", "merge_ok", "fixing"):
        issue.fixed_in, issue.confirm_by, issue.confirm_since = "", None, None
        _set_issue(db, actor, issue, "to_fix", "issue_still_happening", check=check.id if check else None,
                   **({"by_try": by_try} if by_try else {}))


def _name_issue(db: Session, actor: str, check: FftCheck, t: FftTry, f: Found) -> FftIssue:
    if f.issue_id:
        issue = db.get(FftIssue, f.issue_id)
        how = "still"
        still_happening(db, actor, issue, check, by_try=t.id)
    else:
        known = db.scalar(select(FftIssue.feature).join(FftCheckIssue, FftCheckIssue.issue_id == FftIssue.id)
                          .where(FftCheckIssue.check_id == check.id, FftIssue.feature != "").order_by(FftIssue.id))
        issue = new_issue(db, actor, f.title, area_id=check.area_id, origin_try_id=t.id, feature=known or "")  # (what its check tries)
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


def _untried_anywhere(db: Session, issue: FftIssue) -> bool:
    """Does a check of this issue still wait for a person on one of its devices (the Mac Mini's runs confirm nothing)?"""
    for c in db.scalars(select(FftCheck).join(FftCheckIssue, FftCheckIssue.check_id == FftCheck.id)
                        .where(FftCheckIssue.issue_id == issue.id, FftCheck.retired.is_(False))):
        if any(state != "passed" for dev, state in check_state(db, c)["devices"].items() if dev != "mac_mini"):
            return True
    return False


def back_to_ready(db: Session, actor: str, issue: FftIssue) -> None:
    """An issue closed as working while a check of it still waited for a device: back to ready to try (the rule above
    keeps it from happening again)."""
    if issue.state != "closed" or issue.close_reason != "works" or not _untried_anywhere(db, issue):
        raise RuleError("stale", "It's not one closed early.")
    issue.close_reason = ""
    _set_issue(db, actor, issue, "ready", "issue_live", again="a device left to try")


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
    """R5: only blocking issues, fixed and live, with no failing try left elsewhere and every device each of their checks
    needs passed, close: works now (or wait for the player who reported it). An automated pass confirms nothing (R16).
    (Brett's round, Nov 18: a laptop pass closed issues whose checks still waited for the iPhone.)"""
    if actor == "mini":
        return
    for issue in _blocking_issues(db, check):
        if issue.state != "ready" or _failing_elsewhere(db, issue, check, t.device) or _untried_anywhere(db, issue):
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
            # (withdrawn, or kept for its other uses: either way this check no longer holds it, R6)
            db.execute(FftCheckIssue.__table__.delete().where(FftCheckIssue.check_id == check.id, FftCheckIssue.issue_id == issue.id))
        elif ti.how == "still" and issue.state == "to_fix":
            # (only what this try changed goes back: an issue already to fix when it was named stays to fix)
            prior = db.scalar(select(FftEvent.data).where(FftEvent.thing == "issue", FftEvent.thing_id == issue.id,
                                                          FftEvent.kind.in_(("issue_still_happening", "issue_reopened")),
                                                          FftEvent.data["by_try"].as_integer() == t.id).order_by(FftEvent.id.desc()))
            back = (prior or {}).get("from")
            if back in ISSUE_STATES and back != "to_fix":
                if back == "closed":
                    issue.close_reason = "works"
                _set_issue(db, actor, issue, back, "issue_unmarked", by_correction=new.id)
    if t.result == "passed":  # (a pass undone: what it closed as working is ready to try again, R5 and R6)
        for ev in db.scalars(select(FftEvent).where(FftEvent.kind == "issue_closed", FftEvent.thing == "issue",
                                                    FftEvent.data["by_try"].as_integer() == t.id)):
            issue = db.get(FftIssue, ev.thing_id)
            if issue is not None and issue.state == "closed" and issue.close_reason == "works":
                issue.close_reason = ""
                _set_issue(db, actor, issue, "ready", "issue_unmarked", by_correction=new.id)
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
    f = _facts(db)
    for dev in check.devices or ["laptop"]:
        last = f["last"].get((check.id, dev, "mini" if dev == "mac_mini" else "person"))
        if last is None or last.result == "untried":
            devices[dev] = "fixing" if open_claude else "to_try"
        elif last.result == "failed":
            named = {i for i, b in f["named"].get(last.id, []) if b}
            still = [i for i in blocking if i.id in named and i.state != "ready" and i.state != "closed"]
            devices[dev] = "failed" if still or open_claude else "to_try"
            again = again or devices[dev] == "to_try"
        elif last.result == "passed":
            devices[dev] = "fixing" if open_claude else "passed"
        elif last.cant_kind == "blocked":
            b = f["issues"].get(last.blocked_by) if last.blocked_by else None
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
    if turn == "brett" and check.id in f["waiting"]:  # (its change isn't live yet: it waits for its deploy, Nov 20)
        state, turn = "deploying", "claude"
    return {"state": state, "turn": turn, "devices": devices, "again": again}


# ------------------------------------------------------------------ rounds, areas, the one order (R11, R12, R15)


def open_round(db: Session, actor: str, user_id: int | None, area_id: int | None = None, holds: bool = True) -> FftRound:
    """A sitting of tries. `holds` (a lighter round, Brett's pick Nov 19): ▶ Start round holds Claude's merges in its
    own area(s); ▶ Try it on one check opens one that holds nothing. A round already open is kept as it is."""
    _expire_rounds(db)
    r = db.scalar(select(FftRound).where(FftRound.ended_at.is_(None), FftRound.user_id == user_id))
    if r is None:
        r = FftRound(user_id=user_id, area_id=area_id, holds=holds)
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
    if area.lock_owner and area.lock_owner != owner[:60] and area.lock_until and area.lock_until > now():
        raise RuleError("busy", f"It's already in hand ({area.lock_owner}).")
    area.lock_owner, area.lock_until = owner[:60], now() + LOCK
    _event(db, owner, "area_locked", "area", area.id, area_id=area.id)


def unlock_area(db: Session, owner: str, area: FftArea) -> None:
    if area.lock_owner and area.lock_owner != owner[:60] and area.lock_until and area.lock_until > now():
        raise RuleError("busy", f"It's in someone else's hand ({area.lock_owner}).")
    area.lock_owner, area.lock_until = "", None
    _event(db, owner, "area_unlocked", "area", area.id, area_id=area.id)


def order_items(db: Session, actor: str, ids: list[int]) -> None:
    """Brett's one order: the Roadmap's items, top first (dragged on Development's Queue, which lists only those with plans:
    the items dragged come first in their new order, the rest keep theirs after them)."""
    rows = {it.id: it for it in db.scalars(select(FftItem))}
    moved = [x for x in dict.fromkeys(ids) if x in rows]
    rest = [it.id for it in sorted(rows.values(), key=lambda it: (it.place, it.id)) if it.id not in moved]
    for n, i in enumerate(moved + rest):
        rows[i].place = n + 1
    _event(db, actor, "items_ordered", "item", 0, order=[x for x in ids if x in rows])


def order_areas(db: Session, actor: str, item: FftItem, ids: list[int]) -> None:
    """An item's areas in Brett's order; Claude takes the first that's its turn (R15)."""
    rows = {a.id: a for a in db.scalars(select(FftArea).where(FftArea.item_id == item.id))}
    for n, i in enumerate(x for x in ids if x in rows):
        rows[i].place = n + 1
    _event(db, actor, "areas_ordered", "item", item.id, order=[x for x in ids if x in rows])


def _hand_made(area: FftArea) -> None:
    if area.key:
        raise RuleError("bad", "A Product Area's batch follows the list (app/data/taxonomy.json): change it there.")


def rename_area(db: Session, actor: str, area: FftArea, title: str) -> None:
    _hand_made(area)
    if not title.strip():
        raise RuleError("bad", "Give it a name.")
    was, area.title = area.title, title.strip()[:80]
    _event(db, actor, "area_renamed", "area", area.id, area_id=area.id, was=was)


def move_area(db: Session, actor: str, area: FftArea, item: FftItem) -> None:
    """To another Roadmap item, at its end."""
    _hand_made(area)
    was, area.item_id = area.item_id, item.id
    area.place = (db.scalar(select(func.max(FftArea.place)).where(FftArea.item_id == item.id, FftArea.id != area.id)) or 0) + 1
    _event(db, actor, "area_moved", "area", area.id, area_id=area.id, **{"from": was, "to": item.id})


def merge_area(db: Session, actor: str, area: FftArea, into: FftArea) -> None:
    """Its issues and checks join another area; it's archived (kept, so its history reads)."""
    _hand_made(area)
    if into.id == area.id or into.archived:
        raise RuleError("bad", "Merge it into another open area.")
    for i in db.scalars(select(FftIssue).where(FftIssue.area_id == area.id)):
        i.area_id = into.id
    for c in db.scalars(select(FftCheck).where(FftCheck.area_id == area.id)):
        c.area_id = into.id
    area.archived, area.lock_owner, area.lock_until = True, "", None
    _event(db, actor, "area_merged", "area", area.id, area_id=into.id, into=into.id)


def hold_area(db: Session, actor: str, area: FftArea, held: bool) -> None:
    """Below Work's cut line, or back above it (The Work Pages, Nov 20): Claude takes only the plans above the line."""
    if area.held == held:
        return
    area.held = held
    _event(db, actor, "area_held" if held else "area_let_go", "area", area.id, area_id=area.id)


def archive_area(db: Session, actor: str, area: FftArea) -> None:
    """Out of the list; only once nothing in it is open (an empty area drops off by itself)."""
    _hand_made(area)
    if area_open_issues(db, area) or any(check_state(db, c)["turn"] != "closed" for c in area_checks(db, area)):
        raise RuleError("bad", "It still has open issues or checks: move or merge them first.")
    area.archived, area.lock_owner, area.lock_until = True, "", None
    _event(db, actor, "area_archived", "area", area.id, area_id=area.id)


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
    if any(i.state in ("to_fix", "fixing") for i in issues) or any(s in ("failed", "fixing", "wrong", "blocked", "preflight") for s in states):
        return "claude"
    if any(i.state in ("asks", "merge_ok", "ready") for i in issues) or any(s in ("to_try", "later", "asks") for s in states):
        return "brett"
    return "done"


def holding_round(db: Session) -> FftRound | None:
    """The open round that holds Claude's merges, if any (▶ Try it's never does: a lighter round, Nov 19)."""
    _expire_rounds(db)
    return _memo(db, "holding_round", lambda: db.scalar(select(FftRound).where(FftRound.ended_at.is_(None), FftRound.holds.is_(True)).order_by(FftRound.id.desc())))


# ------------------------------------------------------------------ the heads-up before holding (a lighter round, item 3)

AFTER = "fft_round_after"  # (a ToolSetting: {"user_id", "area_id", "prs", "since"}: Brett's round waits for these to go live)


def round_areas(db: Session, area_id: int | None = None) -> set[int]:
    """The areas a round would hold: ▶ Just this area, that one; ▶ Start round, every area with a check in his turn."""
    if area_id:
        return {area_id}
    return {a.id for a in db.scalars(select(FftArea).where(FftArea.archived.is_(False)))
            if any(check_state(db, c)["turn"] == "brett" for c in area_checks(db, a))}


def in_flight(db: Session, area_ids: set[int] | None = None, whole: bool = False) -> list[dict]:
    """Claude's changes about to go live (Brett, Nov 19: "maybe it warns when I am going to be stopping something"):
    issues being fixed whose pull request is attached and not yet live, one entry per pull request. `area_ids` keeps
    those areas' (None: every one); `whole` adds the issues in no area, which a round over every area holds too."""
    out: dict[str, dict] = {}
    for i in db.scalars(select(FftIssue).where(FftIssue.state == "fixing", FftIssue.pr != "").order_by(FftIssue.id)):
        if area_ids is not None and not (i.area_id in area_ids or (whole and i.area_id is None)):
            continue
        g = out.setdefault(i.pr, {"pr": i.pr, "n": i.pr.rstrip("/").rsplit("/", 1)[-1], "titles": [], "areas": [], "area_ids": set()})
        g["titles"].append(i.title)
        g["area_ids"].add(i.area_id)
        area = db.get(FftArea, i.area_id) if i.area_id else None
        if area is not None and area.title not in g["areas"]:
            g["areas"].append(area.title)
    return list(out.values())


def after_state(db: Session) -> dict:
    """Whether Brett's round waits for changes to go live first, and which ({"on", "user_id", "area_id", "prs", "since"})."""
    from app.models import ToolSetting

    row = db.get(ToolSetting, AFTER)
    try:
        data = json.loads(row.value) if row is not None and row.value else {}
    except ValueError:
        data = {}
    return {"on": bool(data), "user_id": data.get("user_id"), "area_id": data.get("area_id"), "prs": data.get("prs", []), "since": data.get("since", "")}


def wait_for_live(db: Session, actor: str, user_id: int | None, area_id: int | None) -> list[dict]:
    """Let it go live first: Brett's round opens by itself once the changes it would hold are live (`fix_live`)."""
    from app.models import ToolSetting

    flight = in_flight(db, round_areas(db, area_id), whole=not area_id)
    if not flight:
        raise RuleError("stale", "Nothing is about to go live there now: start your round.")
    row = db.get(ToolSetting, AFTER) or ToolSetting(key=AFTER)
    row.value = json.dumps({"user_id": user_id, "area_id": area_id, "prs": [g["pr"] for g in flight], "since": now().isoformat()})
    db.merge(row)
    _event(db, actor, "round_after", "tool", 0, area_id=area_id, prs=[g["pr"] for g in flight])
    return flight


def cancel_wait(db: Session, actor: str) -> None:
    from app.models import ToolSetting

    row = db.get(ToolSetting, AFTER)
    if row is not None and row.value:
        row.value = ""
        _event(db, actor, "round_after_off", "tool", 0)


def _after_live(db: Session, actor: str) -> FftRound | None:
    """A change Brett's round waited for is live: once none of them is still on its way, his round opens (it holds)."""
    from app.models import ToolSetting

    st = after_state(db)
    if not st["on"]:
        return None
    if db.scalar(select(func.count()).select_from(FftIssue).where(FftIssue.state == "fixing", FftIssue.pr.in_(st["prs"]))):
        return None
    db.get(ToolSetting, AFTER).value = ""
    r = open_round(db, actor, st["user_id"], st["area_id"])
    _event(db, actor, "round_after_live", "round", r.id, area_id=st["area_id"])
    return r


def in_open_round(db: Session, area: FftArea) -> bool:
    """Is this area held by Brett's sitting (R11, lightened Nov 19): its own area, or for a round over all of them,
    every area with a check in his turn."""
    r = holding_round(db)
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
    items = db.scalars(select(FftItem).where(FftItem.section.in_(("now", "next", "later"))).order_by(item_rank(), FftItem.place, FftItem.id))
    for item in items:
        if item.next_whose == "brett":
            skipped.append((item.title, f"its next step is Brett's ({item.next_step})" if item.next_step else "its next step is Brett's"))
            continue
        for area in db.scalars(select(FftArea).where(FftArea.item_id == item.id, FftArea.archived.is_(False)).order_by(FftArea.place, FftArea.id)):
            turn = area_turn(db, area)
            if turn != "claude":
                continue
            if area.held:  # (below Work's cut line: Brett holds it)
                skipped.append((f"{item.title} › {area.title}", "held below the line"))
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
    if about == "document" and not doc_path:
        raise RuleError("bad", "A decision names its document.")
    if doc_path:  # (whatever it's about, the mockup it asks on: one Backstage › Documents lists, so For you can open it)
        from app.documents import doc_id, find

        if find(doc_id(doc_path)) is None:
            raise RuleError("bad", "That document isn't in docs/library.json.")
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


def answer(db: Session, actor: str, q: FftQuestion, *, choice: int | None, text: str = "", user_id: int | None = None,
           picks: list | None = None) -> None:
    """R13: the answer names its question, so a newer one can't take it; it moves the thing back to Claude. `picks`: the
    picks made on its mockup, saved from inside askdnd, which answer it on their own (Brett's round, Nov 18)."""
    if q.answered_at is not None:
        raise RuleError("stale", "It's already answered.")
    if choice is None and not text.strip() and not picks:
        raise RuleError("bad", "Pick an answer or write one.")
    if choice is not None and not 0 <= choice < len(q.choices or []):
        raise RuleError("bad", "That isn't one of its answers.")
    q.answer_choice, q.answer_text, q.answered_at, q.answered_by = choice, text.strip(), now(), user_id
    if picks:
        q.picks = picks
    _settled(db, actor, q)
    _event(db, actor, "question_answered", "question", q.id, choice=choice)


def withdraw(db: Session, actor: str, q: FftQuestion, why: str) -> None:
    """Nothing superseded waits on Brett (Nov 19): a question a later pick or mockup has answered or replaced is
    withdrawn by Claude with why. It leaves For you as an answer would, and its issue or check moves on the same way."""
    if q.answered_at is not None:
        raise RuleError("stale", "It's already answered.")
    if not why.strip():
        raise RuleError("bad", "Say why it's withdrawn.")
    q.answer_text, q.answered_at, q.answered_by = "Withdrawn: " + why.strip(), now(), None
    _settled(db, actor, q)
    _event(db, actor, "question_withdrawn", "question", q.id)


def _settled(db: Session, actor: str, q: FftQuestion) -> None:
    """A question no longer waits: its issue goes back to where it was when Claude asked, once nothing else waits on it;
    its check stops asking."""
    if q.about == "issue" and q.about_id:
        issue = db.get(FftIssue, q.about_id)
        if issue is not None and issue.state == "asks":
            open_q = db.scalar(select(func.count()).select_from(FftQuestion).where(FftQuestion.about == "issue", FftQuestion.about_id == issue.id,
                                                                                   FftQuestion.answered_at.is_(None), FftQuestion.id != q.id))
            if not open_q:  # (back to where it was when Claude asked: a fix under way stays under way, so it goes live
                # with its merge; the review of PR #417)
                asked = db.scalar(select(FftEvent.data).where(FftEvent.thing == "issue", FftEvent.thing_id == issue.id,
                                                              FftEvent.kind == "issue_asks").order_by(FftEvent.id.desc()))
                back = (asked or {}).get("from")
                _set_issue(db, actor, issue, back if back in ("to_fix", "fixing") else "to_fix", "issue_answered", question=q.id)
    if q.about == "check" and q.about_id:
        c = db.get(FftCheck, q.about_id)
        if c is not None:
            c.asks = False


# ------------------------------------------------------------------ listeners (T8)

SETTLE = timedelta(seconds=5)  # read only events this old, so one saved out of order isn't skipped


def listener(db: Session, name: str, area_id: int | None = None) -> FftListener:
    li = db.scalar(select(FftListener).where(FftListener.name == name))
    if li is None:
        li = FftListener(name=name[:60], area_id=area_id)
        db.add(li)
        db.flush()
    elif area_id is not None and li.area_id != area_id:  # (one made before it said its area hears only that area now)
        li.area_id = area_id
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
