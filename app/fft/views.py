"""How Found, Fixed, Tried reads to people (the v2 brief's words, docs/mockups/feedback-and-testing/): whose turn each
thing is (the pill: Yours amber, Claude's violet, a player's blue, Closed grey), the one sentence under it, and what a
note's sender is told on Notes you sent. The same words on every page; nothing here changes anything."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, picks
from app.fft import rules
from app.fft.models import FftArea, FftIdea, FftIssue, FftItem, FftLine, FftListener, FftNote, FftQuestion
from app.models import User

KIND_SAID = {"problem": "A problem", "idea": "An idea", "question": "A question"}  # (in the window, nothing picked first)
KIND_ASK = {"problem": "What's wrong?", "idea": "What would be better?", "question": "What would you like to know?"}
TONE = {"yours": "ask", "claude": "claude", "player": "ready", "closed": "quiet"}  # (state_word's tones: _admin_bits.html)
ISSUE_WORD = {"to_fix": "To fix", "fixing": "Fixing", "asks": "Claude asks", "merge_ok": "Your OK to merge",
              "ready": "Ready to try", "closed": "Closed"}
CLOSED_WORD = {"works": "Works now", "wont": "Won't do", "same": "Same as another", "cant_repro": "Can't reproduce",
               "withdrawn": "Withdrawn"}
LISTENING = timedelta(minutes=3)  # a listener heard this recently: a session is listening


def turn_pill(turn: str, name: str = "") -> tuple[str, str]:
    """(word, tone) for whose turn it is."""
    word = {"yours": "Yours", "claude": "Claude's", "closed": "Closed"}.get(turn) or (f"{name}'s" if name else "A player's")
    return word, TONE.get(turn, "ready")


def title_of(text: str, most: int = 90) -> str:
    """A note's title: its first sentence (or line), cut at a word to about one line (Notes you sent, Feedback)."""
    import re

    first = re.split(r"(?<=[.!?])\s|\n", (text or "").strip(), maxsplit=1)[0].strip() or "A note"
    if len(first) <= most:
        return first
    cut = first[:most].rsplit(" ", 1)[0] if " " in first[:most] else first[:most - 1]
    return cut.rstrip(" ,;:") + "…"


def local_href(url: str) -> str:
    """A note's page as a link that stays on askdnd: its path and query, or nothing (a note's address is the sender's
    browser's, never trusted to point elsewhere; the code review, Nov 16)."""
    from urllib.parse import urlparse

    from app.fft.steps import local_path

    u = urlparse(url or "")
    path = (u.path or "") + (f"?{u.query}" if u.query else "")
    return path if local_path(path) else ""


def first_name_of(db: Session, user_id: int | None) -> str:
    u = db.get(User, user_id) if user_id else None
    return ((u.name or "").split(" ")[0] if u else "") or "A player"


def issue_turn(db: Session, issue: FftIssue) -> tuple[str, str]:
    """(turn, the player's first name when it's theirs): a fix a player reported is theirs to confirm first (R5)."""
    if issue.state == "ready" and issue.confirm_by:
        return "player", first_name_of(db, issue.confirm_by)
    return {"brett": "yours", "claude": "claude", "closed": "closed"}[rules.ISSUE_TURN[issue.state]], ""


def issue_sentence(db: Session, issue: FftIssue) -> str:
    """The line under an issue's title, for an admin."""
    area = db.get(FftArea, issue.area_id) if issue.area_id else None
    where = f" in the {area.title} area" if area else ", in no area yet"
    if issue.state == "to_fix":
        return f"To fix: Claude's{where}" + (" (it came back)" if issue.reopened else "") + "."
    if issue.state == "fixing":
        return f"Claude is fixing it{where}."
    if issue.state == "asks":
        return "Claude asked you something: answer it in Testing's For you."
    if issue.state == "merge_ok":
        return "A player's words prompted this fix: it merges once you say so."
    if issue.state == "ready":
        if issue.confirm_by:
            return f"Live: {first_name_of(db, issue.confirm_by)} is asked whether it works now (yours if they haven't said in {rules.CONFIRM_DAYS} days)."
        return "Live: try it, in Testing."
    said = CLOSED_WORD.get(issue.close_reason or "", "Closed")
    if issue.close_reason == "same" and issue.same_as_id:
        other = db.get(FftIssue, issue.same_as_id)
        said += f": “{other.title}”" if other else ""
    return f"Closed: {said.lower() if not said.startswith('Same') else said}."


# ------------------------------------------------------------------ a note, as its sender sees it


_FETCH = object()  # (not given: sender_says looks it up itself)


def sender_says(db: Session, note: FftNote, me_id: int | None, issue=_FETCH, idea=_FETCH, lines: list | None = None) -> dict:
    """What a note's sender reads on Notes you sent: {turn, word, tone, sentence, open, asked}. Never another sender's
    words, the issue's title or anything only an admin sees (R2). `issue`, `idea` and `lines` (sender_lines) may be
    given, already read (`markers`, for many notes at once)."""
    def out(turn, sentence, open_=True, word=None, asked=False):
        w, tone = turn_pill(turn)
        return {"turn": turn, "word": word or w, "tone": tone, "sentence": sentence, "open": open_, "asked": asked}

    if note.state == "waiting":
        return out("player", "An admin reads it first, then Claude.", word="With an admin")
    if note.state == "declined":
        return out("closed", "Not taken up: the admin's words are below.", open_=False)
    if note.filed_as == "answered":
        return out("closed", "Answered: below.", open_=False, word="Answered")
    if note.filed_as == "idea":
        idea = (db.get(FftIdea, note.idea_id) if note.idea_id else None) if idea is _FETCH else idea
        st = idea.state if idea else "new"
        if st == "shipped":
            return out("closed", "Built: it's in askdnd now.", open_=False, word="Built")
        if st == "declined":
            return out("closed", "Not taken up as an idea" + (f": {idea.reason}" if idea and idea.reason else "."), open_=False)
        return out("claude", "Taken up as an idea: on the Roadmap" if st == "roadmap" else "Taken up as an idea: it waits its turn.", word="An idea")
    issue = (db.get(FftIssue, note.issue_id) if note.issue_id else None) if issue is _FETCH else issue
    if issue is None:
        return out("closed", "Closed.", open_=False)
    if issue.state == "closed":
        word = CLOSED_WORD.get(issue.close_reason or "", "Closed")
        return out("closed", {"works": "It works now.", "wont": "Not changing it: why is below.", "same": "It's being fixed with another note like it.",
                              "cant_repro": "Claude couldn't make it happen: why is below.", "withdrawn": "Withdrawn."}.get(issue.close_reason or "", "Closed."),
                   open_=False, word=word if issue.close_reason != "same" else "Closed")
    if issue.state == "ready":
        if issue.confirm_by and issue.confirm_by == me_id:
            return out("yours", "Fixed and live: does it work now?")
        return out("claude", "Fixed and live: being tried.", word="Fixed")
    asked = _asked(lines if lines is not None else sender_lines(db, note))
    return out("claude", "Claude is fixing it" + (", and asked you something." if asked else "."), asked=asked)


def _asked(lines: list) -> bool:
    """Claude's or an admin's last line to its senders is newer than anything the sender said."""
    last_to = max((x.id for x in lines if x.to == "sender"), default=0)
    last_from = max((x.id for x in lines if x.who == "sender"), default=0)
    return bool(last_to and last_to > last_from)


def _their_lines(note: FftNote):
    """The lines a sender may read: on their note, and those to every sender on its issue (R2)."""
    cond = FftLine.note_id == note.id
    if note.issue_id:
        cond = cond | ((FftLine.issue_id == note.issue_id) & (FftLine.to == "sender"))
    return cond


def sender_lines(db: Session, note: FftNote) -> list[FftLine]:
    """A note's conversation as its sender reads it: their own lines (approved or not: they wrote them) and the
    lines meant for them; never another sender's, never Brett and Claude's to each other."""
    rows = db.scalars(select(FftLine).where(_their_lines(note)).order_by(FftLine.id))
    return [x for x in rows if x.who == "sender" or x.to == "sender"]


def marker(db: Session, note: FftNote, me_id: int | None) -> str:
    """Where a note stands for its sender and the last line they can read: when it differs from `seen`, it's new."""
    return markers(db, [note], me_id)[note.id]


def markers(db: Session, notes: list[FftNote], me_id: int | None) -> dict[int, str]:
    """`marker` for many notes in four reads, not several per note (Notes you sent's badge runs on every page)."""
    if not notes:
        return {}
    issue_ids = {n.issue_id for n in notes if n.issue_id}
    idea_ids = {n.idea_id for n in notes if n.idea_id}
    issues = {i.id: i for i in db.scalars(select(FftIssue).where(FftIssue.id.in_(issue_ids)))} if issue_ids else {}
    ideas = {i.id: i for i in db.scalars(select(FftIdea).where(FftIdea.id.in_(idea_ids)))} if idea_ids else {}
    cond = FftLine.note_id.in_([n.id for n in notes])
    if issue_ids:
        cond = cond | (FftLine.issue_id.in_(issue_ids) & (FftLine.to == "sender"))
    lines = list(db.scalars(select(FftLine).where(cond).order_by(FftLine.id)))
    out = {}
    for n in notes:
        mine = [x for x in lines if (x.note_id == n.id or (n.issue_id and x.issue_id == n.issue_id and x.to == "sender"))
                and (x.who == "sender" or x.to == "sender")]
        word = sender_says(db, n, me_id, issue=issues.get(n.issue_id), idea=ideas.get(n.idea_id), lines=mine)["word"]
        out[n.id] = f"{word}:{max((x.id for x in mine if x.who != 'sender'), default=0)}"[:40]
    return out


def notes_of(db: Session, user_id: int | None) -> list[FftNote]:
    if not user_id:
        return []
    return list(db.scalars(select(FftNote).where(FftNote.user_id == user_id).order_by(FftNote.id.desc()).limit(200)))


# ------------------------------------------------------------------ who's sending, and whether Claude's listening


def person(db: Session, user: dict | None) -> dict | None:
    """The person a note is from: their row, first name and role here (T2: no email leaves this)."""
    if not user:
        return None
    from app.extraction import first_name

    email = (user.get("email") or "").lower()
    row = picks.user_row(db, user)
    admin = access.level(email) == access.ADMIN
    role = "admin" if admin else (access.role(email) or "member")
    name = first_name(user.get("name") or (row.name if row else "") or "")  # (T2: never an email, never a full name)
    return {"row": row, "id": row.id if row else None, "email": email, "first_name": name or "Someone", "role": role, "admin": admin}


def listening(db: Session) -> bool:
    """A Claude session heard its inbox in the last few minutes (T8's read marks keep when each last asked)."""
    last = db.scalar(select(func.max(FftListener.heard_at)))
    return bool(last and rules.now() - last < LISTENING)


def send_line(db: Session, admin: bool) -> str:
    """The truthful line beside Send (screen 9)."""
    if not admin:
        return "An admin reads it first, then Claude."
    return "Claude is listening: it reads it within a minute." if listening(db) else "It waits for Claude's next session."


# ------------------------------------------------------------------ counts


def to_approve(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(FftNote).where(FftNote.state == "waiting")) or 0


def for_brett(db: Session) -> int:
    """What waits on Brett in Feedback: notes to approve, fixes waiting for his OK, Claude's open questions."""
    issues = db.scalar(select(func.count()).select_from(FftIssue).where(FftIssue.state == "merge_ok")) or 0
    asks = db.scalar(select(func.count()).select_from(FftQuestion).where(FftQuestion.answered_at.is_(None))) or 0
    return to_approve(db) + issues + asks


def items_in_order(db: Session) -> list[FftItem]:
    return list(db.scalars(select(FftItem).order_by(FftItem.place, FftItem.id)))


# ------------------------------------------------------------------ the record, in words


def event_words(ev) -> str:
    """One line saying what happened: Claude's inbox and an issue's History. It never quotes what anyone wrote (T1),
    only what changed."""
    d = ev.data or {}
    if ev.kind == "note_sent":
        return "A note from a player waits for Brett's approval" if d.get("role") != "admin" or d.get("staging") else f"Brett sent a note ({d.get('note_kind')})"
    if ev.kind == "line_added" and not d.get("approved", True):
        return "A player added to their note (it waits for Brett's approval)"
    if ev.kind == "note_filed":
        return f"Note {ev.thing_id} filed as {d.get('as_')}" + (f": issue {d['issue']}" if d.get("issue") else "")
    if ev.kind == "note_joined":
        return f"Note {ev.thing_id} joined issue {d.get('issue')}"
    if ev.kind in ("try_passed", "try_failed", "try_cant"):
        return f"Check {d.get('check')}: {ev.kind[4:]} on the {d.get('device')} ({d.get('where')})"
    if ev.kind == "question_answered":
        return f"Brett answered question {ev.thing_id}"
    if "to" in d:
        return f"{ev.thing.title()} {ev.thing_id}: {d.get('from')} → {d.get('to')}"
    return f"{ev.thing.title()} {ev.thing_id}: {ev.kind.replace('_', ' ')}"
