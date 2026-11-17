"""Areas and Claude's inbox (Working with Claude, Brett's picks Nov 17, docs/mockups/working-together/): notes and checks
sorted into areas that run in Brett's order, one at a time in Claude's hands; and askdnd keeping what Claude hasn't read
yet, so nothing Brett does in askdnd needs telling in chat (app/for_claude.py)."""

import pytest
from sqlalchemy import select

from app import config
from app.importer import import_bundle
from app.models import Area, Check, InboxItem
from tests.table_setup import BUNDLE
from tests.test_feedback import note

KEY = {"X-Feedback-Key": "k" * 40}


@pytest.fixture(autouse=True)
def table(db, monkeypatch):
    import_bundle(db, BUNDLE)
    db.flush()
    monkeypatch.setattr(config, "FEEDBACK_KEY", "k" * 40)


def check(client, title, **more):
    r = client.post("/api/checks", json={"title": title, "path": "/party", "do": "Look.", "expect": "It's there.", **more}, headers=KEY)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def area(client, title, **more):
    r = client.post("/api/areas", json={"title": title, **more}, headers=KEY)
    assert r.status_code == 200, r.text
    return r.json()


def inbox(client):
    return client.get("/api/claude/inbox", headers=KEY).json()["items"]


def test_for_you_and_a_round_go_area_by_area_in_brett_s_order(admin, db):
    """4A: the checks by area, in the areas' order, then each area's own order; ▶ Just this area runs one; dragging the
    areas (7A) changes the order, and Claude's inbox hears it."""
    a1, a2 = (check(admin, t, place=i) for i, t in enumerate(("Builder one", "Builder two")))
    b1 = check(admin, "Card one")
    loose = check(admin, "In no area")
    builder, card = area(admin, "Item Builder", checks=[a1, a2]), area(admin, "The Testing card", checks=[b1])
    page = admin.get("/manage/testing").text
    assert page.index(f'data-check="{a1}"') < page.index(f'data-check="{a2}"') < page.index(f'data-check="{b1}"') < page.index(f'data-check="{loose}"')
    assert f'data-round-area="{builder["id"]}"' in page

    assert admin.post("/manage/testing/areas/order", data={"column": "areas", "keys": [str(card["id"]), str(builder["id"])]}).status_code == 200
    page = admin.get("/manage/testing").text
    assert page.index(f'data-check="{b1}"') < page.index(f'data-check="{a1}"')
    assert any(i["what"] == "order" and i["text"].endswith("The Testing card, Item Builder") for i in inbox(admin))

    admin.post("/manage/testing/round", data={"area": str(builder["id"])})
    card_html = admin.get("/manage/testing/card").text
    assert f'data-check-card="{a1}"' in card_html and "1 of 2" in card_html  # (just that area's two)


def test_one_area_at_a_time_is_in_claudes_hands(admin):
    """The quality rule Brett asked for (Nov 17): Claude takes up one area, finishes it, then the next; it goes first."""
    one, two = area(admin, "One"), area(admin, "Two")
    assert admin.post(f"/api/areas/{two['id']}", json={"fixing": True}, headers=KEY).json()["fixing"] is True
    r = admin.post(f"/api/areas/{one['id']}", json={"fixing": True}, headers=KEY)
    assert r.status_code == 409 and "Two" in r.text
    listed = admin.get("/api/areas", headers=KEY).json()["areas"]
    assert [x["title"] for x in listed] == ["Two", "One"] and listed[0]["says"] == "Claude fixing"
    admin.post(f"/api/areas/{two['id']}", json={"fixing": False}, headers=KEY)
    assert admin.post(f"/api/areas/{one['id']}", json={"fixing": True}, headers=KEY).status_code == 200


def test_where_an_area_is_comes_from_its_notes_and_checks(admin, db):
    """Found, Questions (Claude asked: on you), Claude fixing, Ready for you (on you), Done; never kept, always worked out."""
    fb = note(admin).json()["id"]
    a = area(admin, "Battle", notes=[fb])
    says = lambda: next(x for x in admin.get("/api/areas", headers=KEY).json()["areas"] if x["id"] == a["id"])
    assert says()["says"] == "Found" and says()["next"] == "Waits its turn"
    admin.post(f"/api/feedback/{fb}", json={"note": "Which list do you mean?", "status": "question"}, headers=KEY)
    assert says()["says"] == "Questions" and says()["yours"] and says()["next"] == "1 question for you"
    admin.post(f"/api/feedback/{fb}", json={"kind": "broken", "status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/500"}, headers=KEY)
    made = db.scalar(select(Check).where(Check.feedback_id == fb))
    assert made.area_id == a["id"] and says()["says"] == "Claude fixing"  # (the fix's check joins its note's area, on its way)
    admin.post(f"/api/checks/{made.id}", json={"status": "again"}, headers=KEY)
    assert says()["says"] == "Ready for you"
    admin.post(f"/manage/testing/{made.id}", data={"result": "passed"})
    assert says()["says"] == "Done"
    stands = admin.get("/manage/testing?show=areas").text
    assert 'aria-label="Where it stands"' in stands and f'data-area="{a["id"]}"' not in stands.split("ar-done")[0]  # (Done, folded below)


def test_claudes_inbox_hears_what_brett_does_and_keeps_its_place(admin, player, db):
    """Brett's ask (Nov 17): the loop between askdnd and the Claude app is robust. Every note that reaches Claude, every
    answer, every check marked lands in the inbox; a player's note only once an admin approves it; Claude's read mark is
    kept in askdnd, never goes back, and asking says Claude is listening."""
    from tests.roles import set_role

    sent = note(admin).json()["id"]
    c = check(admin, "Headings stay")
    admin.post(f"/manage/testing/{c}", data={"result": "passed"})
    items = inbox(admin)
    assert [i["what"] for i in items] == ["note", "check"] and items[0]["feedback_id"] == sent and "from" in items[0]["text"]
    assert "Passed" in items[1]["text"] and items[1]["check_id"] == c

    admin.post(f"/api/feedback/{sent}", json={"note": "Swim or fly?", "status": "question"}, headers=KEY)
    admin.post(f"/manage/feedback/{sent}", data={"to": "answer", "answer": "Swim."})
    assert inbox(admin)[-1]["what"] == "answer" and "Swim." in inbox(admin)[-1]["text"]

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    theirs = note(player, text="The rolls panel closes.").json()["id"]
    assert not any(i["feedback_id"] == theirs for i in inbox(admin))  # (an admin approves a player's first)
    admin.post(f"/manage/feedback/{theirs}", data={"to": "new"})
    assert inbox(admin)[-1]["feedback_id"] == theirs and "approved" in inbox(admin)[-1]["text"]

    last = inbox(admin)[-1]["id"]
    assert admin.post("/api/claude/inbox/read", json={"upto": last}, headers=KEY).json()["read"] == last
    assert inbox(admin) == []
    assert admin.post("/api/claude/inbox/read", json={"upto": 1}, headers=KEY).json()["read"] == last  # (never back)
    stands = admin.get("/manage/testing?show=areas").text
    assert 'data-listening="on"' in stands


def test_a_standing_rule_areas_and_the_inbox_are_for_admins_and_claude_only(player, dm, admin, db):
    """Testing is for admins (Brett, Nov 16); the inbox and the areas' API answer only Claude's key."""
    one = area(admin, "One")
    for who in (player, dm):
        who.post("/manage/testing/areas/order", data={"keys": [str(one["id"])]})
        assert 'aria-label="Where it stands"' not in who.get("/manage/testing?show=areas").text
    assert admin.get("/api/claude/inbox").status_code == 404 and admin.get("/api/areas").status_code == 404
    assert admin.post("/api/areas", json={"title": "Sneaky"}).status_code == 404
    assert not any(i.what == "order" for i in db.scalars(select(InboxItem)))
    assert db.scalar(select(Area).where(Area.title == "Sneaky")) is None
