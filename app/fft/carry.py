"""Today's open Feedback and Testing, carried over once into Found, Fixed, Tried (the build plan › How it ships): run
by the migration that turns the new tool on, and safe to run again (it carries nothing twice).

- **Areas** keep their order, under the standing **Fixes and polish** item (Brett moves them on Where it stands).
- **Notes**: one waiting for approval waits again; an open one (with Claude, Claude asks, planned) is filed: a problem
  or a question as an issue (Claude's to fix; Claude's open question comes over as a question for Brett), an idea as an
  idea (planned: on the Roadmap). Its conversation comes as lines, its pictures as pictures: a player's page picture had
  no safe copy, so only its sender sees it; one they added is theirs to share. Done and closed notes stay where they
  were, in the old tables, until those are dropped.
- **Checks** still to try, failed or being fixed come as version 1 (Claude tried them before, so their own try is
  passed): a failed one with a failed try naming its issues; a skipped one as Later; the Mac Mini's as the Mini's.
  A player's Does it work now? stays with its note (done), and a passed one stays behind.
- Claude's inbox starts after the carry-over (the read mark moves past it): `feedback.py areas` and `issues` list it all."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.fft import rules
from app.fft.models import (
    FftArea,
    FftCheck,
    FftCheckVersion,
    FftEvent,
    FftIdea,
    FftIssue,
    FftItem,
    FftLine,
    FftListener,
    FftNote,
    FftPicture,
    FftQuestion,
)
from app.models import Area, Check, Feedback, FeedbackPicture

ACTOR = "askdnd"
OPEN = ("new", "question", "planned")
KIND = {"broken": "problem", "idea": "idea", "question": "question"}
DEVICES = {"iphone": ["iphone"], "claude": ["mac_mini"]}  # (every other setup: the laptop)


def _role(sender: str) -> str:
    said = sender.rsplit("(", 1)[-1].rstrip(")").strip() if "(" in sender else ""
    return said if said in rules.ROLES else "member"


def _first(sender: str) -> str:
    return (sender.split(" (")[0].split(" ")[0] or "Someone")[:60]


def carry_over(db: Session) -> dict:
    """Carry today's open work over; returns what came, by kind. Does nothing the second time."""
    if db.scalar(select(FftEvent.id).where(FftEvent.kind == "carried_over")):
        return {}
    done = {"areas": 0, "notes": 0, "issues": 0, "ideas": 0, "questions": 0, "checks": 0}
    item = db.scalar(select(FftItem).where(FftItem.standing.is_(True)))
    if item is None:
        item = FftItem(title="Fixes and polish", section="now", standing=True,
                       place=(db.scalar(select(func.max(FftItem.place))) or 0) + 1)
        db.add(item)
        db.flush()
    areas = {}
    for a in db.scalars(select(Area).order_by(Area.place, Area.id)):
        new = FftArea(item_id=item.id, title=a.title[:80], place=a.place)
        db.add(new)
        db.flush()
        areas[a.id] = new.id
        done["areas"] += 1
    issues = {}  # an old note's id -> the issue it became
    for fb in db.scalars(select(Feedback).where(Feedback.status.in_(("review", *OPEN))).order_by(Feedback.id)):
        role = _role(fb.sender or "")
        admin = role == "admin"
        note = FftNote(user_id=fb.user_id, first_name=_first(fb.sender or ""), role=role, kind=KIND.get(fb.kind, "problem"),
                       text=fb.text, url=fb.url or "", page=str((fb.context or {}).get("page") or "")[:120],
                       context=rules._clean_context(fb.context or {}), html=fb.html or "", staging=bool((fb.context or {}).get("staging")))
        db.add(note)
        db.flush()
        done["notes"] += 1
        waiting = fb.status == "review"
        if not waiting:
            if note.kind == "idea":
                idea = FftIdea(title=(fb.title or rules._first_words(fb.text))[:120], state="roadmap" if fb.status == "planned" else "new")
                db.add(idea)
                db.flush()
                note.state, note.filed_as, note.idea_id = "filed", "idea", idea.id
                done["ideas"] += 1
            else:
                issue = FftIssue(title=(fb.title or rules._first_words(fb.text))[:120], area_id=areas.get(fb.area_id),
                                 from_player=not admin, pr=fb.pr or "", state="to_fix")
                db.add(issue)
                db.flush()
                note.state, note.filed_as, note.issue_id = "filed", "issue", issue.id
                issues[fb.id] = issue
                done["issues"] += 1
        for m in fb.thread or []:
            if m.get("kind") or not str(m.get("text") or "").strip():
                continue  # (an old change of kind is in the old note; nothing said)
            who = {"sender": "sender", "claude": "claude"}.get(m.get("who"), "admin")
            db.add(FftLine(note_id=note.id, who=who, to="sender" if m.get("to") == "sender" else "", text=str(m["text"])[:4000],
                           approved=not (waiting and who == "sender")))
        if fb.shot_key:
            db.add(FftPicture(note_id=note.id, kind="page", key=fb.shot_key, safe_key=fb.shot_key if admin else None))
        if fb.pasted_key:
            db.add(FftPicture(note_id=note.id, kind="added", key=fb.pasted_key, safe_key=fb.pasted_key))
        for p in db.scalars(select(FeedbackPicture).where(FeedbackPicture.feedback_id == fb.id)):
            if any(c.get("pic") == p.id for m in fb.thread or [] for c in ((m.get("ask") or {}).get("choices") or [])):
                continue  # (Claude's own picture for a design pick: not the sender's)
            db.add(FftPicture(note_id=note.id, kind="added", key=p.key, safe_key=p.key))
        if fb.status == "question" and fb.id in issues:
            ask = next((m for m in reversed(fb.thread or []) if m.get("who") == "claude" and m.get("to") != "sender" and not m.get("kind")), None)
            if ask is not None:
                choices = [{"label": c.get("label", "")[:120], "detail": (c.get("detail") or "")[:300]} for c in ((ask.get("ask") or {}).get("choices") or [])]
                db.add(FftQuestion(about="issue", about_id=issues[fb.id].id, text=str(ask.get("text") or "")[:4000], choices=choices,
                                   mine=(ask.get("ask") or {}).get("mine")))
                issues[fb.id].state = "asks"
                done["questions"] += 1
    for c in db.scalars(select(Check).where(Check.status.in_(("ready", "again", "failed", "fixed", "skipped", "claude"))).order_by(Check.place, Check.id)):
        if c.setup == "player":
            continue
        check = FftCheck(area_id=areas.get(c.area_id), title=c.title[:160], devices=DEVICES.get("claude" if c.status == "claude" else c.setup, ["laptop"]),
                         minutes=c.minutes or 2, place=c.place, as_character=c.as_character, makes=c.makes, preflight="passed")
        db.add(check)
        db.flush()
        db.add(FftCheckVersion(check_id=check.id, version=1, path=c.path or "", steps=[x.strip() for x in (c.do or "").splitlines() if x.strip()],
                               expect=c.expect or "", why=c.said or ""))
        found = [issues[f.id] for f in db.scalars(select(Feedback).where(Feedback.check_id == c.id)) if f.id in issues]
        if c.feedback_id in issues:
            found.append(issues[c.feedback_id])
        for i in found:
            rules.link_issue(db, ACTOR, check, i)
        if c.status in ("failed", "fixed") and found:
            rules.record_try(db, ACTOR, check, result="failed", found=[rules.Found(issue_id=i.id) for i in found], why="Carried over")
            for i in found if c.status == "fixed" else []:  # (Claude's fix is on its way: after the try, which says still to fix)
                i.state, i.pr = "fixing", i.pr or c.pr or ""
        elif c.status == "skipped":
            rules.record_try(db, ACTOR, check, result="cant", cant_kind="later", why="Skipped before the carry-over")
        done["checks"] += 1
    rules._event(db, ACTOR, "carried_over", "item", item.id, **done)
    db.flush()
    last = db.scalar(select(func.max(FftEvent.id))) or 0
    li = db.scalar(select(FftListener).where(FftListener.name == "main")) or FftListener(name="main")
    li.read_id = max(li.read_id or 0, last)
    db.add(li)
    for n in db.scalars(select(FftNote).where(FftNote.user_id.isnot(None))):
        from app.fft import views

        n.seen = n.told = views.marker(db, n, n.user_id)  # (no "new reply" for what they'd already seen)
    return done
