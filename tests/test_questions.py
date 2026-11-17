"""Claude's questions and design picks, answered in askdnd (Working with Claude, Brett's picks 1A, 5A and Board 3,
Nov 17, docs/mockups/working-together/): asked on the note with answers to tap (Claude's own marked) or pictures to
pick from; listed in Testing's For you with the checks of their area; answered there or on Feedback with the same form;
the answer reaches Claude's inbox; a corner card says when there's something new."""

import pytest

from app import config
from app.importer import import_bundle
from app.models import Feedback
from tests.table_setup import BUNDLE
from tests.test_feedback import note, png

KEY = {"X-Feedback-Key": "k" * 40}


@pytest.fixture(autouse=True)
def table(db, monkeypatch):
    import_bundle(db, BUNDLE)
    db.flush()
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)


def ask(client, fb, **more):
    r = client.post(f"/api/feedback/{fb}", json={"note": "Keep the free-form box?", **more}, headers=KEY)
    assert r.status_code == 200, r.text
    return r.json()


CHOICES = [{"label": "Keep it, and check it as you type", "detail": "A red line until it reads as a roll."},
           {"label": "Remove it", "detail": "The picker only."}]


def test_a_question_with_answers_to_tap_is_answered_in_for_you(admin, db):
    """5A: answers to tap, Claude's pick marked and chosen to start with; Brett's own words alongside. The answer goes
    on the note, back to Claude, and into its inbox; For you moves on."""
    fb = note(admin, text="What happens in play when a typed roll isn't dice?").json()["id"]
    ask(admin, fb, choices=CHOICES, mine=0)
    assert admin.get("/manage/testing", follow_redirects=False).headers["location"] == f"/manage/testing?ask={fb}"  # (For you opens on it)
    page = admin.get(f"/manage/testing?ask={fb}").text
    assert f'data-ask="{fb}"' in page and 'data-choice="1"' in page and 'value="0" checked' in page
    assert admin.get("/c/main/manage/counts").json()["testing"] == 1

    r = admin.post(f"/manage/feedback/{fb}?back=testing", data={"to": "answer", "choice": "1", "answer": "And say so in the help."},
                   follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/manage/testing"
    db.expire_all()
    got = db.get(Feedback, fb)
    assert got.status == "new" and got.thread[-1]["choice"] == 1 and got.thread[-1]["text"].startswith("Picked B: Remove it.")
    assert "And say so in the help." in got.thread[-1]["text"]
    heard = admin.get("/api/claude/inbox", headers=KEY).json()["items"][-1]
    assert heard["what"] == "answer" and "Picked B" in heard["text"] and heard["feedback_id"] == fb
    assert admin.get("/c/main/manage/counts").json()["testing"] == 0


def test_a_design_pick_is_pictures_answered_in_one_press(admin, db):
    """Board 3: a question whose answers are pictures, each with its own Pick button; Neither takes words."""
    fb = note(admin, text="Manage should have an Overview page.").json()["id"]
    pic = png()
    ask(admin, fb, choices=[{"label": "What needs you", "pic": pic}, {"label": "A tile per page", "pic": pic}], mine=0)
    page = admin.get(f"/manage/testing?ask={fb}").text
    assert 'data-answer-choice="0"' in page and 'data-answer-choice="1"' in page and "qa-pick" in page
    pics = db.get(Feedback, fb).thread[-1]["ask"]["choices"]
    assert all(c["pic"] for c in pics)
    assert admin.get(f"/manage/feedback/{fb}/pic/{pics[0]['pic']}").status_code == 200
    admin.post(f"/manage/feedback/{fb}?back=testing", data={"to": "answer", "choice": "0"})
    db.expire_all()
    assert db.get(Feedback, fb).thread[-1]["text"] == "Picked A: What needs you."


def test_answers_are_checked_and_feedback_shows_the_same_form(admin, db):
    """Choices come with a question, 2 to 4, Claude's pick among them; an answer names one of them; the Feedback page's
    question is the same form as For you's (one way)."""
    fb = note(admin).json()["id"]
    assert admin.post(f"/api/feedback/{fb}", json={"choices": CHOICES}, headers=KEY).status_code == 400  # (no question)
    assert admin.post(f"/api/feedback/{fb}", json={"note": "?", "choices": CHOICES[:1]}, headers=KEY).status_code == 400
    assert admin.post(f"/api/feedback/{fb}", json={"note": "?", "choices": CHOICES, "mine": 5}, headers=KEY).status_code == 400
    ask(admin, fb, choices=CHOICES)
    assert admin.post(f"/manage/feedback/{fb}", data={"to": "answer", "choice": "7"}).status_code == 400
    assert 'data-question="%d"' % fb in admin.get(f"/manage/feedback?tab=question&open={fb}").text


def test_a_corner_card_says_claude_asked_once(admin, player, db):
    """Board 2: a corner card when there's something new for you, once; never for a player."""
    fb = note(admin).json()["id"]
    ask(admin, fb)
    cards = admin.get("/your-notes/news").json()["cards"]
    assert any(c["href"] == "/manage/testing" for c in cards)
    assert not any(c["href"] == "/manage/testing" for c in admin.get("/your-notes/news").json()["cards"])  # (once)
    assert not any(c["href"] == "/manage/testing" for c in player.get("/your-notes/news").json()["cards"])


def test_claudes_pictures_show_to_the_dm_and_an_empty_answer_says_what_s_missing(admin, player, db):
    """A standing rule kept (CLAUDE.md › Visibility; the outside review's C9): a player's note's own pictures stay kept
    from an admin who is their DM, but Claude's drawings for a pick on it are Claude's, never the player's, so the DM
    sees them. An answer sent empty from For you comes back to the question, saying what's missing."""
    from app import access
    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    access.invalidate()
    fb = note(player, text="The Rest button wraps.", pasted=png()).json()["id"]
    admin.post(f"/manage/feedback/{fb}", data={"to": "new"})
    ask(admin, fb, choices=[{"label": "Wrap it", "pic": png()}, {"label": "Shorten it", "pic": png()}])
    pic = db.get(Feedback, fb).thread[-1]["ask"]["choices"][0]["pic"]
    set_role(db, "admin@example.com", "dm")  # the admin becomes this campaign's DM
    access.invalidate()
    assert admin.get(f"/manage/feedback/{fb}/pasted").status_code == 404 and admin.get(f"/manage/feedback/{fb}/pic/{pic}").status_code == 200

    r = admin.post(f"/manage/feedback/{fb}?back=testing", data={"to": "answer"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/manage/testing?ask={fb}"
    db.expire_all()
    assert db.get(Feedback, fb).status == "question"
