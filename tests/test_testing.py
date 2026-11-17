"""Testing in askdnd (app/testing.py; Brett's idea and picks 1A, 2A, 3A, 4A, 5B, 6C, Nov 16; docs/mockups/testing/): a
check for an admin to try, written by Claude with its key, marked by the admin in the Reader or in a round, where
Failed… is a feedback note tied to the check."""

import pytest
from sqlalchemy import select

from app import config
from app.importer import import_bundle
from app.models import Check, Feedback
from tests.table_setup import BUNDLE
from tests.test_feedback import note

KEY = {"X-Feedback-Key": "k" * 40}


@pytest.fixture(autouse=True)
def table(db, monkeypatch):
    import_bundle(db, BUNDLE)
    db.flush()
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)


def add(client, **more):
    body = {"title": "Column headings stay while a list scrolls", "area": "Sheet", "setup": "laptop", "path": "/characters/1?tab=items",
            "do": "Scroll down the Inventory list.\nThen Change forms.", "expect": "They stay under the tabs.", "minutes": 2, **more}
    r = client.post("/api/checks", json=body, headers=KEY)
    assert r.status_code == 200, r.text
    return r.json()


def test_claude_writes_a_check_and_the_reader_shows_it_with_why(admin, db):
    fb = note(admin).json()["id"]
    c = add(admin, feedback_id=fb, said="Fixed: they stay at the top now.", pr="https://github.com/jettison-v/dndsy/pull/399")
    assert c["status"] == "ready" and c["do"] == ["Scroll down the Inventory list.", "Then Change forms."] and c["feedback_id"] == fb
    page = admin.get(f"/manage/testing?check={c['id']}").text
    assert f'data-check-read="{c["id"]}"' in page and 'data-check-go' in page and f"Note {fb}" in page and 'href="https://github.com/jettison-v/dndsy/pull/399"' in page
    assert admin.get("/api/checks?status=ready", headers=KEY).json()["items"][0]["id"] == c["id"]
    assert admin.get("/c/main/manage/counts").json().get("testing") == 1  # (the Manage menu's count)


def test_claude_names_only_a_note_that_exists_and_a_known_setup(admin):
    assert admin.post("/api/checks", json={"title": "A", "feedback_id": 999999}, headers=KEY).status_code == 400
    assert admin.post("/api/checks", json={"title": "A", "setup": "moon"}, headers=KEY).status_code == 400
    assert admin.post("/api/checks", json={"title": ""}, headers=KEY).status_code == 400
    for bad in ({"path": "javascript:alert(1)"}, {"path": "//elsewhere.example"}, {"pr": "javascript:alert(1)"}):  # (links on the page)
        assert admin.post("/api/checks", json={"title": "A", **bad}, headers=KEY).status_code == 400


def test_a_round_goes_page_to_page_and_failed_is_a_note_tied_to_its_check(admin, db):
    """2A and 3A: ▶ Start round opens the first check's page with its card; Passed goes to the next one's; Failed… sends
    a feedback note that marks the check failed, ties it, and answers with the next page; the last one ends the round."""
    one, two, three = (add(admin, title=t, path=p, place=i) for i, (t, p) in enumerate((("One", "/characters/1/battle"), ("Two", "/c/main/dm"),
                                                                                         ("Three", "/party"))))
    r = admin.post("/manage/testing/round", data={}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/characters/1/battle"
    card = admin.get("/manage/testing/card").text
    assert f'data-check-card="{one["id"]}"' in card and "1 of 3" in card
    r = admin.post(f"/manage/testing/{one['id']}", data={"result": "passed"}, follow_redirects=False)
    assert r.headers["location"] == "/c/main/dm" and db.get(Check, one["id"]).status == "passed"
    sent = note(admin, text="The list says it differently.", check=two["id"]).json()
    db.expire_all()
    failed = db.get(Check, two["id"])
    assert failed.status == "failed" and failed.failed_id == sent["id"] and sent["next"] == "/party"
    assert db.get(Feedback, sent["id"]).context["check"] == two["id"]
    r = admin.post(f"/manage/testing/{three['id']}", data={"result": "skipped"}, follow_redirects=False)
    assert r.headers["location"] == "/manage/testing" and admin.get("/manage/testing/card").status_code == 204  # (the round is done)
    assert [h["what"] for h in db.get(Check, two["id"]).history][-1].startswith("Failed")


def test_go_brings_the_check_with_its_card_and_comes_back_to_it(admin, db):
    """Brett, Nov 16 ("I am not getting the cards after clicking on the links"): Go opens the check's page with its card
    (a round of one), and marking it comes back to it in the Reader."""
    c = add(admin, path="/party")
    r = admin.post(f"/manage/testing/{c['id']}/go", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/party"
    assert f'data-check-card="{c["id"]}"' in admin.get("/manage/testing/card").text
    r = admin.post(f"/manage/testing/{c['id']}", data={"result": "passed"}, follow_redirects=False)
    assert r.headers["location"] == f"/manage/testing?check={c['id']}" and admin.get("/manage/testing/card").status_code == 204


def test_claude_moves_a_fixed_check_back_to_try_again(admin, db):
    c = add(admin)
    admin.post(f"/manage/testing/{c['id']}", data={"result": "skipped"})
    r = admin.post(f"/api/checks/{c['id']}", json={"status": "again", "said": "Fixed in PR 401."}, headers=KEY).json()
    assert r["status"] == "again" and r["said"] == "Fixed in PR 401."
    assert "Try again" in admin.get("/manage/testing?show=again").text


def test_a_standing_rule_testing_is_for_admins_and_claude_only(player, dm, admin, db):
    """A standing rule (Brett, Nov 16, docs/mockups/testing/ 5B: admins, and his test accounts through View as): a
    player or the DM gets no Testing page, no card, no marking, and a note from them can't touch a check."""
    c = add(admin)
    for who in (player, dm):
        assert who.get("/manage/testing").status_code in (403, 404)
        assert who.get("/manage/testing/card").status_code in (403, 404)
        assert who.post(f"/manage/testing/{c['id']}", data={"result": "passed"}).status_code in (403, 404)
    assert admin.post("/api/checks", json={"title": "A"}).status_code == 404  # (no key)
    db.expire_all()
    assert db.get(Check, c["id"]).status == "ready"
    assert db.scalar(select(Check).where(Check.failed_id.is_not(None))) is None
