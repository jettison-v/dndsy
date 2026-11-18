"""Found, Fixed, Tried for people (app/fft/sending.py, app/fft/feedback_page.py, app/your_notes.py; screens 9–15 of
docs/mockups/found-fixed-tried/): sending a note, approving it, the Feedback page's issues, and Notes you sent, with
the standing rules on who sees what."""

import base64
import io

import pytest
from PIL import Image
from sqlalchemy import select

from app import access, config
from app.fft import rules, sending
from app.fft.models import FftIdea, FftIssue, FftLine, FftNote, FftPicture
from app.importer import import_bundle
from tests.roles import set_role
from tests.table_setup import BUNDLE


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


def png(colour=(200, 40, 40)) -> str:
    out = io.BytesIO()
    Image.new("RGB", (8, 6), colour).save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


FULL, SAFE, ADDED = png((200, 40, 40)), png((40, 40, 40)), png((40, 200, 40))


def send(client, text="Rest wraps on a phone.", kind="problem", **more):
    body = {"text": text, "kind": kind, "url": "/characters/1/battle", "html": "<main data-private=\"emptied\"></main>",
            "context": {"page": "Cole · Battle", "who": "player@example.com"},
            "pictures": [{"kind": "page", "full": FULL, "safe": SAFE}, {"kind": "added", "full": ADDED, "safe": None}]}
    return client.post("/feedback", json=body | more)


@pytest.fixture
def sender(admin, player, db):
    """The player, switched on to send notes (Brett's test accounts, Nov 3)."""
    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    return player


def _note(db) -> FftNote:
    return db.scalar(select(FftNote).order_by(FftNote.id.desc()))


# ------------------------------------------------------------------ sending (screen 9)


def test_only_admins_and_switched_on_accounts_send(admin, player, db):
    set_role(db, "player@example.com", "player")
    assert send(player).status_code == 404
    assert send(admin).status_code == 200
    assert send(admin, kind="").status_code == 400  # (what it is: picked each time, never for you)
    assert send(admin, text=" ").status_code == 400


def test_an_admins_note_is_filed_at_once_and_a_players_waits(admin, sender, db):
    """A standing rule (Brett, Nov 6; R1, T1): a player's note waits for an admin; an admin's is filed as it's sent."""
    r = send(admin)
    assert not r.json()["waits"] and _note(db).state == "filed" and db.get(FftIssue, _note(db).issue_id).state == "to_fix"
    r = send(sender)
    n = _note(db)
    assert r.json()["waits"] and n.state == "waiting" and n.first_name and "@" not in n.first_name
    assert "who" not in n.context  # (T2: no email kept)


def test_only_its_sender_sees_the_full_picture(admin, sender, dm, db):
    """A standing rule (CLAUDE.md › Visibility: character notes are visible to players but not the DM; T5): the page's
    picture comes as a full copy, its sender's alone, and a safe copy with their character notes covered, which an
    admin, the DM and Claude see. A picture they added is theirs to share."""
    send(sender)
    n = _note(db)
    page, added = db.scalars(select(FftPicture).where(FftPicture.note_id == n.id).order_by(FftPicture.id))
    assert page.key != page.safe_key and added.key == added.safe_key
    mine = sender.get(f"/your-notes/pictures/{page.id}")
    assert mine.status_code == 200 and mine.content == base64.b64decode(FULL.split(",")[1])
    theirs = admin.get(f"/manage/feedback/pictures/{page.id}")
    assert theirs.status_code == 200 and theirs.content == base64.b64decode(SAFE.split(",")[1])
    assert dm.get(f"/your-notes/pictures/{page.id}").status_code == 404 and dm.get(f"/manage/feedback/pictures/{page.id}").status_code in (303, 403, 404)
    shown = admin.get("/manage/feedback?tab=approve").text
    assert f"/manage/feedback/pictures/{page.id}" in shown and "data-covered" in shown


def test_a_note_sent_viewing_as_someone_keeps_no_full_copy(admin, db):
    """Sent by an admin viewing as a player: the page was the player's, so its full copy is no one's to keep."""
    set_role(db, "player@example.com", "player")
    admin.post("/view-as", data={"email": "player@example.com"})
    assert send(admin).status_code == 200
    admin.post("/view-as/stop")
    n = _note(db)
    page = db.scalar(select(FftPicture).where(FftPicture.note_id == n.id, FftPicture.kind == "page"))
    assert page.key == page.safe_key and n.context["viewing_as"] and "@" not in n.context["viewing_as"]


def test_on_staging_a_note_goes_to_askdnd_ai_with_safe_copies_only(admin, db, monkeypatch):
    """A standing rule (the audit, Nov 17; T6): staging's note reaches askdnd.ai's relay with a first name, never an
    email, and the safe copies, never the full one."""
    sent = {}
    monkeypatch.setattr(config, "STAGING", True)
    monkeypatch.setenv("FFT_RELAY_KEY", "r" * 40)
    monkeypatch.setattr(sending, "SEND", lambda url, payload, key: sent.update(url=url, payload=payload, key=key) or {"id": 7})
    r = send(admin)
    assert r.json() == {"ok": True, "id": 7, "waits": True, "said": "Sent to askdnd.ai: an admin reads it first."}
    assert sent["url"].endswith("/api/fft/relay") and "@" not in str(sent["payload"]) and FULL not in sent["payload"]["pictures"]
    assert SAFE in sent["payload"]["pictures"] and "html" not in sent["payload"] and db.scalar(select(FftNote)) is None


def test_the_line_beside_send_is_true(admin, sender, db):
    assert sender.get("/feedback/line").json()["line"] == "An admin reads it first, then Claude."
    assert admin.get("/feedback/line").json()["line"] == "It waits for Claude's next session."
    li = rules.listener(db, "main")
    li.heard_at = rules.now()
    db.flush()
    assert admin.get("/feedback/line").json() == {"line": "Claude is listening: it reads it within a minute.", "listening": True}


# ------------------------------------------------------------------ approving (screens 10, 11)


def test_feedback_is_for_admins(admin, sender, dm, db):
    send(sender)
    n = _note(db)
    for client in (sender, dm):
        assert client.get("/manage/feedback").status_code in (303, 403, 404)
        client.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})
    assert db.get(FftNote, n.id).state == "waiting"


def test_approving_as_an_issue_with_undo(admin, sender, db):
    send(sender)
    n = _note(db)
    r = admin.post(f"/manage/feedback/notes/{n.id}?tab=approve", data={"do": "issue"}, follow_redirects=False)
    assert r.status_code == 303 and n.state == "filed" and db.get(FftIssue, n.issue_id).from_player
    page = admin.get(r.headers["location"]).text
    assert f'/manage/feedback/notes/{n.id}/undo' in page  # (the corner card's Undo)
    admin.post(f"/manage/feedback/notes/{n.id}/undo")
    db.refresh(n)
    assert n.state == "waiting" and n.issue_id is None


def test_same_as_joins_without_showing_the_other_notes(admin, sender, db):
    """R2: a note joins an issue already filed; its sender hears that issue's outcome, never another reporter's words or
    the issue's title."""
    first = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="problem", text="Trah's own words")
    issue = rules.file_issue(db, "user:1", first, title="The admins' title for it")
    send(sender, text="Same here after resting.")
    n = _note(db)
    window = admin.get(f"/manage/feedback/same?note={n.id}&q=title").text
    assert "The admins&#39; title for it" in window or "The admins' title for it" in window
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "same", "issue": issue.id})
    assert n.issue_id == issue.id
    rules.add_line(db, "claude", "To everyone who sent it", issue=issue, to="sender")
    rules.add_line(db, "claude", "Between Brett and Claude", issue=issue)
    db.flush()
    mine = sender.get("/your-notes?tab=askdnd").text
    assert "Same here after resting." in mine and "To everyone who sent it" in mine
    assert "Trah&#39;s own words" not in mine and "Trah's own words" not in mine and "admins" not in mine and "Between Brett and Claude" not in mine


def test_an_idea_a_question_answered_and_declined_with_why(admin, sender, db):
    send(sender, kind="idea", text="A dice tray.")
    idea = _note(db)
    admin.post(f"/manage/feedback/notes/{idea.id}", data={"do": "idea"})
    assert idea.filed_as == "idea" and db.get(FftIdea, idea.idea_id)
    send(sender, kind="question", text="Can I roll for an NPC?")
    q = _note(db)
    admin.post(f"/manage/feedback/notes/{q.id}", data={"do": "answer", "words": "Only the DM can."})
    send(sender, text="Not a bug.")
    no = _note(db)
    admin.post(f"/manage/feedback/notes/{no.id}", data={"do": "decline", "words": "It's how the 2024 rules work."})
    assert (q.filed_as, no.state) == ("answered", "declined")
    mine = sender.get("/your-notes?tab=askdnd").text
    assert "Only the DM can." in mine and "the 2024 rules work" in mine and 'data-turn="closed"' in mine


def test_a_question_an_admin_sends_waits_on_open_for_claude_then_its_answer_comes_back(admin, db):
    """Issue 27 (Brett's round, Nov 18): an admin's question is filed for Claude to answer, but it showed nowhere in
    Feedback and its sender read it as Closed. It waits on Open under Questions for Claude, Claude's turn, and its
    sender reads that it's with Claude; once answered, the answer is theirs to read and it moves to Closed."""
    admin.post("/feedback", json={"text": "How do I end a round?", "kind": "question", "url": "/manage/testing", "html": "<main></main>",
                                  "context": {"page": "Testing"}, "pictures": []})
    q = _note(db)
    assert q.filed_as == "question"
    page = admin.get("/manage/feedback?tab=open").text
    assert 'data-group="questions"' in page and f'data-row="n{q.id}"' in page
    assert f'data-note="f{q.id}"' in admin.get("/your-notes?tab=askdnd").text
    mine = admin.get(f"/your-notes?tab=askdnd&note=f{q.id}").text
    assert 'data-turn="claude"' in mine and 'data-turn="closed"' not in mine
    rules.answer_note(db, "claude", q, "Press End round on the round's card.")
    db.flush()
    assert f'data-row="n{q.id}"' not in admin.get("/manage/feedback?tab=open").text
    assert f'data-row="n{q.id}"' in admin.get("/manage/feedback?tab=closed").text
    assert "Press End round on the round" in admin.get(f"/your-notes?tab=askdnd&note=f{q.id}").text


# ------------------------------------------------------------------ an issue (screens 13, 14)


def test_an_issue_moves_closes_with_a_reason_its_senders_read_and_reopens(admin, sender, db):
    send(sender)
    n = _note(db)
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})
    i = db.get(FftIssue, n.issue_id)
    page = admin.get(f"/manage/feedback?tab=open&open=i{i.id}").text
    assert f'data-fft-issue="{i.id}"' in page and "/manage/feedback/close?issue=" in page
    assert "Close it: why?" in admin.get(f"/manage/feedback/close?issue={i.id}").text
    admin.post(f"/manage/feedback/issues/{i.id}", data={"do": "close", "reason": "wont", "words": "It's as designed.", "seen": "to_fix"})
    assert i.state == "closed" and i.close_reason == "wont"
    assert "It&#39;s as designed." in sender.get("/your-notes?tab=askdnd").text or "It's as designed." in sender.get("/your-notes?tab=askdnd").text
    admin.post(f"/manage/feedback/issues/{i.id}", data={"do": "reopen"})
    assert i.state == "to_fix" and i.reopened
    r = admin.post(f"/manage/feedback/issues/{i.id}", data={"do": "close", "reason": "wont", "seen": "closed"})
    assert r.status_code == 409 and i.state == "to_fix"  # (R14: a stale page's change is refused)


def test_a_fix_a_player_prompted_waits_for_your_ok(admin, sender, db):
    """R17: Claude's fix for a player's note waits for Brett's OK to merge."""
    send(sender)
    n = _note(db)
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})
    i = db.get(FftIssue, n.issue_id)
    rules.fix_ready(db, "claude", i, "https://github.com/x/y/pull/1")
    db.flush()
    assert 'data-do="ok_merge"' in admin.get(f"/manage/feedback?tab=open&open=i{i.id}").text
    admin.post(f"/manage/feedback/issues/{i.id}", data={"do": "ok_merge"})
    assert i.state == "fixing" and rules.may_merge(db, i)[0]


def test_lines_to_claude_stay_between_you_and_claude(admin, sender, db):
    send(sender)
    n = _note(db)
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})
    i = db.get(FftIssue, n.issue_id)
    admin.post(f"/manage/feedback/issues/{i.id}", data={"do": "line", "to": "claude", "words": "Check the Wizard too."})
    admin.post(f"/manage/feedback/issues/{i.id}", data={"do": "line", "to": "senders", "words": "Thanks: it's being fixed."})
    mine = sender.get("/your-notes?tab=askdnd").text
    assert "it&#39;s being fixed" in mine and "Check the Wizard" not in mine


# ------------------------------------------------------------------ Notes you sent (screen 15)


def test_a_players_reply_waits_and_does_it_work_now(admin, sender, db):
    """T1: what a player adds waits for approval before Claude reads it. R5: the player whose note prompted a fix says
    whether it works now."""
    send(sender)
    n = _note(db)
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})
    sender.post(f"/your-notes/notes/{n.id}", data={"text": "It also happens on Battle."})
    line = db.scalar(select(FftLine).where(FftLine.note_id == n.id, FftLine.who == "sender"))
    assert line is not None and not line.approved
    i = db.get(FftIssue, n.issue_id)
    assert 'data-do="approve-line"' in admin.get(f"/manage/feedback?tab=open&open=i{i.id}").text
    admin.post(f"/manage/feedback/lines/{line.id}")
    assert line.approved
    rules.start_fixing(db, "claude", i)
    rules.fix_live(db, "askdnd", i, "abc")
    db.flush()
    page = sender.get("/your-notes?tab=askdnd").text
    assert 'data-works="yes"' in page and 'data-turn="yours"' in page
    sender.post(f"/your-notes/notes/{n.id}/works", data={"answer": "yes"})
    assert i.state == "closed" and i.close_reason == "works"


def test_new_reply_is_counted_once_and_cleared_by_reading(admin, sender, db):
    send(sender)
    n = _note(db)
    assert sender.get("/your-notes/news").json()["tabs"]["askdnd"] == 0
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})
    news = sender.get("/your-notes/news").json()
    assert news["tabs"]["askdnd"] == 1 and len(news["cards"]) == 1
    assert sender.get("/your-notes/news").json()["cards"] == []  # (one card per change)
    sender.get("/your-notes?tab=askdnd")
    assert sender.get("/your-notes/news").json()["tabs"]["askdnd"] == 0


def test_someone_elses_note_is_never_yours(admin, sender, db):
    send(admin, text="Brett's own note")
    n = _note(db)
    assert "Brett&#39;s own note" not in sender.get("/your-notes?tab=askdnd").text
    assert sender.post(f"/your-notes/notes/{n.id}", data={"text": "x"}).status_code == 404
    pic = db.scalar(select(FftPicture).where(FftPicture.note_id == n.id))
    assert sender.get(f"/your-notes/pictures/{pic.id}").status_code == 404


def test_a_page_with_a_nul_character_still_sends(admin, db):
    """Sentry ASKDND-V2-F (Nov 4): a page's text carried a NUL character, which Postgres refuses: every JSON body drops it."""
    assert send(admin, html="<main>Bag\u0000 of Holding</main>", context={"page": "Cole\u0000"}).status_code == 200
    n = _note(db)
    assert n.html == "<main>Bag of Holding</main>" and n.context["page"] == "Cole"
