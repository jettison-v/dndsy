"""Feedback for Claude (app/feedback.py; Brett, 2026-11-03, docs/mockups/feedback-queue/): a note from any page, kept
in a queue for Claude, who reads and moves it on with its own key."""

import base64
import io

import pytest
from PIL import Image
from sqlalchemy import func, select

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


def note(client, text="Speed should show the swim speed too.", kind="broken", **more):
    return client.post("/feedback", json={"text": text, "kind": kind, "url": "http://localhost/characters/1/battle",
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


def test_your_notes_round_2_each_note_is_a_request_an_answer_and_a_track(admin, player, db):
    """Brett, Nov 7 (feedback 54, docs/mockups/your-notes-2/ Layout B): each note in the list is its title (the first
    sentence), its date and where it stands with what happened; beside it the note itself: its track of steps, what
    you asked and what happened. Open first, then Done; ?note= opens one. Deleting asks for a reason for its sender,
    never required."""
    from app.your_notes import title_of, track
    from tests.roles import set_role

    assert title_of("The Rest button wraps. It did on Sheet too.") == "The Rest button wraps."
    long = "word " * 30
    assert title_of(long).endswith("word…") and len(title_of(long)) <= 91
    assert [s["state"] for s in track(("Sent", "Approved", "Planned", "Fixed"), 1)] == ["done", "done", "now", "todo"]
    assert [(s["label"], s["state"]) for s in track(("Sent", "Approved", "Planned", "Fixed"), 0, "Closed")] == \
        [("Sent", "done"), ("Closed", "stop"), ("Planned", "skip"), ("Fixed", "skip")]

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    note(player, text="The Rest button wraps. It did on Sheet too.")
    note(player, text="Dice are too loud.")
    wraps, loud = db.scalars(select(Feedback).order_by(Feedback.id)).all()
    admin.post(f"/manage/feedback/{wraps.id}", data={"to": "new"})
    admin.post(f"/manage/feedback/{wraps.id}", data={"to": "done"})
    admin.post(f"/manage/feedback/{wraps.id}", data={"to": "tell", "answer": "Fixed: Rest stays on one line."})
    admin.post(f"/manage/feedback/{loud.id}", data={"to": "deleted", "answer": "Dice sounds are a setting in Your dice."})
    page = player.get("/your-notes?tab=askdnd").text
    rows = page.split('id="t-askdnd"')[1].split('data-ls-rows>')[1].split("</aside>")[0]
    assert rows.index(f'data-note="f{loud.id}"') < rows.index(f'data-note="f{wraps.id}"')  # (both done: newest first)
    assert '<span class="nt-title">The Rest button wraps.' in rows and "Fixed: Rest stays on one line.</span>" in rows and "Fixed: Fixed:" not in rows  # (the reply alone: no "Fixed: Fixed.", the UI review)
    assert 'data-group-newest="Done"' in rows and '"status": "Closed"' in rows
    read = page.split(f'data-note-read="f{loud.id}"')[1].split("</article>")[0]
    assert '<li class="st-stop">Closed</li>' in read and '<li class="st-skip">Fixed</li>' in read
    assert "Dice sounds are a setting in Your dice." in read and "Add to it" not in read  # (a closed note: as today)
    assert f'data-note-read="f{loud.id}">' in page  # (the first is shown when none is asked for)
    picked = player.get(f"/your-notes?tab=askdnd&note=f{wraps.id}").text
    assert f'data-note-read="f{wraps.id}">' in picked and f'data-note-read="f{loud.id}" hidden' in picked
    # Deleting without a reason is fine: its sender sees what Closed means
    note(player, text="A third note.")
    third = db.scalar(select(Feedback).where(Feedback.text == "A third note."))
    admin.post(f"/manage/feedback/{third.id}", data={"to": "deleted", "answer": ""})
    db.refresh(third)
    assert third.status == "deleted" and not third.thread
    assert "Not something askdnd will change for now." in player.get(f"/your-notes?tab=askdnd&note=f{third.id}").text
    assert "Why, for " in admin.get("/manage/feedback?tab=all").text


def test_a_note_sent_on_staging_goes_to_prods_queue_marked_staging(admin, db, monkeypatch):
    """Brett, Nov 6: one feedback queue; staging's notes reach prod, so refreshing staging's data loses none."""
    from app import config, feedback

    monkeypatch.setattr(config, "STAGING", True)
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 32)
    sent = []
    monkeypatch.setattr(feedback, "SEND", lambda url, note, key: sent.append((url, note, key)) or {"id": 77, "review": False})
    r = note(admin)
    assert r.json()["id"] == 77 and r.json()["to_prod"] and db.scalar(select(Feedback)) is None  # (none kept on staging)
    url, payload, key = sent[0]
    assert url == "https://askdnd.ai/api/feedback/from-staging" and key == "k" * 32
    assert payload["email"] == "admin@example.com" and payload["shot"].startswith("data:image/png") and payload["context"]["pointed"]["label"] == "Speed"
    monkeypatch.setattr(feedback, "SEND", lambda url, note, key: {"error": "Prod didn't take it (timed out)."})
    note(admin, text="Kept here when prod is away.")
    fb = db.scalar(select(Feedback))
    assert fb.text == "Kept here when prod is away." and "timed out" in fb.context["not_sent_to_prod"]


def test_prod_takes_a_staging_note_only_with_the_key(admin, db, monkeypatch):
    client_for_api = admin  # (the key decides, not who is signed in)
    from app import config

    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 32)
    body = {"email": "Player@Example.com", "name": "Pat", "text": "The Coins window is cut off on staging.", "url": "https://staging.askdnd.ai/x",
            "context": {"page": "Battle"}, "html": "<html></html>", "shot": png()}
    assert client_for_api.post("/api/feedback/from-staging", json=body).status_code == 404
    assert client_for_api.post("/api/feedback/from-staging", json=body, headers={"X-Feedback-Key": "nope" * 8}).status_code == 404
    r = client_for_api.post("/api/feedback/from-staging", json=body, headers={"X-Feedback-Key": "k" * 32})
    fb = db.get(Feedback, r.json()["id"])
    assert r.json()["review"] and fb.status == "review" and fb.context["staging"] and fb.shot_key and fb.sender.startswith("Pat (")


def test_a_notes_page_is_kept_from_an_admin_who_is_its_senders_dm(admin, player, db):
    """A standing rule (CLAUDE.md › Visibility: character notes are visible to players but NOT the DM, even an admin;
    the outside review's C9): a note's page and pictures can show its sender's character notes, so an admin who is the
    DM of a campaign the sender plays in sees its words but not its page, pictures or what it pointed at."""
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    assert note(player, text="The Rest button wraps.", pasted=png()).status_code == 200
    fb = db.scalar(select(Feedback))
    page = admin.get("/manage/feedback").text  # (not the DM: everything)
    assert f"/manage/feedback/{fb.id}/shot" in page and 'data-kept="0"' in page and "pointed at Speed" in page
    assert admin.get(f"/manage/feedback/{fb.id}/page").status_code == 200

    set_role(db, "admin@example.com", "dm")  # the admin becomes this campaign's DM
    access.invalidate()
    page = admin.get("/manage/feedback").text
    assert "The Rest button wraps." in page and 'data-kept="1"' in page  # (its words stay)
    assert f"/manage/feedback/{fb.id}/shot" not in page and f"/manage/feedback/{fb.id}/page" not in page and "pointed at Speed" not in page
    for which in ("shot", "pasted", "page"):
        assert admin.get(f"/manage/feedback/{fb.id}/{which}").status_code == 404


def test_a_note_sent_viewing_as_a_player_is_kept_from_their_dm(admin, db):
    """Sent by one admin viewing as a player: the page is that player's, so it's kept from the player's DM, even when
    the DM is another admin."""
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/view-as", data={"email": "player@example.com"})
    assert note(admin).status_code == 200
    admin.post("/view-as/stop")
    fb = db.scalar(select(Feedback))
    assert fb.context["viewing_as_email"] == "player@example.com"
    other = db.scalar(select(User).where(User.email == "admin@example.com"))
    other.email = "second@example.com"  # (the sender, now under another address; admin@ will be the DM)
    db.flush()
    fb.user_id = other.id
    set_role(db, "admin@example.com", "dm")
    access.invalidate()
    assert admin.get(f"/manage/feedback/{fb.id}/page").status_code == 404


def test_the_dm_over_rule_is_one_rule():
    rows = {"dm@x": {"roles": {1: "dm", 2: "player"}}, "p@x": {"roles": {1: "player"}}, "q@x": {"roles": {2: "dm"}},
            "co@x": {"roles": {1: "dm"}}}
    assert access.dm_over("dm@x", "p@x", rows) and access.dm_over(" DM@x ", "P@x", rows)
    assert not access.dm_over("p@x", "dm@x", rows)  # (a player over the DM: no)
    assert not access.dm_over("dm@x", "q@x", rows)  # (q is the DM of 2, where dm@ plays)
    assert not access.dm_over("dm@x", "co@x", rows)  # (two DMs of one campaign)
    assert not access.dm_over("dm@x", "dm@x", rows) and not access.dm_over(None, "p@x", rows) and not access.dm_over("dm@x", "", rows)


def test_a_note_says_what_it_is_and_nothing_picks_it_for_you(admin, db):
    """Brett, Nov 16: a note is something broken, an idea or a question, picked when it's sent and never for you (a kind
    picked for you is never changed). Without one, or with one askdnd doesn't know, nothing is kept."""
    assert note(admin, kind=None).status_code == 400
    assert note(admin, kind="bug").status_code == 400
    assert note(admin, kind=["idea"]).status_code == 400  # (not a string: refused, never a 500)
    assert db.scalar(select(func.count()).select_from(Feedback)) == 0
    assert note(admin, kind="question").status_code == 200
    assert db.scalar(select(Feedback)).kind == "question"
    notes = admin.get("/your-notes?tab=askdnd").text  # (Notes you sent filters by it, even with one kind sent so far)
    assert notes.count('data-ls-group="what"') == 3
    window = admin.get("/help").text  # (the window on every page: three choices, none on)
    assert window.count('data-fb-kind="') == 3 and 'class="chip on" role="radio"' not in window


def test_the_queue_sorts_by_kind_and_an_admin_or_claude_changes_one_saying_why(admin, player, db, monkeypatch):
    """Brett, Nov 16: the queue filters by kind; a "bug" that's really a design change is changed, with why in its
    thread for the admins and Claude, never on its sender's Your notes. A note sent before kinds says Not sorted."""
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    note(admin, text="The Rest button wraps.")
    note(admin, text="Could Battle show the swim speed?", kind="idea")
    note(player, text="Why is my Speed 25?", kind="question")
    wraps, swim, why = db.scalars(select(Feedback).order_by(Feedback.id)).all()
    old = Feedback(sender="Old (admin)", text="Sent before kinds.", status="new")
    db.add(old)
    db.commit()
    page = admin.get("/manage/feedback?tab=new").text
    assert 'data-kind="broken"' in page and 'data-kind="idea"' in page and 'data-kind="none"' in page
    ideas = admin.get("/manage/feedback?tab=new&kind=idea").text
    assert "Could Battle show the swim speed?" in ideas and "The Rest button wraps." not in ideas
    assert "Sent before kinds." in admin.get("/manage/feedback?tab=new&kind=none").text
    r = admin.post(f"/manage/feedback/{wraps.id}?tab=new&kind=broken", data={"to": "kind", "kind": "idea", "answer": "It's a design change"},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("tab=new&kind=broken")
    r = admin.post(f"/manage/feedback/{wraps.id}?tab=new&kind=x//y", data={"to": "kind", "kind": "idea"}, follow_redirects=False)
    assert r.headers["location"].endswith("tab=new&kind=")  # (only a kind askdnd knows goes back into the address)
    db.refresh(wraps)
    assert wraps.kind == "idea" and wraps.status == "new" and wraps.thread[-1]["text"] == "Broken → Idea: It's a design change"
    assert admin.post(f"/manage/feedback/{wraps.id}", data={"to": "kind", "kind": "nonsense"}).status_code == 400
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)
    claude = {"X-Feedback-Key": "k" * 40}
    assert [i["id"] for i in admin.get("/api/feedback?kind=none", headers=claude).json()["items"]] == [old.id]
    assert admin.post(f"/api/feedback/{old.id}", json={"kind": "broken", "why": "Sorted once"}, headers=claude).json()["kind"] == "broken"
    assert admin.post(f"/api/feedback/{old.id}", json={"kind": "bug"}, headers=claude).status_code == 400
    assert admin.post(f"/api/feedback/{old.id}", json={"kind": {"x": 1}}, headers=claude).status_code == 400
    assert {i["id"] for i in admin.get("/api/feedback?kind=idea,question", headers=claude).json()["items"]} == {swim.id, wraps.id}
    admin.post(f"/manage/feedback/{why.id}", data={"to": "new"})  # (approved)
    admin.post(f"/manage/feedback/{why.id}", data={"to": "kind", "kind": "broken", "answer": "Speed is read wrong"})
    assert "Speed is read wrong" not in player.get("/your-notes?tab=askdnd").text  # (between the admins and Claude)


def test_an_idea_and_a_question_say_where_they_stand_in_their_own_words(admin, player, db, monkeypatch):
    """Brett, Nov 16: an idea goes onto the Roadmap and is built later; a question is answered. Its sender's track,
    label and corner card say so (Your notes)."""
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    note(player, text="Could Battle show the swim speed?", kind="idea")
    note(player, text="Why is my Speed 25?", kind="question")
    idea, question = db.scalars(select(Feedback).order_by(Feedback.id)).all()
    player.get("/your-notes?tab=askdnd")
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)
    claude = {"X-Feedback-Key": "k" * 40}
    for fb in (idea, question):
        admin.post(f"/manage/feedback/{fb.id}", data={"to": "new"})
    admin.post(f"/api/feedback/{idea.id}", json={"status": "planned"}, headers=claude)
    admin.post(f"/api/feedback/{question.id}", json={"tell": "A Dwarf's Speed is 25 in 2024? No: 30.", "status": "done"}, headers=claude)
    cards = [c["text"] for c in player.get("/your-notes/news").json()["cards"]]
    assert "On the Roadmap: “Could Battle show the swim speed?”" in cards and "Answered: “Why is my Speed 25?”" in cards
    page = player.get("/your-notes?tab=askdnd").text
    assert page.count('data-ls-group="what"') == 3 and 'data-kind="idea"' in page and 'data-kind="question"' in page
    from app.your_notes import askdnd_note

    db.refresh(idea)
    db.refresh(question)
    shown = {fb.kind: askdnd_note(fb) for fb in (idea, question)}
    assert shown["idea"]["label"] == "On the Roadmap" and [s["label"] for s in shown["idea"]["track"]] == ["Sent", "With Claude", "On the Roadmap", "Built"]
    assert [s["state"] for s in shown["idea"]["track"]] == ["done", "done", "done", "now"]
    assert shown["question"]["label"] == "Answered" and [s["label"] for s in shown["question"]["track"]] == ["Sent", "With Claude", "Answered"]
    assert shown["question"]["track"][-1]["state"] == "done"
    for label in ("On the Roadmap", "Answered"):  # (their own status chips; Planned, Fixed and Closed always show)
        assert f'data-ls-value="{label}"' in page
    assert 'data-ls-value="Built"' not in page  # (nothing built yet: no chip for it)


def test_a_staging_note_from_before_kinds_is_kept_not_sorted(admin, db, monkeypatch):
    """Staging may run code from before kinds: its note is kept, with no kind, to be sorted."""
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 32)
    r = admin.post("/api/feedback/from-staging", json={"email": "admin@example.com", "text": "From older staging"},
                   headers={"X-Feedback-Key": "k" * 32})
    assert r.status_code == 200 and db.get(Feedback, r.json()["id"]).kind == ""


def _png_file(name="shot.png"):
    out = io.BytesIO()
    Image.new("RGB", (8, 6), (40, 200, 40)).save(out, "PNG")
    return ("pics", (name, out.getvalue(), "image/png"))


def test_add_to_it_takes_screenshots_that_only_its_sender_admins_and_claude_see(admin, player, dm, db, file_store, monkeypatch):
    """Feedback 64 (Nov 16): Add to it takes screenshots too, chosen or pasted, from a note's sender on Notes you sent
    and from an admin on the queue. Its sender sees their own; another player can't; admins and Claude can."""
    from app.models import FeedbackPicture
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    note(player, text="The Rest button wraps.")
    fb = db.scalar(select(Feedback))
    r = player.post(f"/your-notes/feedback/{fb.id}", data={"text": "Here it is on my phone"}, files=[_png_file(), _png_file("two.png")],
                    follow_redirects=False)
    assert r.status_code == 303
    db.refresh(fb)
    pics = fb.thread[-1]["pics"]
    assert len(pics) == 2 and fb.thread[-1]["text"] == "Here it is on my phone" and fb.status == "review"
    assert db.get(FeedbackPicture, pics[0]).key.endswith(".png")  # (in file storage, like every picture)
    assert player.get(f"/your-notes/feedback/{fb.id}/pic/{pics[0]}").headers["content-type"] == "image/png"
    page = player.get("/your-notes?tab=askdnd").text
    assert f"/your-notes/feedback/{fb.id}/pic/{pics[1]}" in page
    assert dm.get(f"/your-notes/feedback/{fb.id}/pic/{pics[0]}").status_code == 404  # (not their note)
    assert admin.get(f"/manage/feedback/{fb.id}/pic/{pics[0]}").status_code == 200
    assert f"/manage/feedback/{fb.id}/pic/{pics[0]}" in admin.get("/manage/feedback?tab=review").text
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)
    assert admin.get(f"/api/feedback/{fb.id}/pic/{pics[1]}", headers={"X-Feedback-Key": "k" * 40}).status_code == 200
    assert admin.get(f"/api/feedback/{fb.id}/pic/{pics[1]}").status_code == 404  # (Claude's key, or nothing)
    # A screenshot alone is enough; the wrong kind of file, or too many, is refused and nothing is kept
    assert player.post(f"/your-notes/feedback/{fb.id}", files=[_png_file()], follow_redirects=False).status_code == 303
    before = db.scalar(select(func.count()).select_from(FeedbackPicture))
    assert player.post(f"/your-notes/feedback/{fb.id}", data={"text": "x"}, files=[("pics", ("a.gif", b"GIF89a", "image/gif"))]).status_code == 400
    assert player.post(f"/your-notes/feedback/{fb.id}", data={"text": "x"}, files=[_png_file(f"{i}.png") for i in range(5)]).status_code == 400
    assert player.post(f"/your-notes/feedback/{fb.id}", data={"text": " "}).status_code == 400
    assert db.scalar(select(func.count()).select_from(FeedbackPicture)) == before
    # An admin adds one on the queue
    r = admin.post(f"/manage/feedback/{fb.id}", data={"to": "answer", "answer": "Same on mine"}, files=[_png_file()], follow_redirects=False)
    db.refresh(fb)
    assert r.status_code == 303 and fb.thread[-1]["who"] == "you" and len(fb.thread[-1]["pics"]) == 1 and fb.status == "new"


def test_a_sender_sees_the_pictures_they_sent_but_never_their_dm_even_viewing_as_them(admin, player, dm, db, file_store):
    """Brett, Nov 16: Notes you sent shows the pictures a note was sent with (the page as the window opened, a pasted
    screenshot, those added later) to its sender. A standing rule (CLAUDE.md › Visibility; the outside review's C9):
    they can show the sender's character notes, so an admin who is the sender's DM never sees them, and View as is no
    way round it."""
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    assert note(player, text="The Rest button wraps.", pasted=png()).status_code == 200
    fb = db.scalar(select(Feedback))
    player.post(f"/your-notes/feedback/{fb.id}", data={"text": "And on my phone"}, files=[_png_file()])
    db.refresh(fb)
    pic = fb.thread[-1]["pics"][0]
    mine = player.get("/your-notes?tab=askdnd").text
    for which in ("shot", "pasted"):
        assert f"/your-notes/feedback/{fb.id}/{which}" in mine
        assert player.get(f"/your-notes/feedback/{fb.id}/{which}").headers["content-type"].startswith("image/")
    assert f"/your-notes/feedback/{fb.id}/pic/{pic}" in mine
    assert dm.get(f"/your-notes/feedback/{fb.id}/shot").status_code == 404  # (not their note)
    assert player.get(f"/your-notes/feedback/{fb.id}/page").status_code == 404  # (only the two pictures, never the page as drawn)
    # An admin who isn't the sender's DM, viewing as them, sees what they see
    admin.post("/view-as", data={"email": "player@example.com"})
    assert f"/your-notes/feedback/{fb.id}/shot" in admin.get("/your-notes?tab=askdnd").text
    admin.post("/view-as/stop")
    # The same admin as this campaign's DM: View as refuses (app/view_as.py), and the pictures stay theirs
    set_role(db, "admin@example.com", "dm")
    access.invalidate()
    admin.post("/view-as", data={"email": "player@example.com"})
    assert "The Rest button wraps." not in admin.get("/your-notes?tab=askdnd").text  # (not viewing as them: their own page)
    for path in (f"/your-notes/feedback/{fb.id}/shot", f"/your-notes/feedback/{fb.id}/pasted", f"/your-notes/feedback/{fb.id}/pic/{pic}"):
        assert admin.get(path).status_code == 404, path


def test_claude_gives_a_note_a_short_title_its_sender_and_the_queue_show(admin, player, db, monkeypatch):
    """Brett, Nov 16: when Claude takes a note up it writes a short title (feedback.py title); Notes you sent and the
    queue show it, and a note without one shows its first sentence."""
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    note(player, text="When I press the button on the left of the spell row nothing seems to happen at all on my phone.")
    fb = db.scalar(select(Feedback))
    assert f'data-note="f{fb.id}"' in player.get("/your-notes?tab=askdnd").text
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)
    claude = {"X-Feedback-Key": "k" * 40}
    r = admin.post(f"/api/feedback/{fb.id}", json={"title": "  Spell row's   button on a phone  "}, headers=claude)
    assert r.json()["title"] == "Spell row's button on a phone"  # (spaces tidied)
    db.refresh(fb)
    assert fb.title == "Spell row's button on a phone"
    assert "Spell row&#39;s button on a phone" in player.get("/your-notes?tab=askdnd").text
    assert "Spell row&#39;s button on a phone" in admin.get("/manage/feedback?tab=review").text
    assert admin.post(f"/api/feedback/{fb.id}", json={"title": "x" * 300}, headers=claude).json()["title"] == "x" * 120
