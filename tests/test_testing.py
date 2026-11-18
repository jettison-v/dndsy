"""Testing in askdnd (app/testing.py; Brett's idea and picks 1A, 2A, 3A, 4A, 5B, 6C, Nov 16; docs/mockups/testing/): a
check for an admin to try, written by Claude with its key, marked by the admin in the Reader or in a round, where
Failed… is a feedback note tied to the check."""

import pytest
from sqlalchemy import select

from app import config
from app.importer import import_bundle
from app.models import Check, Feedback
from tests.table_setup import BUNDLE

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



def test_claude_names_only_a_note_that_exists_and_a_known_setup(admin):
    assert admin.post("/api/checks", json={"title": "A", "feedback_id": 999999}, headers=KEY).status_code == 400
    assert admin.post("/api/checks", json={"title": "A", "setup": "moon"}, headers=KEY).status_code == 400
    assert admin.post("/api/checks", json={"title": ""}, headers=KEY).status_code == 400
    for bad in ({"path": "javascript:alert(1)"}, {"path": "//elsewhere.example"}, {"pr": "javascript:alert(1)"}):  # (links on the page)
        assert admin.post("/api/checks", json={"title": "A", **bad}, headers=KEY).status_code == 400



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
