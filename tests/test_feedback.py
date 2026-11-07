"""Feedback for Claude (app/feedback.py; Brett, 2026-11-03, docs/mockups/feedback-queue/): a note from any page, kept
in a queue for Claude, who reads and moves it on with its own key."""

import base64
import io

import pytest
from PIL import Image
from sqlalchemy import select

from app import access, config
from app.importer import import_bundle
from app.models import Feedback, User
from tests.table_setup import BUNDLE


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


def png() -> str:
    out = io.BytesIO()
    Image.new("RGB", (8, 6), (200, 40, 40)).save(out, "PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def note(client, text="Speed should show the swim speed too.", **more):
    return client.post("/feedback", json={"text": text, "url": "http://localhost/characters/1/battle",
                                           "context": {"page": "Cole · Battle", "window": "1440 × 900", "browser": "Chrome 132 on macOS",
                                                       "extension": "0.9.9", "pointed": {"label": "Speed", "path": "main > div.nt"}},
                                           "html": "<html><body>Battle</body></html>", "shot": png(), **more})


def test_an_admin_sends_a_note_with_the_page(admin, db):
    r = note(admin, pasted=png())
    assert r.status_code == 200 and r.json()["waiting"] == 1
    fb = db.scalar(select(Feedback))
    assert fb.status == "new" and fb.sender.endswith("(admin)") and fb.context["pointed"]["label"] == "Speed"
    assert fb.shot_key and fb.pasted_key and fb.html.startswith("<html>") and fb.context["server_at"]
    page = admin.get("/manage/feedback").text
    assert "Speed should show the swim speed too." in page and "pointed at Speed" in page
    assert admin.get(f"/manage/feedback/{fb.id}/shot").headers["content-type"] == "image/png"
    as_text = admin.get(f"/manage/feedback/{fb.id}/page")
    assert as_text.headers["content-type"].startswith("text/plain") and as_text.text == "<html><body>Battle</body></html>"  # (never run here)


def test_only_admins_and_switched_on_accounts_send_and_only_admins_read(admin, player, db):
    """Brett, Nov 3: he tests as a player too. An account an admin switches on sends with \\ (no menu item, so its menus
    stay a player's); the queue stays admins'."""
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    assert note(player).status_code == 404
    assert 'data-feedback' not in player.get("/help").text.split("<body", 1)[1].split(">", 1)[0]
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    assert db.scalar(select(User).where(User.email == "player@example.com")).feedback
    access.invalidate()
    body = player.get("/help").text
    assert "data-feedback" in body.split("<body", 1)[1].split(">", 1)[0] and 'id="fb-win"' in body
    assert "data-fb-open" not in body  # (no menu item: a player's menus)
    assert "data-fb-open" in admin.get("/help").text
    r = note(player, text="The Rest button wraps.")
    assert r.status_code == 200 and db.scalar(select(Feedback)).sender.endswith("(player)")
    assert player.get("/manage/feedback", follow_redirects=False).status_code in (303, 403)
    assert player.get(f"/manage/feedback/{db.scalar(select(Feedback)).id}/page", follow_redirects=False).status_code in (303, 403)


def test_a_page_with_a_nul_character_still_sends(admin, db):
    """Sentry ASKDND-V2-F (Nov 4): a page's text carried a NUL character, which Postgres refuses: every JSON body drops it."""
    r = note(admin, html="<html><body>Bag\u0000 of Holding</body></html>", context={"page": "Cole\u0000"})
    assert r.status_code == 200
    fb = db.scalar(select(Feedback))
    assert fb.html == "<html><body>Bag of Holding</body></html>" and fb.context["page"] == "Cole"


def test_a_note_needs_words(admin):
    assert note(admin, text="  ").status_code == 400


def test_claude_reads_asks_and_closes_with_its_own_key(admin, db, monkeypatch):
    """Claude can't sign in to beta: its key reads the queue and moves each note on; Brett's answer makes it new again."""
    note(admin)
    fb = db.scalar(select(Feedback))
    assert admin.get("/api/feedback").status_code == 404  # (no key set: the API answers nothing)
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)
    claude = {"X-Feedback-Key": "k" * 40}
    assert admin.get("/api/feedback", headers={"X-Feedback-Key": "wrong"}).status_code == 404
    items = admin.get("/api/feedback", headers=claude).json()["items"]
    assert [i["id"] for i in items] == [fb.id] and items[0]["shots"] == ["shot"] and "html" not in items[0]
    assert admin.get(f"/api/feedback/{fb.id}", headers=claude).json()["html"].startswith("<html>")
    assert admin.get(f"/api/feedback/{fb.id}/shot", headers=claude).content[:4] == b"\x89PNG"
    admin.post(f"/api/feedback/{fb.id}", headers=claude, json={"note": "The tile, or Speed's panel?"})
    db.refresh(fb)
    assert fb.status == "question" and fb.thread[-1]["who"] == "claude"
    assert "The tile, or Speed&#39;s panel?" in admin.get("/manage/feedback?tab=question").text
    admin.post(f"/manage/feedback/{fb.id}", data={"to": "answer", "answer": "The tile."})
    db.refresh(fb)
    assert fb.status == "new" and fb.thread[-1] == {**fb.thread[-1], "who": "you", "text": "The tile."}
    admin.post(f"/api/feedback/{fb.id}", headers=claude, json={"status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/190"})
    db.refresh(fb)
    assert fb.status == "done" and fb.pr.endswith("/190")
    assert admin.get("/api/feedback", headers=claude).json()["items"] == []  # (done: out of the open queue)


def test_viewing_as_someone_a_note_is_still_the_admins(admin, db):
    """View as refuses every change; a note for Claude is the admin's own, and says whom they were viewing as."""
    admin.post("/view-as", data={"email": "player@example.com"})
    r = note(admin)
    assert r.status_code == 200
    fb = db.scalar(select(Feedback))
    assert fb.sender.endswith("(admin)") and fb.context.get("viewing_as")


def test_the_admin_menu_counts_whats_waiting_for_you(admin, db):
    """The Admin menu's count is what needs an admin: the table's notes to approve and Claude's questions (an
    admin's own note goes straight to Claude)."""
    note(admin)
    slug = db.scalar(select(__import__("app.models", fromlist=["Campaign"]).Campaign.slug))
    assert admin.get(f"/c/{slug}/manage/counts").json()["feedback"] == 0
    db.scalar(select(Feedback)).status = "question"
    db.flush()
    assert admin.get(f"/c/{slug}/manage/counts").json()["feedback"] == 1


def test_a_note_from_the_table_waits_for_an_admins_approval(admin, player, db, monkeypatch):
    """Brett, Nov 6: his table sends notes too, and each waits for him before Claude sees it. Approve sends it to
    Claude, Delete drops it, adding to it approves it; Claude's queue never holds one waiting."""
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    r = note(player, text="The Rest button wraps.")
    assert r.status_code == 200 and r.json()["review"]
    fb = db.scalar(select(Feedback))
    assert fb.status == "review"
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)
    claude = {"X-Feedback-Key": "k" * 40}
    assert admin.get("/api/feedback", headers=claude).json()["items"] == []  # (not Claude's yet)
    page = admin.get("/manage/feedback").text  # (opens on Waiting for you while there's one)
    assert 'href="?tab=review" class="on"' in page and "Approve: send to Claude" in page
    slug = db.scalar(select(__import__("app.models", fromlist=["Campaign"]).Campaign.slug))
    assert "from the table to approve" in admin.get(f"/c/{slug}/manage").text
    admin.post(f"/manage/feedback/{fb.id}", data={"to": "new"})
    db.expire_all()
    assert db.get(Feedback, fb.id).status == "new" and [i["id"] for i in admin.get("/api/feedback", headers=claude).json()["items"]] == [fb.id]
    second = Feedback(text="Delete me", sender="x (player)", status="review")
    third = Feedback(text="Add to me", sender="x (player)", status="review")
    db.add_all([second, third])
    db.flush()
    admin.post(f"/manage/feedback/{second.id}", data={"to": "deleted"})
    admin.post(f"/manage/feedback/{third.id}", data={"to": "answer", "answer": "It's on Battle too."})
    db.expire_all()
    assert db.get(Feedback, second.id).status == "deleted" and db.get(Feedback, third.id).status == "new"
    assert note(admin).json()["review"] is False and db.scalar(select(Feedback).order_by(Feedback.id.desc())).status == "new"


def test_a_note_can_be_added_to_any_time(admin, db):
    """Feedback 18 (Brett, Nov 5): something forgotten goes on the note itself, which goes back to Claude (a planned one
    stays planned)."""
    note(admin)
    fb = db.scalar(select(Feedback))
    assert "Add to this note" in admin.get("/manage/feedback?tab=new").text
    admin.post(f"/manage/feedback/{fb.id}", data={"to": "planned"})
    admin.post(f"/manage/feedback/{fb.id}", data={"to": "answer", "answer": "I retried from the extension too."})
    db.refresh(fb)
    assert fb.status == "planned" and fb.thread[-1]["text"] == "I retried from the extension too."
    admin.post(f"/manage/feedback/{fb.id}", data={"to": "done"})
    admin.post(f"/manage/feedback/{fb.id}", data={"to": "answer", "answer": "It's back."})
    db.refresh(fb)
    assert fb.status == "new" and len(fb.thread) == 2


def test_only_the_tabs_that_need_you_have_a_badge(admin, db):
    """Feedback 21 (Brett, Nov 5): Done has nothing to act on, so its count is plain, not a badge."""
    note(admin)
    fb = db.scalar(select(Feedback))
    admin.post(f"/manage/feedback/{fb.id}", data={"to": "done"})
    page = admin.get("/manage/feedback?tab=new").text
    done = page.split('href="?tab=done"')[1].split("</a>")[0]
    assert "mcount" not in done and ">1<" in done


def test_your_feedback_shows_a_player_their_notes_and_closes_the_loop(admin, player, dm, db, monkeypatch):
    """Brett, Nov 7: a feedback workflow for the players who send it. Your notes › About askdnd lists each sender's own notes and
    where they stand in their words; replies meant for them (from an admin on the queue, or Claude with its key) show
    there, never the admin's and Claude's notes to each other; Add to it goes back to an admin first (a player's words
    reach Claude only once approved, Brett Nov 6); a corner card says once when a note moves."""
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    note(player, text="The Rest button wraps.")
    fb = db.scalar(select(Feedback))
    assert 'href="/your-notes"' in player.get("/help").text  # (the account menu and More)
    page = player.get("/your-notes?tab=askdnd").text
    assert "The Rest button wraps." in page and "Waiting for an admin" in page and "Battle</body>" not in page
    assert [c["text"] for c in player.get("/your-notes/news").json()["cards"]] == []  # (seen on the page: nothing to tell)
    # Approved, then Claude's question to the admin (not for the player) and a reply meant for the player
    admin.post(f"/manage/feedback/{fb.id}", data={"to": "new"})
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)
    claude = {"X-Feedback-Key": "k" * 40}
    admin.post(f"/api/feedback/{fb.id}", json={"note": "Which page, Brett?", "status": "planned"}, headers=claude)
    admin.post(f"/manage/feedback/{fb.id}", data={"to": "tell", "answer": "Thanks: it's planned."})
    assert [c["text"] for c in player.get("/your-notes/news").json()["cards"]] == ["Planned: “The Rest button wraps.”"]
    assert [c["text"] for c in player.get("/your-notes/news").json()["cards"]] == []  # (once)
    # Opening About askdnd from the other tab clears its badge (the page cleared the tab it opened on)
    player.get("/your-notes?tab=story")
    assert player.get("/your-notes/news").json()["tabs"]["askdnd"] == 1
    assert player.get("/your-notes/seen?tab=askdnd").json()["count"] == 0
    page = player.get("/your-notes?tab=askdnd").text
    assert "Thanks: it&#39;s planned." in page and 'class="page wide notes-page"' in page and 'data-tab="t-askdnd"' in page and "Which page, Brett?" not in page and ">Planned<" in page
    # Claude tells them it's fixed
    admin.post(f"/api/feedback/{fb.id}", json={"tell": "Fixed: Rest stays on one line now.", "status": "done"}, headers=claude)
    assert [c["text"] for c in player.get("/your-notes/news").json()["cards"]] == ["Fixed: “The Rest button wraps.”"]
    assert "Fixed: Rest stays on one line now." in player.get("/your-notes?tab=askdnd").text
    # Adding to it: back to an admin first; the queue says who wrote it
    player.post(f"/your-notes/feedback/{fb.id}", data={"text": "It wraps on Sheet too."})
    db.expire_all()
    assert db.get(Feedback, fb.id).status == "review"
    assert admin.get("/api/feedback", headers=claude).json()["items"] == []  # (not Claude's until approved)
    queue = admin.get("/manage/feedback").text
    assert "It wraps on Sheet too." in queue and "Reply to " in queue
    # Someone else's note is none of theirs
    other = Feedback(text="Someone else's", sender="x (player)", status="new")
    db.add(other)
    db.flush()
    assert "Someone else" not in player.get("/your-notes?tab=askdnd").text
    assert player.post(f"/your-notes/feedback/{other.id}", data={"text": "mine now"}).status_code == 404
    assert dm.post(f"/your-notes/feedback/{fb.id}", data={"text": "not theirs"}).status_code == 404
