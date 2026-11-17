"""Testing round 3, the card and the walkthrough (Working with Claude, Brett's picks Nov 17, docs/mockups/working-together/):
several issues on one check, each its own note (2A); steps as a walkthrough, held to its rules (3A); a check that makes
something runs in a test campaign and the round comes back home (Board 6); the card as it was left, and on Testing only
for a check about Testing (6A, notes 83, 85, 91)."""

import pytest
from sqlalchemy import select

from app import config, testing
from app.importer import import_bundle
from app.models import Campaign, Check, Feedback, User
from tests.table_setup import BUNDLE
from tests.test_feedback import note

KEY = {"X-Feedback-Key": "k" * 40}


@pytest.fixture(autouse=True)
def table(db, monkeypatch):
    import_bundle(db, BUNDLE)
    db.flush()
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)


def add(client, **more):
    r = client.post("/api/checks", json={"title": "Build an item", "path": "/party", "do": "Press [+ New item].", "expect": "It opens.", **more},
                    headers=KEY)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_every_issue_found_on_a_check_is_its_own_note(admin, db):
    """2A: Failed… fails the check and the card stays on it; + Another issue sends the next; each is a note tied to the
    check; Done · Next check moves on. The check comes back once every broken issue is fixed; an idea doesn't hold it."""
    c = add(admin)
    admin.post("/manage/testing/round", data={})
    one = note(admin, text="How many spills out of its box.", check=c).json()["id"]
    two = note(admin, text="Help beside Only with it.", kind="idea", check=c).json()["id"]
    three = note(admin, text="The sentence says the name twice.", check=c).json()["id"]
    db.expire_all()
    chk = db.get(Check, c)
    assert chk.status == "failed" and [h["what"].split(":")[0] for h in chk.history].count("Failed") == 1
    assert [f.id for f in testing.issues(db, chk)] == [one, two, three]
    card = admin.get("/manage/testing/card").text
    assert all(f'data-issue="{i}"' in card for i in (one, two, three)) and "data-cc-failed" in card
    assert all(f'data-issue="{i}"' in admin.get(f"/manage/testing?show=failed&check={c}").text for i in (one, two, three))

    for i in (one,):
        admin.post(f"/api/feedback/{i}", json={"kind": "broken", "status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/501"}, headers=KEY)
    db.expire_all()
    assert db.get(Check, c).status == "failed" and "still to go" in db.get(Check, c).history[-1]["what"]  # (note 3 isn't fixed yet)
    admin.post(f"/api/feedback/{three}", json={"kind": "broken", "status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/502"}, headers=KEY)
    db.expire_all()
    assert db.get(Check, c).status == "fixed"  # (the idea, note 2, doesn't hold it back)


def test_an_issue_can_go_with_a_check_that_passes(admin, db):
    """+ Issue (it works, but…): tied to the check, which isn't failed."""
    c = add(admin)
    sent = note(admin, text="It works, but the font is small.", kind="idea", check=c, fail=False).json()["id"]
    db.expire_all()
    assert db.get(Check, c).status == "ready" and db.get(Feedback, sent).check_id == c
    assert db.get(Check, c).history[-1]["what"].startswith("An issue")
    admin.post(f"/manage/testing/{c}", data={"result": "passed"})
    admin.post(f"/api/feedback/{sent}", json={"kind": "broken", "status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/503"}, headers=KEY)
    db.expire_all()
    own = db.scalar(select(Check).where(Check.feedback_id == sent))
    assert own is not None and own.status == "fixed" and db.get(Check, c).status == "passed"  # (its fix comes back to be tried)


def test_steps_are_a_walkthrough_held_to_its_rules(admin):
    """3A (Brett, Nov 17: "type lots in Or type it" didn't make sense): one action a step; what to type `marked`; a
    button [drawn]; a box **named**; why after it. A step that breaks the rules is refused, from both ways a check is made."""
    steps = testing.walk("In **Or type it**, type `lots`. (why: not a dice roll, on purpose)\nPress [Save].")
    assert [p["kind"] for p in steps[0]["parts"]] == ["text", "box", "text", "typed", "text"] and steps[0]["why"] == "not a dice roll, on purpose"
    assert steps[1]["parts"][1] == {"kind": "press", "text": "Save"}
    for bad in ("Name it Test Compass 2, then press [Save].", "Type lots in the box."):
        r = admin.post("/api/checks", json={"title": "A", "do": bad}, headers=KEY)
        assert r.status_code == 400 and "testing-guide" in r.text
    fb = note(admin).json()["id"]
    r = admin.post(f"/api/feedback/{fb}", json={"kind": "broken", "status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/9",
                                               "check_do": "Open it, then close it."}, headers=KEY)
    assert r.status_code == 400
    page = admin.get(f"/manage/testing?check={add(admin, do='In **Name**, type `Test Compass 2`.')}").text
    assert page.count('class="typed"') == 1 and "data-tick" in page


def test_a_check_that_makes_something_runs_in_a_test_campaign_and_the_round_comes_home(admin, db):
    """Board 6: makes refused outside a test campaign; the card says where it runs; a round there ends back in the
    campaign it began in."""
    test = Campaign(name="VTT Test", slug="vtt-test", is_test=True)
    db.add(test)
    db.commit()
    assert admin.post("/api/checks", json={"title": "A", "makes": True, "path": "/c/main/dm/items/new"}, headers=KEY).status_code == 400
    c = add(admin, makes=True, path="/c/vtt-test/dm/items/new")
    me = db.scalar(select(User).where(User.email == "admin@example.com"))
    home = db.scalar(select(Campaign).where(Campaign.slug == "main")).id
    admin.post(f"/manage/testing/{c}/go")
    admin.get("/c/vtt-test/dm/items/new")  # (visiting makes it the current campaign)
    db.expire_all()
    assert db.get(User, me.id).current_campaign_id == test.id
    assert "data-in-test" in admin.get("/manage/testing/card").text
    admin.post(f"/manage/testing/{c}", data={"result": "passed"})
    db.expire_all()
    assert db.get(User, me.id).current_campaign_id == home


def test_the_card_draws_as_it_was_left_and_on_testing_only_for_a_check_about_it(admin):
    """Notes 85 and 91, 6A: folded and its corner come from the cookie, so it never opens and then folds; on the
    Testing page it shows only when the check is about Testing."""
    about_testing, elsewhere = add(admin, title="Testing's card", path="/manage/testing"), add(admin)
    admin.post(f"/manage/testing/{elsewhere}/go")
    assert admin.get("/manage/testing/card?at=/manage/testing").status_code == 204
    admin.cookies.set("askdnd-cc", "folded.tl")
    card = admin.get("/manage/testing/card?at=/party").text
    assert 'data-corner="tl"' in card and 'class="check-card folded"' in card
    admin.post(f"/manage/testing/{about_testing}/go")
    assert f'data-check-card="{about_testing}"' in admin.get("/manage/testing/card?at=/manage/testing").text
