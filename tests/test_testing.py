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
    a feedback note that marks the check failed and ties it, and the card stays on it (Brett's 2A, Nov 17) until Done ·
    Next check; the last one ends the round."""
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
    assert failed.status == "failed" and db.get(Feedback, sent["id"]).check_id == two["id"] and sent["check"] == two["id"]
    assert db.get(Feedback, sent["id"]).context["check"] == two["id"]
    card = admin.get("/manage/testing/card").text
    assert f'data-check-card="{two["id"]}"' in card and "data-check-next" in card and f'data-issue="{sent["id"]}"' in card  # (it stays)
    r = admin.post(f"/manage/testing/{two['id']}/next", follow_redirects=False)
    assert r.headers["location"] == "/party"
    r = admin.post(f"/manage/testing/{three['id']}", data={"result": "skipped", "why": "data"}, follow_redirects=False)
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
    assert r.headers["location"] == f"/manage/testing?show=done&check={c['id']}" and admin.get("/manage/testing/card").status_code == 204
    assert f'data-check-read="{c["id"]}"' in admin.get(r.headers["location"]).text  # (back to it, where it's now listed)


def test_claude_moves_a_fixed_check_back_to_try_again(admin, db):
    c = add(admin)
    admin.post(f"/manage/testing/{c['id']}", data={"result": "skipped", "why": "data"})
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
    assert db.scalar(select(Feedback).where(Feedback.check_id.is_not(None))) is None


def test_go_sees_a_check_through_its_players_eyes_and_comes_back_to_your_own(admin, db):
    """Brett's Board 1 (Nov 16): Go turns on View as for the check's character's player first; Testing stays the
    admin's own while viewing (its card, its marks); marking it ends View as. View as's own rule decides who may be
    viewed: refused, the check opens as you, with why."""
    from tests.table_setup import char, owned_by

    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    db.flush()
    c = add(admin, path=f"/characters/{cole.id}/battle", as_character=cole.id, as_who="Cole's player")
    r = admin.post(f"/manage/testing/{c['id']}/go", follow_redirects=False)
    assert r.headers["location"] == f"/characters/{cole.id}/battle"
    assert "Viewing as" in admin.get("/").text  # (View as is on)
    assert f'data-check-card="{c["id"]}"' in admin.get("/manage/testing/card").text  # (the card is still the admin's)
    r = admin.post(f"/manage/testing/{c['id']}", data={"result": "passed"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == f"/manage/testing?show=done&check={c['id']}"  # (not refused while viewing)
    assert "Viewing as" not in admin.get("/").text  # (back to your own view)

    own = add(admin, path="/party", as_character=cole.id)
    owned_by(db, cole, "admin@example.com")  # (the admin's own character: View as never views yourself)
    db.flush()
    r = admin.post(f"/manage/testing/{own['id']}/go", follow_redirects=False)
    assert r.headers["location"] == "/party" and "Viewing as" not in admin.get("/party").text


def test_a_fix_on_its_way_waits_under_failed_until_its_live(admin, db):
    """Brett's 4A: Claude marks a failed check fixed with its PR; it waits under Failed (Fix on its way) until the fix is
    live, when `feedback.py check live` brings it back as Try again."""
    c = add(admin)
    r = admin.post(f"/api/checks/{c['id']}", json={"status": "fixed", "pr": "https://github.com/jettison-v/dndsy/pull/402"}, headers=KEY).json()
    assert r["status"] == "fixed" and r["says"] == "Fix on its way"
    assert f'data-check="{c["id"]}"' in admin.get("/manage/testing?show=failed").text
    assert f'data-check="{c["id"]}"' not in admin.get("/manage/testing").text  # (not Ready until it's live)
    assert admin.post("/api/checks", json={"title": "A", "as_character": 999999}, headers=KEY).status_code == 400


def test_check_live_brings_back_only_fixes_askdnd_runs(monkeypatch):
    """`feedback.py check live` (deploy_check.py runs it after each deploy): a fixed check whose PR is merged and inside
    the running commit comes back as Try again; one whose PR isn't merged, or merged after what runs, waits."""
    import io
    import json as _json
    import subprocess as sp

    from scripts import feedback as fbs

    checks = [{"id": 1, "pr": "https://github.com/jettison-v/dndsy/pull/10"}, {"id": 2, "pr": "https://github.com/jettison-v/dndsy/pull/11"},
              {"id": 3, "pr": "https://github.com/jettison-v/dndsy/pull/12"}, {"id": 4, "pr": ""}]
    moved = []
    monkeypatch.setattr(fbs, "call", lambda base, path, body=None: (moved.append((path, body)) or b"{}") if body else _json.dumps({"items": checks}).encode())
    asked = []
    monkeypatch.setattr(fbs.urllib.request, "urlopen", lambda req, timeout=0: (asked.append(req), io.BytesIO(b'{"version": "abc123"}'))[1])
    prs = {"10": {"state": "MERGED", "mergeCommit": {"oid": "inside"}}, "11": {"state": "OPEN", "mergeCommit": None},
           "12": {"state": "MERGED", "mergeCommit": {"oid": "later"}}}

    def run(cmd, **kw):
        if cmd[:3] == ["gh", "pr", "view"]:
            return sp.CompletedProcess(cmd, 0, stdout=_json.dumps(prs[cmd[3]]))
        if cmd[:2] == ["git", "merge-base"]:
            return sp.CompletedProcess(cmd, 0 if cmd[3] == "inside" and cmd[4] == "abc123" else 1)
        return sp.CompletedProcess(cmd, 0)

    monkeypatch.setattr(sp, "run", run)
    fbs.live("https://askdnd.example")
    assert moved == [("/api/checks/1", {"status": "again"})]
    assert asked[0].get_header("User-agent") == "askdnd-feedback-script"  # (askdnd.ai turns a bare client away: 403)


def test_a_fixed_broken_note_comes_with_its_check(admin, db):
    """Brett, Nov 16: every broken note gets its check. Claude marking an admin's broken note done with its PR makes one
    (Fix on its way, with Claude's steps and the note's own page), once; it goes to the admin's queue when live."""
    fb = note(admin).json()["id"]
    admin.post(f"/api/feedback/{fb}", json={"kind": "broken", "tell": "Fixed: Speed shows the swim speed now."}, headers=KEY)
    body = {"status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/405", "check_do": "Open Battle.\nLook at Speed.",
            "check_expect": "Swim 50 under it."}
    admin.post(f"/api/feedback/{fb}", json=body, headers=KEY)
    admin.post(f"/api/feedback/{fb}", json=body, headers=KEY)  # (again: still one check)
    rows = list(db.scalars(select(Check).where(Check.feedback_id == fb)))
    assert len(rows) == 1
    c = rows[0]
    assert (c.status, c.setup, c.path, c.do, c.expect, c.pr) == ("fixed", "laptop", "/characters/1/battle", "Open Battle.\nLook at Speed.",
                                                                 "Swim 50 under it.", body["pr"])
    assert c.said == "Fixed: Speed shows the swim speed now."


def test_a_players_fix_is_theirs_to_confirm_then_yours_after_three_days(admin, player, db):
    """Brett's 6C: a fix to a player's note asks them, on Notes you sent, Does it work now? Yes passes it; Still broken
    fails it and sends the note back with their words (to an admin first). Unanswered for three days, it's yours."""
    from datetime import timedelta

    from sqlalchemy import update

    from tests.roles import set_role

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    fb = note(player, text="The rolls panel closes by itself.").json()["id"]
    admin.post(f"/api/feedback/{fb}", json={"kind": "broken", "status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/406"}, headers=KEY)
    c = db.scalar(select(Check).where(Check.feedback_id == fb))
    assert c.setup == "player" and c.status == "fixed"
    assert 'data-try="' not in player.get(f"/your-notes?tab=askdnd&note=f{fb}").text  # (not until the fix is live)
    admin.post(f"/api/checks/{c.id}", json={"status": "again"}, headers=KEY)  # (check live, once its PR is in)
    assert f'data-try="{fb}"' in player.get(f"/your-notes?tab=askdnd&note=f{fb}").text
    assert f'data-check="{c.id}"' not in admin.get("/manage/testing").text and f'data-check="{c.id}"' in admin.get("/manage/testing?show=player").text
    assert admin.get("/c/main/manage/counts").json()["testing"] == 0  # (the player's, for now)

    r = player.post(f"/your-notes/feedback/{fb}/works", data={"answer": "no", "text": "It still closes on a new roll."}, follow_redirects=False)
    assert r.status_code == 303
    db.expire_all()
    assert db.get(Check, c.id).status == "failed" and db.get(Feedback, fb).status == "review"  # (back, to an admin first)
    assert "It still closes on a new roll." in db.get(Feedback, fb).thread[-1]["text"]

    db.execute(update(Check).where(Check.id == c.id).values(status="again", asked_at=Check.asked_at - timedelta(days=4)))
    db.flush()
    assert f'data-check="{c.id}"' in admin.get("/manage/testing").text  # (three days unanswered: the admin's)
    assert player.post(f"/your-notes/feedback/{fb}/works", data={"answer": "yes"}).status_code in (200, 303)
    db.expire_all()
    assert db.get(Check, c.id).status == "passed"
    assert admin.post(f"/your-notes/feedback/{fb}/works", data={"answer": "yes"}).status_code == 404  # (only its sender answers)


def test_claudes_own_checks_stay_out_of_the_admins_list(admin, db):
    """The ones Claude runs on the Mac Mini's seats (setup claude) are Claude's: under Claude's chip, to run or run, never
    in the admin's Ready list, round or count."""
    mine = add(admin, title="On the seats", setup="claude")
    ran = add(admin, title="Ran on the seats", setup="claude")
    admin.post(f"/api/checks/{ran['id']}", json={"status": "claude", "said": "12 of 12"}, headers=KEY)
    ready = admin.get("/manage/testing").text
    assert f'data-check="{mine["id"]}"' not in ready and admin.get("/c/main/manage/counts").json()["testing"] == 0
    claude = admin.get("/manage/testing?show=claude").text
    assert f'data-check="{mine["id"]}"' in claude and f'data-check="{ran["id"]}"' in claude


def test_the_code_reviews_edges(admin, player, db, monkeypatch):
    """The code review (Nov 16): a check marked from the list leaves a round where it was; a failed check comes back
    when its note is fixed again (never a second one); a player's idea gets no check; a note's address that would leave
    askdnd (a backslash) makes no link; a later edit doesn't restart a player's three days; a check id that isn't a
    number is ignored, not a server error; Still broken on a closed note is refused; Failed… on staging marks the check
    with askdnd.ai's note."""
    from datetime import UTC, datetime, timedelta

    from app import feedback as fbm
    from tests.roles import set_role

    one, two = add(admin, title="One", path="/party"), add(admin, title="Two", path="/c/main/dm")
    admin.post("/manage/testing/round", data={})
    r = admin.post(f"/manage/testing/{two['id']}", data={"result": "skipped", "why": "data"}, follow_redirects=False)  # (not the round's current one)
    assert r.headers["location"] == f"/manage/testing?show=done&check={two['id']}"
    assert f'data-check-card="{one["id"]}"' in admin.get("/manage/testing/card").text  # (the round is still on One)

    fb = note(admin).json()["id"]
    admin.post(f"/api/feedback/{fb}", json={"kind": "broken", "status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/1"}, headers=KEY)
    c = db.scalar(select(Check).where(Check.feedback_id == fb))
    admin.post(f"/api/checks/{c.id}", json={"status": "failed"}, headers=KEY)
    admin.post(f"/api/feedback/{fb}", json={"status": "new"}, headers=KEY)
    admin.post(f"/api/feedback/{fb}", json={"status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/2"}, headers=KEY)
    db.expire_all()
    assert [(x.id, x.status, x.pr) for x in db.scalars(select(Check).where(Check.feedback_id == fb))] == [(c.id, "fixed", "https://github.com/jettison-v/dndsy/pull/2")]

    set_role(db, "player@example.com", "player")
    admin.post("/manage/accounts/feedback", data={"email": "player@example.com", "on": "1"})
    idea = note(player, kind="idea").json()["id"]
    admin.post(f"/api/feedback/{idea}", json={"status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/3"}, headers=KEY)
    assert db.scalar(select(Check).where(Check.feedback_id == idea)) is None
    sly = note(player, url="https://askdnd.ai/\\evil.example/x").json()["id"]
    admin.post(f"/api/feedback/{sly}", json={"status": "done", "pr": "https://github.com/jettison-v/dndsy/pull/4"}, headers=KEY)
    assert db.scalar(select(Check).where(Check.feedback_id == sly)).path == ""

    mine = db.scalar(select(Check).where(Check.feedback_id == sly))
    admin.post(f"/api/checks/{mine.id}", json={"status": "again"}, headers=KEY)
    db.expire_all()
    mine = db.get(Check, mine.id)
    mine.asked_at = datetime.now(UTC) - timedelta(days=4)
    db.commit()
    admin.post(f"/api/checks/{mine.id}", json={"title": "Renamed"}, headers=KEY)  # (an edit: still asked four days ago)
    assert f'data-check="{mine.id}"' in admin.get("/manage/testing").text

    assert note(admin, check=True).status_code == 200  # (true isn't a check id)
    closed = db.get(Feedback, sly)
    closed.status = "deleted"
    db.commit()
    assert player.post(f"/your-notes/feedback/{sly}/works", data={"answer": "no"}).status_code == 404

    monkeypatch.setattr(config, "STAGING", True)
    monkeypatch.setattr(fbm, "to_prod", lambda n: {"id": 4242, "review": False})
    three = add(admin, title="Three")
    sent = note(admin, check=three["id"]).json()
    db.expire_all()
    assert db.get(Check, three["id"]).status == "failed" and "4242" in db.get(Check, three["id"]).history[-1]["what"] and sent["check"] == three["id"]
