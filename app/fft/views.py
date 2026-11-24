"""How Found, Fixed, Tried reads to people (the v2 brief's words, docs/mockups/feedback-and-testing/): whose turn each
thing is (the pill: Yours amber, Claude's violet, a player's blue, Closed grey), the one sentence under it, and what a
note's sender is told on Notes you sent. The same words on every page; nothing here changes anything."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, config, picks
from app.fft import rules, taxonomy
from app.fft.models import (
    FftArea,
    FftCheck,
    FftCheckIssue,
    FftEvent,
    FftIdea,
    FftIssue,
    FftItem,
    FftLine,
    FftListener,
    FftNote,
    FftNoteIssue,
    FftPull,
    FftQuestion,
)
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


def doc_of(path: str) -> dict | None:
    """The mockup a question asks on, as Backstage › Documents lists it: its name, its page in askdnd, its claude.ai link."""
    if not path:
        return None
    from app.documents import doc_id, find

    e = find(doc_id(path))
    if e is None:
        return {"title": path.rsplit("/", 2)[-2] if "/" in path else path, "href": "/manage/documents", "link": ""}
    return {"title": e["title"], "href": f"/manage/documents/{e['id']}", "link": e.get("link") or ""}


def question_view(q: FftQuestion) -> dict:
    """A question as the conversation and For you show it: its words, answers to tap, Claude's pick, its mockup, Brett's answer."""
    picked = (q.choices or [])[q.answer_choice] if q.answer_choice is not None and q.answer_choice < len(q.choices or []) else None
    return {"q": q, "doc": doc_of(q.doc_path), "picked": picked}


def talk(lines: list, asked: list[dict]) -> list[tuple]:
    """An issue's conversation in the order it happened: its lines and Claude's questions (question_view) together."""
    said = [(x.created_at, 0, x.id, x) for x in lines] + [(a["q"].created_at, 1, a["q"].id, a) for a in asked]
    return [(at, x) for at, _, _, x in sorted(said, key=lambda t: t[:3])]


def first_name_of(db: Session, user_id: int | None) -> str:
    u = db.get(User, user_id) if user_id else None
    return ((u.name or "").split(" ")[0] if u else "") or "A player"


CHECK_WORD = {"to_try": "To try", "again": "To try again", "later": "Later", "asks": "Claude asks", "failed": "Failed",
              "fixing": "Being fixed", "wrong": "Being rewritten", "blocked": "Blocked", "preflight": "Claude tries it first", "deploying": "Waits for its deploy",
              "passed": "Passed", "retired": "Retired"}  # (where a check stands, in words: `rules.check_state`)


def check_word(st: dict) -> str:
    return CHECK_WORD["again"] if st["again"] and st["state"] == "to_try" else CHECK_WORD.get(st["state"], st["state"])


def issue_checks(db: Session, issue: FftIssue) -> list[dict]:
    """The checks that try an issue's fix, each with where it stands (`rules.check_state`) and that in words, retired
    ones left out."""
    out = []
    for c in db.scalars(select(FftCheck).join(FftCheckIssue, FftCheckIssue.check_id == FftCheck.id)
                        .where(FftCheckIssue.issue_id == issue.id, FftCheck.retired.is_(False)).order_by(FftCheck.id)):
        st = rules.check_state(db, c)
        out.append({"c": c, **st, "word": check_word(st)})
    return out


def issue_turn(db: Session, issue: FftIssue) -> tuple[str, str]:
    """(turn, the player's first name when it's theirs): a fix a player reported is theirs to confirm first (R5). A
    ready issue whose checks are all Claude's (blocked, wrong, still failing) is Claude's too, never Yours with nothing
    to try (Brett's round, Nov 18)."""
    if issue.state == "ready" and issue.confirm_by:
        return "player", first_name_of(db, issue.confirm_by)
    if issue.state == "ready" and (cs := issue_checks(db, issue)) and not any(x["turn"] == "brett" for x in cs):
        return "claude", ""
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
        return "Claude asked you something: answer it in For you."
    if issue.state == "merge_ok":
        return "A player's words prompted this fix: it merges once you say so."
    if issue.state == "ready":
        if issue.confirm_by:
            return f"Live: {first_name_of(db, issue.confirm_by)} is asked whether it works now (yours if they haven't said in {rules.CONFIRM_DAYS} days)."
        cs = issue_checks(db, issue)  # (named, each with where it stands, under this line: _fft_bits.html its_checks)
        one = len(cs) == 1
        if any(x["turn"] == "brett" for x in cs):
            return "Live: try " + ("its check" if one else "its checks") + " in For you."
        if cs:
            return "Live, but " + ("its check" if one else "its checks") + " can't be tried yet: Claude's to sort out."
        return "Live: Claude still owes it a check to try."
    said = CLOSED_WORD.get(issue.close_reason or "", "Closed")
    if issue.close_reason == "same" and issue.same_as_id:
        other = db.get(FftIssue, issue.same_as_id)
        said += f": “{other.title}”" if other else ""
    return f"Closed: {said.lower() if not said.startswith('Same') else said}."


# ------------------------------------------------------------------ a note, as its sender sees it


_FETCH = object()  # (not given: sender_says looks it up itself)


def sender_says(db: Session, note: FftNote, me_id: int | None, issue=_FETCH, idea=_FETCH, parts=_FETCH) -> dict:
    """What a note's sender reads on Notes you sent: {turn, word, tone, sentence, open}. Never another sender's words,
    the issue's title or anything only an admin sees (R2). `issue` and `idea` may be given, already read (`markers`, for
    many notes at once). A line to them is a new reply, never "asked you something": a line isn't marked a question,
    and its words don't decide (Brett's round, Nov 18, issue 32 on askdnd.ai)."""
    def out(turn, sentence, open_=True, word=None):
        w, tone = turn_pill(turn)
        return {"turn": turn, "word": word or w, "tone": tone, "sentence": sentence, "open": open_}

    if note.state == "waiting":
        return out("player", "An admin reads it first, then Claude.", word="With an admin")
    if note.state == "declined":
        return out("closed", "Not taken up: the admin's words are below.", open_=False)
    if note.filed_as == "answered":
        return out("closed", "Answered: below.", open_=False, word="Answered")
    if note.filed_as == "question":  # (sent for Claude to answer, waiting: issue 27)
        return out("claude", "A question for Claude: the answer comes here.")
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
    if parts is _FETCH:
        parts = [db.get(FftIssue, x) for x in rules.issues_of_note(db, note)[1:]]
    if parts:  # (Split… into several issues, issue 22: how each part turns out, in order, never their titles: R2)
        each = [_one_issue(x, me_id) for x in [issue, *parts]]
        mine = next((x for x in each if x[0] == "yours"), None)
        left = sum(1 for x in each if x[3])
        if mine:
            said = out(*mine[:2])
        elif left:
            said = out("claude", f"Split into {len(each)} parts: {len(each) - left} done, {left} being fixed.")
        else:
            said = out("closed", f"Split into {len(each)} parts, all closed.", open_=False)
        return said | {"parts": [{"word": w or turn_pill(t)[0], "tone": turn_pill(t)[1], "sentence": s, "open": o} for t, s, w, o in each]}
    turn, sentence, word, open_ = _one_issue(issue, me_id)
    return out(turn, sentence, open_, word)


def _one_issue(issue, me_id: int | None) -> tuple[str, str, str | None, bool]:
    """One issue as a sender reads it: (turn, sentence, word, open)."""
    if issue.state == "closed":
        word = CLOSED_WORD.get(issue.close_reason or "", "Closed")
        return ("closed", {"works": "It works now.", "wont": "Not changing it: why is below.", "same": "It's being fixed with another note like it.",
                           "cant_repro": "Claude couldn't make it happen: why is below.", "withdrawn": "Withdrawn."}.get(issue.close_reason or "", "Closed."),
                word if issue.close_reason != "same" else "Closed", False)
    if issue.state == "ready":
        if issue.confirm_by and issue.confirm_by == me_id:
            return ("yours", "Fixed and live: does it work now?", None, True)
        return ("claude", "Fixed and live: being tried.", "Fixed", True)
    return ("claude", "Claude is fixing it.", None, True)


def _their_lines(note: FftNote):
    """The lines a sender may read: on their note, and those to every sender on its issue, or on each part it was split
    into (R2, issue 22)."""
    cond = FftLine.note_id == note.id
    if note.issue_id:
        on = FftLine.issue_id.in_(select(FftNoteIssue.issue_id).where(FftNoteIssue.note_id == note.id)) | (FftLine.issue_id == note.issue_id)
        cond = cond | (on & (FftLine.to == "sender"))
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
    split: dict[int, list[int]] = {}  # (a note's split parts, issue 22)
    for nid, iid in db.execute(select(FftNoteIssue.note_id, FftNoteIssue.issue_id).where(FftNoteIssue.note_id.in_([n.id for n in notes])).order_by(FftNoteIssue.issue_id)):
        split.setdefault(nid, []).append(iid)
    issue_ids = {n.issue_id for n in notes if n.issue_id} | {i for ids in split.values() for i in ids}
    idea_ids = {n.idea_id for n in notes if n.idea_id}
    issues = {i.id: i for i in db.scalars(select(FftIssue).where(FftIssue.id.in_(issue_ids)))} if issue_ids else {}
    ideas = {i.id: i for i in db.scalars(select(FftIdea).where(FftIdea.id.in_(idea_ids)))} if idea_ids else {}
    cond = FftLine.note_id.in_([n.id for n in notes])
    if issue_ids:
        cond = cond | (FftLine.issue_id.in_(issue_ids) & (FftLine.to == "sender"))
    lines = list(db.scalars(select(FftLine).where(cond).order_by(FftLine.id)))
    out = {}
    for n in notes:
        on = {n.issue_id, *split.get(n.id, [])} if n.issue_id else set()
        mine = [x for x in lines if (x.note_id == n.id or (x.issue_id in on and x.to == "sender"))
                and (x.who == "sender" or x.to == "sender")]
        parts = [issues[i] for i in split.get(n.id, []) if i in issues] if n.issue_id else []
        said = sender_says(db, n, me_id, issue=issues.get(n.issue_id), idea=ideas.get(n.idea_id), parts=parts)
        word = said["word"] + (f"/{sum(1 for p in said['parts'] if p['open'])}of{len(said['parts'])}" if said.get("parts") else "")  # (short: the marker keeps 40 characters)
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


def send_line(db: Session, admin: bool, sent: bool = False) -> str:
    """The truthful line beside Send (screen 9), or once it's sent (`sent`): the same truth, said as done."""
    if not admin:
        return "Sent: an admin reads it first, then Claude." if sent else "An admin reads it first, then Claude."
    if listening(db):
        return "Sent: Claude reads it within a minute." if sent else "Claude is listening: it reads it within a minute."
    return "Sent: it waits for Claude's next session." if sent else "It waits for Claude's next session."


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


def pull_worth_saying(ev) -> bool:
    """A pull request's event a plan's History shows: opened, ended, brought up to date, tests passed or failed; not each
    flicker of its merge state."""
    d = ev.data or {}
    ch = d.get("changes") or {}
    return ev.kind in ("pull_new", "pull_live") or bool(d.get("to")) or bool(ch.get("updated")) or ch.get("tests") in ("passed", "failed")


def event_words(ev) -> str:
    """One line saying what happened: Claude's inbox and an issue's History. It never quotes what anyone wrote (T1),
    only what changed."""
    d = ev.data or {}
    if ev.thing == "pull":  # (a pull request's record, item 39: on a plan's History; never an inbox, rules.heard)
        n = d.get("number")
        if ev.kind == "pull_live":
            return f"Pull request #{n} is live on askdnd.ai"
        if ev.kind == "pull_new":
            return f"Pull request #{n} " + {"merged": "merged", "closed": "closed"}.get(d.get("to") or "", "opened")
        if d.get("to"):
            return f"Pull request #{n} {'reopened' if d['to'] == 'open' else d['to']}"
        ch = d.get("changes") or {}
        if ch.get("updated"):
            return f"Pull request #{n} brought up to date with main"
        if ch.get("tests") in ("passed", "failed"):
            return f"Pull request #{n}'s tests {ch['tests']}"
        return f"Pull request #{n} changed"
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
    if ev.kind == "question_withdrawn":
        return f"Claude withdrew question {ev.thing_id} (a later pick replaced it)"
    if ev.kind == "line_added":  # (its "to" is who it's for, never a state: the review of PR #417)
        who = "Claude" if ev.actor == "claude" else "askdnd" if ev.actor == "askdnd" else "An admin" if ev.actor.startswith("user:") else "Someone"
        to = {"sender": ", to its senders", "claude": ", to Claude"}.get(d.get("to") or "", "")
        return f"{who} wrote on {ev.thing} {ev.thing_id}{to}"
    if ev.thing == "item" and ev.kind.startswith("item_"):  # (a Roadmap item's Updates, and Claude's inbox)
        said = {"item_new": "Added to the Roadmap", "item_addition": "Brett added to it" + {"chat": " (said in chat)", "discussion": " (in a discussion with Claude)"}.get(d.get("where") or "", ""),
                "item_answered": "Claude answered an addition: " + {"in": "in scope", "later": "later", "question": "a question"}.get(d.get("answer", ""), ""),
                "item_scope": f"Claude wrote scope version {d.get('version')}", "item_agreed": f"Brett: scope version {d.get('version')} looks right",
                "item_changes": f"Brett asked for changes to scope version {d.get('version')}",
                "item_comments": f"Brett's {d.get('n')} comment{'s' if d.get('n') != 1 else ''} on its scope" + (f" (answers to {d.get('answers')} question{'s' if d.get('answers') != 1 else ''})" if d.get("answers") else ""),
                "item_step": "A step added" + (" for Brett" if d.get("whose") == "brett" else ""), "item_step_done": "A step done",
                "item_step_open": "A step not done after all", "item_step_removed": "A step taken off", "item_shipped": "Shipped",
                "item_not_doing": "Not doing", "item_set": "Its " + ", ".join(k for k in ("title", "why", "size", "status", "result") if d.get(k) or (k == "why" and d.get("why_from"))) + " changed",
                "item_scope_asked": "Brett pressed Scope it: first in Claude's queue", "item_scope_unasked": "Brett: not now (back in its place)",
                "item_moved": f"Moved to {str(d.get('section', '')).replace('_', ' ').title()}", "item_next": "Its next step changed"}.get(ev.kind)
        if said:
            return f"Roadmap item {ev.thing_id}: {said}"
    if ev.kind == "issue_split":  # (Split…, issue 22)
        return f"Issue {ev.thing_id} split: issues {', '.join(str(x) for x in d.get('into') or [])} have its notes too"
    if ev.kind == "issue_split_from":
        return f"Issue {ev.thing_id} split from issue {d.get('issue')}, with its notes"
    if ev.kind == "issue_kind":
        return f"Issue {ev.thing_id} is {'an improvement' if d.get('became') == 'improvement' else 'a fix'}"
    if ev.kind == "issue_feature":
        return f"Issue {ev.thing_id} is about {taxonomy.path(d.get('feature', '')) or d.get('feature')}" + (f" (was {taxonomy.path(d['was'])})" if d.get("was") else "")
    if ev.kind == "area_lane":
        said = rules.LANE_SAID
        return f"Lane: {said.get(d.get('from') or '', d.get('from')) or 'none'} → {said.get(d.get('to') or '', d.get('to'))}"
    if ev.kind in ("area_held", "area_let_go"):
        return "Held below Development's line" if ev.kind == "area_held" else "Let go: back above Development's line"
    if ev.kind == "check_moved":
        return f"Check {ev.thing_id} followed issue {d.get('issue')} into this plan"
    if "to" in d:
        words = ISSUE_WORD if ev.thing == "issue" else {}
        return f"{ev.thing.title()} {ev.thing_id}: {words.get(d.get('from'), d.get('from'))} → {words.get(d.get('to'), d.get('to'))}"
    what = ev.kind.removeprefix(ev.thing + "_").replace("_", " ")  # ("check_restored" on check 21: "Check 21: restored")
    return f"{ev.thing.title()} {ev.thing_id}: {what}"


# ------------------------------------------------------------------ what Claude left half done


def gaps(db: Session) -> list[dict]:
    """What Claude left half done, each Claude's to close now (Brett, Nov 17: "how are we going to make sure that you do
    not miss something?"): a fix with no check to try it; a check Claude hasn't tried itself (R18); something said on an
    open issue, a note, a failed try, a line or an answer, that Claude hasn't replied to; an open issue with no Feature; a
    question sent to Claude and not yet answered; a fix in a pull request whose plan has no lane (Nov 19).
    `feedback.py gaps` prints them, Claude Code's end-of-turn hook won't let a turn end on one, and Development
    shows them as Claude missed. Nothing waiting on Brett is a gap."""
    from app.fft.models import FftTry, FftTryIssue

    out = []
    checked = set(db.scalars(select(FftCheckIssue.issue_id).join(FftCheck, FftCheck.id == FftCheckIssue.check_id)
                             .where(FftCheck.retired.is_(False))))
    issues = list(db.scalars(select(FftIssue).where(FftIssue.state != "closed").order_by(FftIssue.id)))
    for i in issues:
        if i.pr and i.id not in checked:
            out.append({"kind": "no_check", "thing": "issue", "id": i.id, "title": i.title,
                        "says": "Fixed, with no check to try it: write one (--issue), try it yourself, mark it passed."})
    for c in db.scalars(select(FftCheck).where(FftCheck.retired.is_(False), FftCheck.preflight != "passed").order_by(FftCheck.id)):
        out.append({"kind": "not_tried", "thing": "check", "id": c.id, "title": c.title,
                    "says": "Not tried by Claude yet (R18): try it, then preflight pass (or fail, and fix)."})
    ids = [i.id for i in issues] or [0]
    notes = list(db.scalars(select(FftNote).where(FftNote.issue_id.in_(ids), FftNote.state == "filed")))
    lines = list(db.scalars(select(FftLine).where((FftLine.issue_id.in_(ids)) | (FftLine.note_id.in_([n.id for n in notes] or [0])))))
    asked = list(db.scalars(select(FftQuestion).where(FftQuestion.about == "issue", FftQuestion.about_id.in_(ids))))
    tries = db.execute(select(FftTryIssue.issue_id, FftTry.created_at).join(FftTry, FftTry.id == FftTryIssue.try_id)
                       .where(FftTryIssue.issue_id.in_(ids), FftTry.replaced.is_(False), FftTry.actor == "person")).all()
    of_note = {n.id: n.issue_id for n in notes}
    said: dict[int, list] = {i.id: [] for i in issues}  # issue -> [(when, by Claude?)]
    for n in notes:
        said[n.issue_id].append((n.created_at, False))
    for x in lines:
        iid = x.issue_id or of_note.get(x.note_id)
        if iid in said and x.who != "askdnd" and (x.who == "claude" or x.approved):
            said[iid].append((x.created_at, x.who == "claude"))
    for q in asked:
        said[q.about_id].append((q.created_at, True))
        if q.answered_at:
            said[q.about_id].append((q.answered_at, False))
    for iid, at in tries:
        said[iid].append((at, False))
    for i in issues:
        theirs = [at for at, claude in said[i.id] if not claude]
        mine = [at for at, claude in said[i.id] if claude]
        if theirs and i.state != "asks" and (not mine or max(theirs) > max(mine)):
            out.append({"kind": "unanswered", "thing": "issue", "id": i.id, "title": i.title, "since": max(theirs),
                        "says": "Said to Claude and not answered: reply (feedback.py issue <id> tell … --to brett) with what you'll do."})
        if not taxonomy.feature(i.feature):  # (the Product Taxonomy, Nov 18: every issue in one Feature, so in its batch)
            out.append({"kind": "no_feature", "thing": "issue", "id": i.id, "title": i.title,
                        "says": "No Feature yet: give it one (feedback.py issue <id> feature <key>; feedback.py features lists them)."})
    for a in db.scalars(select(FftArea).where(FftArea.archived.is_(False)).order_by(FftArea.id)):  # (Brett, Nov 19: a fix never
        if not rules.lane_of(a) and any(i.pr and i.area_id == a.id for i in issues):  # goes without its lane)
            out.append({"kind": "no_lane", "thing": "area", "id": a.id, "title": a.title,
                        "says": "A fix in a pull request with no lane: feedback.py lane --area <id> (or attach its pull request again)."})
    for it in db.scalars(select(FftItem).where(FftItem.standing.is_(False), FftItem.section.in_(rules.ROADMAP_SECTIONS)).order_by(FftItem.id)):
        sc = rules.latest_scope(db, it)  # (Needs changes… on its scope: Claude answers each comment and writes the next, issue 54)
        if sc is not None and sc.agreed_at is None and sc.changes_at is not None:
            out.append({"kind": "scope_changes", "thing": "item", "id": it.id, "title": it.title, "since": sc.changes_at,
                        "says": f"Brett asked for changes to scope v{sc.version}: answer each comment (feedback.py roadmap {it.id} answer …) and write v{sc.version + 1} (scope … --changed)."})
    for it in rules.scope_asked(db):  # (Scope it, Brett's pick Nov 21: first in the queue, so in Claude's hands now)
        out.append({"kind": "scope_asked", "thing": "item", "id": it.id, "title": it.title, "since": it.scope_asked_at,
                    "says": f"Brett pressed Scope it: write its first version (feedback.py roadmap {it.id} scope --what … --in …)."})
    for it in db.scalars(select(FftItem).where(FftItem.section == "shipped", FftItem.result == "").order_by(FftItem.id)):  # (Brett, Nov 20)
        out.append({"kind": "no_result", "thing": "item", "id": it.id, "title": it.title,
                    "says": "Shipped with no result: write what it changed, with its numbers (feedback.py roadmap <id> set --result \"…\")."})
    for it, last in rules.builds_done(db):  # (issue 72, Brett Nov 22: a build stayed in the queue after he ticked its last step)
        out.append({"kind": "steps_done", "thing": "item", "id": it.id, "title": it.title, "since": last,
                    "says": f"Every step is done: ship it with what it changed (feedback.py roadmap {it.id} ship --result \"…\"), or add the step that's left."})
    frozen = rules.freeze_state(db)["on"]
    for p in db.scalars(select(FftPull).where(FftPull.state == "open").order_by(FftPull.number)):  # (item 39: GitHub reports them)
        if p.tests == "failed":  # (since its tests failed: a later change to it, such as its merge state, doesn't restart the wait)
            red = db.scalar(select(func.max(FftEvent.at)).where(FftEvent.thing == "pull", FftEvent.thing_id == p.id,
                                                                FftEvent.data["changes"]["tests"].astext == "failed"))
            out.append({"kind": "pull_red", "thing": "pull", "id": p.id, "title": f"#{p.number} {p.title}", **({"since": red} if red else {}),
                        "says": f"Pull request #{p.number}'s tests failed: fix it, or close it if it's no longer wanted."})
        if p.unclaimed:
            out.append({"kind": "pull_unclaimed", "thing": "pull", "id": p.id, "title": f"#{p.number} {p.title}",
                        "says": f"Pull request #{p.number} was opened for work nobody claimed: claim its plan (feedback.py claim --area <id>), so it's on the record as yours."})
        if p.tests == "passed" and p.merge_state == "clean" and not p.auto_merge and not frozen and not _held_back(db, p):
            out.append({"kind": "pull_waiting", "thing": "pull", "id": p.id, "title": f"#{p.number} {p.title}",
                        "says": f"Pull request #{p.number} passed and can merge, but isn't set to: merge it, or turn auto-merge on (GitHub turns it off after a failed try)."})
        if p.merge_state == "behind" and p.auto_merge and not frozen and not _held_back(db, p):  # (Nov 24: GitHub's robot can't do it)
            out.append({"kind": "pull_behind", "thing": "pull", "id": p.id, "title": f"#{p.number} {p.title}",
                        "says": f"Pull request #{p.number} is set to merge but is behind main: bring it up to date (gh pr update-branch {p.number}), so its tests run again and it merges."})
        if p.merge_state == "dirty":
            out.append({"kind": "pull_conflicts", "thing": "pull", "id": p.id, "title": f"#{p.number} {p.title}",
                        "says": f"Pull request #{p.number} conflicts with main, so it can't be brought up to date: merge main into it."})
    running = config.running_version()  # (deploys mark themselves live, item 39: a version askdnd can't place releases nothing)
    if running and rules.now() - config.STARTED_AT > UNPLACED_AFTER and db.scalar(select(FftPull.id).limit(1)) and rules.version_pull(db, running) is None:
        out.append({"kind": "version_unplaced", "thing": "deploy", "id": 0, "title": f"askdnd.ai runs {running[:7]}", "since": config.STARTED_AT,
                    "says": "No pull request askdnd knows has this merge commit, so nothing in it was marked live: find which fixes it holds and run feedback.py live."})
    for n in db.scalars(select(FftNote).where(FftNote.state == "filed", FftNote.filed_as == "question").order_by(FftNote.id)):
        out.append({"kind": "question", "thing": "note", "id": n.id, "title": title_of(n.text),
                    "says": "A question sent to Claude, waiting for its answer (feedback.py note <id> --answer \"…\")."})
    return _since(db, out)


GAP_WORDS = {"no_check": "fixed, with no check for you to try", "not_tried": "a check Claude hasn't tried itself",
             "unanswered": "you said something Claude hasn't answered", "no_feature": "no Feature yet",
             "question": "a question you sent, not answered yet", "no_lane": "a fix waiting with no lane",
             "no_result": "finished, with no result written yet", "scope_changes": "you asked for changes to its scope",
             "scope_asked": "you asked for its scope", "steps_done": "every step done, not shipped yet",
             "pull_red": "a pull request whose tests failed", "pull_conflicts": "a pull request that conflicts with main",
             "pull_behind": "a pull request waiting to merge, behind main",
             "version_unplaced": "askdnd.ai runs a version no pull request explains",
             "pull_unclaimed": "a pull request for work nobody claimed", "pull_waiting": "a pull request that passed and isn't merging"}  # (each kind of gap, as Development says it)
UNPLACED_AFTER = timedelta(minutes=15)  # (GitHub reports a merge within a minute; a deploy takes about ten)
GAP_GRACE = timedelta(minutes=15)  # (Brett, Nov 19, issue 39: what just happened isn't late yet; 15 minutes, his pick 1A, issue 21)


def _since(db: Session, out: list[dict]) -> list[dict]:
    """When each gap began: the last thing that happened to it (its newest event), else when it was made."""
    for g in out:
        if g.get("since"):
            continue
        at = db.scalar(select(func.max(FftEvent.at)).where(FftEvent.thing == g["thing"], FftEvent.thing_id == g["id"]))
        if g["thing"] == "area":
            at = db.scalar(select(func.max(FftEvent.at)).where(FftEvent.kind == "issue_pr", FftEvent.area_id == g["id"])) or at
        row = {"issue": FftIssue, "check": FftCheck, "note": FftNote, "area": FftArea, "item": FftItem, "pull": FftPull}[g["thing"]]
        g["since"] = at or getattr(db.get(row, g["id"]), "created_at", None) or rules.now()
    return out


def hands(db: Session) -> list[dict]:
    """What's in Claude's hands (Brett's pick 1A on docs/mockups/fft-round-2/, issue 21: "you haven't missed anything
    yet; you just haven't processed it"): every gap, oldest first, each `late` once it has waited GAP_GRACE while a
    Claude session listens. With none listening it waits for the next session and nothing is late. Claude's own
    end-of-turn check still holds it to every one at once."""
    cut, on = rules.now() - GAP_GRACE, listening(db)
    return [g | {"late": on and g["since"] <= cut} for g in sorted(gaps(db), key=lambda g: g["since"])]


def missed(db: Session) -> list[dict]:
    """Waiting on Claude too long (Development's amber panel): the late ones in `hands`."""
    return [g for g in hands(db) if g["late"]]


def _held_back(db: Session, p: FftPull) -> bool:
    """A green pull request that's meant to wait: its plan is Careful (Brett tries it first), in his open round, or has
    a local try he hasn't answered."""
    from app.fft.models import FftLocalTry

    a = db.get(FftArea, p.area_id) if p.area_id else None
    if a is None:
        return False
    waiting_try = db.scalar(select(FftLocalTry.id).where(FftLocalTry.area_id == a.id, FftLocalTry.answer == "").limit(1)) is not None
    return rules.lane_of(a) == "careful" or rules.in_open_round(db, a) or waiting_try  # (or his local try first: After my local try)


def pull_row(p: FftPull) -> dict:
    """A pull request for the API and feedback.py: where it stands and the work it's for (Upkeep: nothing)."""
    return {"number": p.number, "title": p.title, "branch": p.branch, "by_bot": p.by_bot, "state": p.state, "tests": p.tests,
            "merge_state": p.merge_state, "auto_merge": p.auto_merge, "issue": p.issue_id, "area": p.area_id, "item": p.item_id,
            "upkeep": rules.pull_upkeep(p), "reported_at": p.reported_at.isoformat() if p.reported_at else None,
            "updated_by_askdnd_at": p.updated_by_askdnd_at.isoformat() if p.updated_by_askdnd_at else None,
            "merge_commit": p.merge_commit, "live_at": p.live_at.isoformat() if p.live_at else None}
