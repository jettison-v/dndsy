"""Today's open Feedback and Testing carried over once into Found, Fixed, Tried (app/fft/carry.py; the build plan ›
How it ships): what's open comes, what's done stays, nothing comes twice, and the standing rules hold for what came."""

import base64
import io

from PIL import Image
from sqlalchemy import func, select

from app import files, picks
from app.fft import rules
from app.fft.carry import carry_over
from app.fft.models import FftArea, FftCheck, FftIdea, FftIssue, FftLine, FftListener, FftNote, FftPicture, FftQuestion, FftTry
from app.importer import import_bundle
from app.models import Area, Campaign, Check, Feedback, FeedbackPicture, User
from tests.table_setup import BUNDLE


def _png(db, colour) -> str:
    out = io.BytesIO()
    Image.new("RGB", (6, 4), colour).save(out, "PNG")
    return files.put(db, db.scalar(select(Campaign.id)), out.getvalue(), "image/png")


def test_open_work_carries_over_once(db):
    import_bundle(db, BUNDLE)
    pat = picks.user_row(db, {"email": "player@example.com"})
    if pat is None:
        pat = User(email="player@example.com", name="Pat Player")
        db.add(pat)
        db.flush()
    manage, menu = Area(title="Manage", place=2), Area(title="Menu bar", place=1)
    db.add_all([manage, menu])
    db.flush()
    shot, pasted, added = _png(db, (200, 0, 0)), _png(db, (0, 200, 0)), _png(db, (0, 0, 200))
    waiting = Feedback(user_id=pat.id, sender="Pat Player (player)", text="Rests are wrong.", kind="broken", status="review",
                       context={"page": "Cole · Battle", "signed_in_as": "Pat (player)", "who": "player@example.com"}, shot_key=shot,
                       thread=[{"who": "sender", "text": "And it happens twice."}])
    open_ = Feedback(user_id=pat.id, sender="Pat Player (player)", text="The menu wraps.", kind="broken", status="new", area_id=menu.id,
                     pasted_key=pasted, thread=[{"who": "you", "to": "sender", "text": "Thanks, Claude has it."}, {"who": "you", "text": "Broken → Idea", "kind": "idea"}])
    asked = Feedback(sender="Brett (admin)", text="Manage's list is long.", kind="broken", status="question", area_id=manage.id,
                     thread=[{"who": "claude", "text": "Fold it, or tabs?", "ask": {"choices": [{"label": "Fold"}, {"label": "Tabs"}], "mine": 0}}])
    idea = Feedback(sender="Brett (admin)", text="A dice tray.", kind="idea", status="planned")
    done = Feedback(sender="Brett (admin)", text="Old and done.", kind="broken", status="done")
    db.add_all([waiting, open_, asked, idea, done])
    db.flush()
    db.add(FeedbackPicture(feedback_id=open_.id, key=added))
    failed = Check(title="The menu holds", status="failed", area_id=menu.id, do="Open the menu.\nPress [Close].", expect="It closes.", path="/party", history=[])
    ready = Check(title="Manage folds", status="ready", area_id=manage.id, do="Open Manage.", expect="It folds.", history=[])
    mini = Check(title="The Mini's seats", status="claude", setup="claude", do="Run it.", history=[])
    gone = Check(title="Passed already", status="passed", do="x", history=[])
    player = Check(title="Pat's fix", status="again", setup="player", feedback_id=done.id, do="x", history=[])
    db.add_all([failed, ready, mini, gone, player])
    db.flush()
    open_.check_id = failed.id
    db.flush()

    came = carry_over(db)
    db.flush()
    assert came == {"areas": 2, "notes": 4, "issues": 2, "ideas": 1, "questions": 1, "checks": 3}
    assert carry_over(db) == {} and db.scalar(select(func.count()).select_from(FftNote)) == 4  # (once)

    areas = {a.title: a for a in db.scalars(select(FftArea))}
    assert areas["Menu bar"].place < areas["Manage"].place  # (their order)
    w = db.scalar(select(FftNote).where(FftNote.text == "Rests are wrong."))
    assert w.state == "waiting" and w.first_name == "Pat" and w.role == "player" and "signed_in_as" not in w.context and "who" not in w.context
    assert not db.scalar(select(FftLine).where(FftLine.note_id == w.id)).approved  # (T1: their added words wait too)
    page = db.scalar(select(FftPicture).where(FftPicture.note_id == w.id))
    assert page.key == shot and page.safe_key is None  # (T5: a player's old page picture has no safe copy: only they see it)
    o = db.scalar(select(FftNote).where(FftNote.text == "The menu wraps."))
    issue = db.get(FftIssue, o.issue_id)
    assert issue.state == "to_fix" and issue.area_id == areas["Menu bar"].id and issue.from_player
    assert [x.text for x in db.scalars(select(FftLine).where(FftLine.note_id == o.id))] == ["Thanks, Claude has it."]
    assert {p.key for p in db.scalars(select(FftPicture).where(FftPicture.note_id == o.id))} == {pasted, added}
    q = db.scalar(select(FftQuestion))
    assert q.text == "Fold it, or tabs?" and [c["label"] for c in q.choices] == ["Fold", "Tabs"] and q.mine == 0
    assert db.get(FftIssue, q.about_id).state == "asks"
    assert db.scalar(select(FftIdea)).state == "roadmap"
    assert db.scalar(select(FftNote).where(FftNote.text == "Old and done.")) is None

    checks = {c.title: c for c in db.scalars(select(FftCheck))}
    assert set(checks) == {"The menu holds", "Manage folds", "The Mini's seats"}
    assert rules.check_state(db, checks["The menu holds"])["state"] == "failed" and db.scalar(select(FftTry).where(FftTry.check_id == checks["The menu holds"].id))
    assert rules.check_state(db, checks["Manage folds"])["state"] == "to_try" and checks["The Mini's seats"].devices == ["mac_mini"]
    assert db.scalar(select(FftListener).where(FftListener.name == "main")).read_id > 0  # (Claude's inbox starts after it)
