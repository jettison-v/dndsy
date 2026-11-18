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


def test_a_note_that_only_moved_on_says_updated_and_one_with_a_reply_says_new_reply(admin, sender, db):
    """Issue 25 (Brett's round, Nov 18): a note whose status had only moved on said "new reply" in Notes you sent. It
    says updated until someone writes to its sender; then new reply. (Opening the tab shows what's new, then clears it.)"""
    send(sender, text="Rest wraps on a phone.")
    n = _note(db)
    assert "data-new-reply" not in sender.get("/your-notes?tab=askdnd").text  # (just sent: nothing new to its sender)
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})  # (approved: it moved on, nobody wrote)
    assert 'data-new-reply="moved"' in sender.get("/your-notes?tab=askdnd").text
    rules.add_line(db, "claude", "Thanks: it's being fixed.", issue=db.get(FftIssue, n.issue_id), to="sender")
    db.flush()
    assert 'data-new-reply="reply"' in sender.get("/your-notes?tab=askdnd").text


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


# ------------------------------------------------------------------ the reader in sections (Brett's pick A, issue 4)


def test_an_issue_reads_in_sections_its_new_lines_marked_until_opened(admin, sender, db):
    """Issues 4, 31, 32 (Brett's round, Nov 18): the reader "all just blends together". An issue reads in sections, Where
    it stands, What was found, Conversation, then History folded; a note's words come before its pictures, in a part of
    their own; each line says when, and what was said since you last opened the issue is marked New (never your own
    words), until you open it."""
    from datetime import timedelta

    from app.fft.models import FftSeen
    from app.models import User

    send(sender)
    n = _note(db)
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})
    issue = db.get(FftIssue, n.issue_id)
    me = db.scalar(select(User).where(User.email == "admin@example.com"))
    if me is None:
        me = User(email="admin@example.com", name="Dev Admin")
        db.add(me)
        db.flush()
    old = rules.add_line(db, "claude", "Seen this one already.", issue=issue)
    old.created_at = rules.now() - timedelta(hours=3)
    seen = db.scalar(select(FftSeen).where(FftSeen.user_id == me.id, FftSeen.issue_id == issue.id))  # (approving it opened it)
    if seen is None:
        seen = FftSeen(user_id=me.id, issue_id=issue.id, at=rules.now())
        db.add(seen)
    seen.at = rules.now() - timedelta(hours=1)
    newer = rules.add_line(db, "claude", "Something new since then.", issue=issue)
    mine = rules.add_line(db, "user:1", "My own words.", issue=issue, user_id=me.id)
    db.flush()
    page = admin.get(f"/manage/feedback?tab=open&open=i{issue.id}").text
    order = [page.index(f'data-sec="{k}"') for k in ("stands", "found", "talk", "history")]
    assert order == sorted(order)  # (in that order)
    report = page[page.index(f'data-report="{n.id}"'):]
    assert report.index('class="fft-words"') < report.index('class="fft-thumbs"')  # (words first, its pictures apart)
    assert f'data-line="{newer.id}" data-new' in page and f'data-line="{old.id}" data-new' not in page
    assert f'data-line="{mine.id}" data-new' not in page  # (never your own words)
    assert 'data-clock="when"' in page  # (each line says when)
    again = admin.get(f"/manage/feedback?tab=open&open=i{issue.id}").text
    assert "data-new" not in again  # (opened: seen)


def test_found_on_a_check_lists_what_a_checks_try_turned_up(admin, db):
    """Issue 33 (Brett's question, Nov 18: "What does From checks mean?"): the chip said neither of the two things it
    showed. Found on a check lists the issues a check's try turned up; an issue a check is only written for isn't one."""
    from app.fft.models import FftCheck, FftTry, FftTryIssue

    found = rules.new_issue(db, "claude", "Turned up by a check")
    written_for = rules.new_issue(db, "claude", "A check was written for it")
    db.flush()
    c = rules.write_check(db, "claude", title="A check", steps=["Look."], expect="It shows.", issue_ids=[written_for.id])
    db.flush()
    t = FftTry(check_id=c.id, version=1, device="laptop", result="failed")
    db.add(t)
    db.flush()
    db.add(FftTryIssue(try_id=t.id, issue_id=found.id))
    db.flush()
    page = admin.get("/manage/feedback?tab=open&chip=checks").text
    assert "Found on a check" in page and f'data-row="i{found.id}"' in page and f'data-row="i{written_for.id}"' not in page
    assert db.get(FftCheck, c.id)  # (still there: it just isn't what the chip lists)


def test_claudes_addresses_are_links_a_senders_are_not(admin, sender, db):
    """Brett's note 105 (Nov 17), carried into Found, Fixed, Tried: Claude's words show their https:// addresses as
    links, in Feedback and on Notes you sent; a sender's words never become links."""
    send(sender, text="See https://example.com/mine please.")
    n = _note(db)
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})
    issue = db.get(FftIssue, n.issue_id)
    rules.add_line(db, "claude", "The mockup: https://claude.ai/artifact/abc.", issue=issue, to="sender")
    db.flush()
    page = admin.get(f"/manage/feedback?tab=open&open=i{issue.id}").text
    assert '<a href="https://claude.ai/artifact/abc" target="_blank" rel="noopener">' in page
    assert 'href="https://example.com/mine' not in page  # (the sender's own words stay words)
    assert '<a href="https://claude.ai/artifact/abc"' in sender.get("/your-notes?tab=askdnd").text


def test_a_standing_rule_the_page_as_drawn_never_keeps_a_players_private_parts(admin, sender, db):
    """A standing rule (Brett, 2026-10-17: character notes are visible to players but NOT the DM; T5): the page as drawn
    is kept with every [data-private] part emptied, whatever the browser sent (the review of PR #417: only app.js
    emptied them; an older app.js in a tab left open would have sent them). An admin reading it sees the emptied copy."""
    page = ('<html><body><aside class="peek"><div data-private class="nt"><p>My secret plan</p><img src="x"></div>'
            '<p>The party</p><input data-private value="hidden words"></aside></body></html>')
    send(sender, html=page)
    n = _note(db)
    assert "My secret plan" not in n.html and "hidden words" not in n.html and "The party" in n.html
    assert n.html.count('data-private="emptied"') == 2
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue"})
    drawn = admin.get(f"/manage/feedback/notes/{n.id}/page").text
    assert "My secret plan" not in drawn and "The party" in drawn


def test_every_picture_added_to_a_note_shows_and_one_without_a_safe_copy_is_never_served_viewing_as(admin, sender, db):
    """The review of PR #417: Add to it takes up to four screenshots, and Notes you sent showed only the last; and a
    carried-over picture with no safe copy made the page fail for an admin viewing as its sender."""
    send(sender)
    n = _note(db)
    shots = [("pics", (f"s{i}.png", base64.b64decode(ADDED.split(",")[1]), "image/png")) for i in range(3)]
    assert sender.post(f"/your-notes/notes/{n.id}", data={"text": "Three more"}, files=shots).status_code in (200, 303)
    mine = sender.get(f"/your-notes?tab=askdnd&note=f{n.id}").text
    line_pics = db.scalars(select(FftPicture).where(FftPicture.line_id.isnot(None))).all()
    assert len(line_pics) == 3 and all(f"/your-notes/pictures/{p.id}" in mine for p in line_pics)
    page = db.scalar(select(FftPicture).where(FftPicture.note_id == n.id, FftPicture.kind == "page"))
    page.safe_key = None  # (as carry.py keeps a player's carried-over page picture)
    db.flush()
    set_role(db, "player@example.com", "player")
    admin.post("/view-as", data={"email": "player@example.com"})
    assert admin.get(f"/your-notes/pictures/{page.id}").status_code == 404
    admin.post("/view-as/stop")
