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


def test_the_admin_menu_counts_whats_new(admin, db):
    note(admin)
    slug = db.scalar(select(__import__("app.models", fromlist=["Campaign"]).Campaign.slug))
    assert admin.get(f"/c/{slug}/manage/counts").json()["feedback"] == 1


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
