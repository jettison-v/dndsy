"""How Found, Fixed, Tried reads to people (the v2 brief's words, docs/mockups/feedback-and-testing/): whose turn each
thing is (the pill: Yours amber, Claude's violet, a player's blue, Closed grey), the one sentence under it, and what a
note's sender is told on Notes you sent. The same words on every page; nothing here changes anything."""

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import access, picks
from app.fft import rules, taxonomy
from app.fft.models import FftArea, FftCheck, FftCheckIssue, FftIdea, FftIssue, FftItem, FftLine, FftListener, FftNote, FftQuestion
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


def sender_says(db: Session, note: FftNote, me_id: int | None, issue=_FETCH, idea=_FETCH) -> dict:
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
    if issue.state == "closed":
        word = CLOSED_WORD.get(issue.close_reason or "", "Closed")
        return out("closed", {"works": "It works now.", "wont": "Not changing it: why is below.", "same": "It's being fixed with another note like it.",
                              "cant_repro": "Claude couldn't make it happen: why is below.", "withdrawn": "Withdrawn."}.get(issue.close_reason or "", "Closed."),
                   open_=False, word=word if issue.close_reason != "same" else "Closed")
    if issue.state == "ready":
        if issue.confirm_by and issue.confirm_by == me_id:
            return out("yours", "Fixed and live: does it work now?")
        return out("claude", "Fixed and live: being tried.", word="Fixed")
    return out("claude", "Claude is fixing it.")


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
        word = sender_says(db, n, me_id, issue=issues.get(n.issue_id), idea=ideas.get(n.idea_id))["word"]
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
    if ev.kind == "question_withdrawn":
        return f"Claude withdrew question {ev.thing_id} (a later pick replaced it)"
    if ev.kind == "line_added":  # (its "to" is who it's for, never a state: the review of PR #417)
        who = "Claude" if ev.actor == "claude" else "askdnd" if ev.actor == "askdnd" else "An admin" if ev.actor.startswith("user:") else "Someone"
        to = {"sender": ", to its senders", "claude": ", to Claude"}.get(d.get("to") or "", "")
        return f"{who} wrote on {ev.thing} {ev.thing_id}{to}"
    if ev.thing == "item" and ev.kind.startswith("item_"):  # (a Roadmap item's Updates, and Claude's inbox)
        said = {"item_new": "Added to the Roadmap", "item_addition": "Brett added to it" + (" (said in chat)" if d.get("where") == "chat" else ""),
                "item_answered": "Claude answered an addition: " + {"in": "in scope", "later": "later", "question": "a question"}.get(d.get("answer", ""), ""),
                "item_scope": f"Claude wrote scope version {d.get('version')}", "item_agreed": f"Brett: scope version {d.get('version')} looks right",
                "item_step": "A step added" + (" for Brett" if d.get("whose") == "brett" else ""), "item_step_done": "A step done",
                "item_step_open": "A step not done after all", "item_step_removed": "A step taken off", "item_shipped": "Shipped",
                "item_not_doing": "Not doing", "item_set": "Its " + ", ".join(k for k in ("title", "why", "size", "status") if d.get(k)) + " changed",
                "item_moved": f"Moved to {str(d.get('section', '')).replace('_', ' ').title()}", "item_next": "Its next step changed"}.get(ev.kind)
        if said:
            return f"Roadmap item {ev.thing_id}: {said}"
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
    for it in db.scalars(select(FftItem).where(FftItem.section == "shipped", FftItem.result == "").order_by(FftItem.id)):  # (Brett, Nov 20)
        out.append({"kind": "no_result", "thing": "item", "id": it.id, "title": it.title,
                    "says": "Shipped with no result: write what it changed, with its numbers (feedback.py roadmap <id> set --result \"…\")."})
    for n in db.scalars(select(FftNote).where(FftNote.state == "filed", FftNote.filed_as == "question").order_by(FftNote.id)):
        out.append({"kind": "question", "thing": "note", "id": n.id, "title": title_of(n.text),
                    "says": "A question sent to Claude, waiting for its answer (feedback.py note <id> --answer \"…\")."})
    return _since(db, out)


GAP_GRACE = timedelta(minutes=30)  # (Brett, Nov 19, issue 39: what just happened isn't missed yet)


def _since(db: Session, out: list[dict]) -> list[dict]:
    """When each gap began: the last thing that happened to it (its newest event), else when it was made."""
    from app.fft.models import FftEvent

    for g in out:
        if g.get("since"):
            continue
        at = db.scalar(select(func.max(FftEvent.at)).where(FftEvent.thing == g["thing"], FftEvent.thing_id == g["id"]))
        if g["thing"] == "area":
            at = db.scalar(select(func.max(FftEvent.at)).where(FftEvent.kind == "issue_pr", FftEvent.area_id == g["id"])) or at
        row = {"issue": FftIssue, "check": FftCheck, "note": FftNote, "area": FftArea, "item": FftItem}[g["thing"]]
        g["since"] = at or getattr(db.get(row, g["id"]), "created_at", None) or rules.now()
    return out


def missed(db: Session) -> list[dict]:
    """Claude missed, as Brett sees it on Work: only what has waited longer than GAP_GRACE (Claude's own
    end-of-turn check still sees every gap at once)."""
    cut = rules.now() - GAP_GRACE
    return [g for g in gaps(db) if g["since"] <= cut]
