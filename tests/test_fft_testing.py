"""Testing (Found, Fixed, Tried: app/fft/testing_page.py; screens 1–8 of docs/mockups/found-fixed-tried/): For you is
everything that's Brett's turn; a round takes the checks for this device page by page with the card; Something's
wrong…, Can't try… and Change result go through the rules."""

import re

import pytest
from sqlalchemy import select

from app.fft import rules
from app.fft.models import FftArea, FftCheck, FftEvent, FftIdea, FftIssue, FftItem, FftNote, FftRound, FftTry
from app.importer import import_bundle
from tests.table_setup import BUNDLE

IPHONE = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Safari/604.1"}


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


def _area(db, title="Manage"):
    item = FftItem(title="Fixes and polish", section="now", place=1, standing=True)
    db.add(item)
    db.flush()
    a = FftArea(item_id=item.id, title=title, place=1)
    db.add(a)
    db.flush()
    return a


def _check(db, title="Rest stays on one line", path="/party", devices=None, area=None, issue=None, preflight=True, **kw):
    c = rules.write_check(db, "claude", title=title, steps=["Open the sheet.", "Press [Rest]."], expect="One line.", path=path,
                          area_id=area.id if area else None, devices=devices, issue_ids=[issue.id] if issue else None, **kw)
    if preflight:
        rules.preflight(db, "claude", c, True)
    db.flush()
    return c


def wrong(client, c, text="Big C's name is cut off.", blocking=True, **more):
    return client.post(f"/manage/testing/checks/{c.id}/wrong", json={"text": text, "blocking": blocking, "url": "/party",
                                                                     "context": {"page": "Party"}, "html": "<main></main>", "pictures": [], **more})


# ------------------------------------------------------------------ who


def test_a_standing_rule_testing_is_for_admins_only(player, dm, admin, db):
    """A standing rule (Brett, Nov 16, docs/mockups/testing/ 5B: admins, and his test accounts through View as): a
    player or the DM gets no Testing page, no card, no marking."""
    c = _check(db)
    for who in (player, dm):
        assert who.get("/manage/testing").status_code in (303, 403, 404)
        assert who.get("/manage/for-you").status_code in (303, 403, 404) and who.get("/manage/for-you/count").status_code in (303, 403, 404)
        assert who.get("/manage/testing/card").status_code in (303, 403, 404)
        who.post(f"/manage/testing/checks/{c.id}/try", data={"result": "passed"})
        wrong(who, c)
    assert db.scalar(select(FftTry)) is None and db.scalar(select(FftIssue)) is None


# ------------------------------------------------------------------ For you (screen 1)


def test_for_you_is_everything_thats_yours_in_one_list(admin, db):
    a = _area(db)
    mine = _check(db, area=a)
    _check(db, title="Not tried by Claude yet", area=a, preflight=False)  # (R18: Claude's try first)
    phone = _check(db, title="On a phone", area=a, devices=["iphone"])
    _check(db, title="The Mini runs this", area=a, devices=["mac_mini"])  # (Claude's own: never in your list)
    rules.ask(db, "claude", about="area", about_id=a.id, text="Should the card start on the left?", choices=[{"label": "Left"}, {"label": "Right"}], mine=0)
    n = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="problem", text="Rests are wrong.")
    rules.send_note(db, user_id=None, first_name="Brett", role="admin", kind="idea", text="A dice tray.")
    road = FftItem(title="Retire the old environment", place=2, next_whose="brett", next_step="A click in Railway")
    db.add(road)
    db.flush()
    page = admin.get("/manage/for-you").text
    assert f'data-row="c{mine.id}"' in page and f'data-row="c{phone.id}"' in page and "Not tried by Claude yet" not in page
    assert "The Mini runs this" not in page and "The Mini runs this" in admin.get("/manage/testing?show=claudes").text
    assert "on your iPhone" in page and f'data-row="n{n.id}"' in page and f'data-row="r{road.id}"' in page and 'data-kind="question"' in page
    assert f'data-row="d{db.scalar(select(FftIdea.id))}"' in page
    assert "▶ Start round · 1 check" in page  # (only what this device can try)
    assert "▶ Start round · 1 check" in admin.get("/manage/for-you", headers=IPHONE).text


def test_for_you_is_its_own_page_grouped_by_what_you_do(admin, db):
    """Brett, Nov 19 (the work flow's slice 2): For you leaves Testing for its own page, grouped Try, Decide, Look at,
    From the table, From the Roadmap; its count is on the Admin gear; old links to it still arrive."""
    a = _area(db)
    c = _check(db, area=a)
    rules.ask(db, "claude", about="area", about_id=a.id, text="Left or right?", choices=[{"label": "Left"}, {"label": "Right"}], mine=0)
    rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="problem", text="Rests are wrong.")
    db.add(FftItem(title="A click in Railway", place=2, next_whose="brett", next_step="Rename the service"))
    db.flush()
    page = admin.get("/manage/for-you").text
    sections = re.findall(r'data-section="(\w+)"', page)
    assert sections == ["try", "decide", "table", "roadmap"]  # (in that order; Look at only when there's something)
    assert f'data-group="a{a.id}"' in page and 'data-group="decide"' not in page  # (Try by area; Decide one list, its area on the row)
    assert f"{a.title} · Claude asks" in page
    assert 'data-fft-page="for-you"' in page and 'data-tab="foryou"' not in page and 'data-do="start-round"' in page
    stands = admin.get("/manage/testing").text
    assert 'data-tab="stands"' in stands and 'class="on" data-tab="stands"' in stands and 'data-do="start-round"' not in stands
    for old in ("/manage/testing?show=foryou", f"/manage/testing?open=c{c.id}"):
        r = admin.get(old, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/manage/for-you")
    assert admin.get("/manage/testing", follow_redirects=False).status_code == 200
    assert admin.get("/manage/for-you/count").json() == {"n": 4}
    assert "data-for-you-count" in admin.get("/party").text  # (the badge's place on the Admin gear, on every page)
    menu = admin.get("/manage/feedback").text
    assert 'data-item="for-you"' in menu and 'data-manage-count="for-you"' in menu and 'data-manage-count="testing"' not in menu


def test_a_check_reads_as_the_card_will_show_it(admin, db):
    issue = rules.new_issue(db, "claude", "The ⋯ menu won't close")
    c = _check(db, issue=issue, why="")
    rules.start_fixing(db, "claude", issue)
    rules.fix_live(db, "askdnd", issue, "abc")
    db.flush()
    page = admin.get(f"/manage/for-you?open=c{c.id}").text
    assert f'data-fft-check="{c.id}"' in page and 'class="walk"' in page and "One line." in page
    assert "The ⋯ menu won&#39;t close" in page or "The ⋯ menu won't close" in page
    assert 'data-do="try-it"' in page and 'data-do="passed"' in page and 'data-do="wrong"' in page and 'data-history' in page


# ------------------------------------------------------------------ a round (screens 2, 4, 5)


def test_a_round_goes_page_to_page_and_passed_moves_on_with_undo(admin, db):
    a = _area(db)
    first = _check(db, title="First", path="/party", area=a)
    second = _check(db, title="Second", path="/help", area=a)
    r = admin.post("/manage/testing/round", follow_redirects=False)
    assert r.headers["location"] == "/party" and rules.round_open(db) is not None
    assert f'data-check-card="{first.id}"' in admin.get("/manage/testing/card?at=/party").text
    assert 'id="check-card"' in admin.get("/party").text  # (the card's slot on every page while the round is open)
    r = admin.post(f"/manage/testing/checks/{first.id}/try", data={"result": "passed", "seen": "to_try"}, follow_redirects=False)
    assert r.headers["location"] == "/help"
    undo = admin.get("/help").text
    t = db.scalar(select(FftTry).where(FftTry.check_id == first.id))
    assert f"/manage/testing/tries/{t.id}/undo" in undo  # (Undo in the corner card)
    admin.post(f"/manage/testing/tries/{t.id}/undo")
    assert rules.check_state(db, first)["state"] == "to_try" and f'data-check-card="{first.id}"' in admin.get("/manage/testing/card").text
    admin.post(f"/manage/testing/checks/{first.id}/try", data={"result": "passed"})
    r = admin.post(f"/manage/testing/checks/{second.id}/try", data={"result": "passed"}, follow_redirects=False)
    assert r.headers["location"].startswith("/manage/for-you") and rules.round_open(db) is not None  # (the last one doesn't end it)
    card = admin.get("/manage/testing/card").text
    assert "data-round-done" in card and 'data-do="end-round"' in card  # (Brett's round, Nov 18: only End round ends it)
    admin.post("/manage/testing/round/end")
    assert rules.round_open(db) is None and "data-round-done" not in admin.get("/manage/testing/card").text
    ended = db.scalar(select(FftEvent).where(FftEvent.kind == "round_ended").order_by(FftEvent.id.desc()))
    assert ended.actor.startswith("user:")  # (whose hand ended it)


def test_try_it_on_one_check_ends_with_it(admin, db):
    """▶ Try it on one check isn't a round to Brett: passing it ends the round it opened, so nothing is left open that
    stops a merge (R11); only a round he started with ▶ Start round waits for End round (his round, Nov 18)."""
    c = _check(db)
    admin.post(f"/manage/testing/checks/{c.id}/go")
    assert rules.round_open(db) is not None
    admin.post(f"/manage/testing/checks/{c.id}/try", data={"result": "passed"})
    assert rules.round_open(db) is None and "data-round-done" not in admin.get("/manage/testing/card").text


def test_while_a_round_is_open_nothing_merges(admin, db):
    """R11."""
    issue = rules.new_issue(db, "claude", "Something else")
    rules.start_fixing(db, "claude", issue)
    _check(db)
    admin.post("/manage/testing/round")
    assert rules.may_merge(db, issue) == (False, "Brett's round is open: nothing merges until it ends (only an issue that stops his round may).")
    admin.post("/manage/testing/round/end")
    assert rules.may_merge(db, issue)[0] and db.scalar(select(FftRound)).ended_at is not None


def test_somethings_wrong_fails_the_try_and_another_adds_to_it(admin, db):
    c = _check(db)
    admin.post(f"/manage/testing/checks/{c.id}/go")
    r = wrong(admin, c, stops_round=True)
    assert r.json()["failed"] and rules.check_state(db, c)["state"] == "failed"
    t = db.get(FftTry, r.json()["try"])
    issue = db.get(FftIssue, r.json()["issue"])
    note = db.scalar(select(FftNote).where(FftNote.issue_id == issue.id))
    assert note.text == "Big C's name is cut off." and note.state == "filed" and note.try_id == t.id
    assert rules.stops_round(db, issue) and rules.may_merge(db, issue)[0]  # (it stops the round: Claude may fix it now)
    card = admin.get("/manage/testing/card").text
    assert "data-cc-failed" in card and 'data-do="another"' in card and f"/manage/testing/tries/{t.id}/change" in card
    r2 = wrong(admin, c, text="And the Send line is wrong.", **{"try": t.id})
    assert r2.json()["try"] == t.id and r2.json()["issue"] != issue.id  # (the same try, a second issue)
    assert len(db.scalars(select(FftTry).where(FftTry.check_id == c.id)).all()) == 1


def test_an_issue_that_doesnt_stop_it_is_sent_on_its_own(admin, db):
    c = _check(db)
    r = wrong(admin, c, text="A typo in the heading.", blocking=False)
    assert not r.json()["failed"] and rules.check_state(db, c)["state"] == "to_try" and db.get(FftIssue, r.json()["issue"]).state == "to_fix"


def test_still_happening_sends_a_fixed_issue_back(admin, db):
    issue = rules.new_issue(db, "claude", "The ⋯ menu won't close")
    c = _check(db, issue=issue)
    rules.start_fixing(db, "claude", issue)
    rules.fix_live(db, "askdnd", issue, "abc")
    db.flush()
    asked = admin.get(f"/manage/testing/checks/{c.id}/wrong").json()
    assert [i["id"] for i in asked["issues"]] == [issue.id]
    wrong(admin, c, text="Still won't close.", issue=issue.id)
    assert issue.state == "to_fix" and rules.check_state(db, c)["state"] == "failed"


def test_cant_try_later_blocked_and_wrong(admin, db):
    c = _check(db)
    assert "Can&#39;t try it?" in admin.get(f"/manage/testing/checks/{c.id}/cant").text or "Can't try it?" in admin.get(f"/manage/testing/checks/{c.id}/cant").text
    admin.post(f"/manage/testing/checks/{c.id}/try", data={"result": "cant", "cant": "later"})
    assert rules.check_state(db, c)["state"] == "later"
    blocker = rules.new_issue(db, "claude", "The page won't load")
    db.flush()
    admin.post(f"/manage/testing/checks/{c.id}/try", data={"result": "cant", "cant": "blocked", "blocked_by": blocker.id})
    assert rules.check_state(db, c)["state"] == "blocked"
    admin.post(f"/manage/testing/checks/{c.id}/try", data={"result": "cant", "cant": "wrong", "why": "No note was open"})
    assert rules.check_state(db, c)["state"] == "wrong"


def test_change_result_corrects_and_withdraws_what_only_that_try_found(admin, db):
    """R6: a correction is a new try; nothing is deleted."""
    c = _check(db)
    issue_id = wrong(admin, c).json()["issue"]
    t = db.scalar(select(FftTry).where(FftTry.check_id == c.id))
    window = admin.get(f"/manage/testing/tries/{t.id}/change").text
    assert "Correct this try" in window and "closes as withdrawn" in window
    admin.post(f"/manage/testing/tries/{t.id}/change", data={"result": "untried", "why": "Pressed the wrong one"})
    db.refresh(t)
    assert t.replaced and rules.check_state(db, c)["state"] == "to_try"
    issue = db.get(FftIssue, issue_id)
    assert issue.state == "closed" and issue.close_reason == "withdrawn"  # (only that try found it: withdrawn, still findable)
    history = admin.get(f"/manage/for-you?open=c{c.id}").text
    assert "<s>" in history and "Pressed the wrong one" in history


def test_a_question_answered_in_for_you_names_itself(admin, db):
    """R13: the answer names its question and moves the issue back to Claude."""
    issue = rules.new_issue(db, "claude", "How should a closed issue say why?")
    q = rules.ask(db, "claude", about="issue", about_id=issue.id, text="Words or a pill?", choices=[{"label": "Words"}, {"label": "A pill"}], mine=0)
    db.flush()
    assert issue.state == "asks"
    page = admin.get(f"/manage/for-you?open=q{q.id}").text
    assert "Claude&#39;s pick" in page or "Claude's pick" in page
    admin.post(f"/manage/testing/questions/{q.id}", data={"text": ""})
    assert q.answered_at is None  # (nothing picked for you)
    admin.post(f"/manage/testing/questions/{q.id}", data={"choice": "1"})
    assert q.answer_choice == 1 and issue.state == "to_fix"


def test_a_mockup_asked_about_an_issue_opens_from_for_you_and_shows_in_its_conversation(admin, db):
    """Brett, Nov 17: a mockup asked as a loose decision had no link to it, sat in no area, and wasn't on the issue it
    answers. Asked about the issue with its document, For you opens the mockup by its name, and the issue's
    conversation shows the question, the answers with Claude's pick, then the answer, in the order it happened."""
    from app.fft.models import FftLine

    issue = rules.new_issue(db, "claude", "The reader blends together")
    db.add(FftLine(issue_id=issue.id, who="claude", to="", text="I'll draw it."))
    db.flush()
    with pytest.raises(rules.RuleError):  # (only a mockup Manage › Documents lists)
        rules.ask(db, "claude", about="issue", about_id=issue.id, text="Which?", doc_path="docs/mockups/nothing-here/index.html")
    q = rules.ask(db, "claude", about="issue", about_id=issue.id, text="Which reader should I build?",
                  choices=[{"label": "Cards"}, {"label": "Tabs"}], mine=0, doc_path="docs/mockups/fft-reader/index.html")
    db.flush()
    page = admin.get(f"/manage/for-you?open=q{q.id}").text
    assert 'data-modal-url="/manage/documents/mockups-fft-reader-index?part=1" data-modal-size="full" data-open-doc>Open mockup</a>' in page
    assert "Feedback&#39;s Reader: Sections" in page
    window = admin.get("/manage/documents/mockups-fft-reader-index?part=1").text  # (the mockup alone, in a window over For you)
    assert 'id="peek-title"' in window and 'class="doc-frame"' in window and "<main" not in window
    reader = admin.get(f"/manage/feedback?tab=open&open=i{issue.id}").text
    assert f'data-question="{q.id}"' in reader and f'href="/manage/for-you?open=q{q.id}" data-do="answer"' in reader
    assert reader.index("I&#39;ll draw it.") < reader.index(f'data-question="{q.id}"')
    admin.post(f"/manage/testing/questions/{q.id}", data={"choice": "0", "text": "with counts"})
    reader = admin.get(f"/manage/feedback?tab=open&open=i{issue.id}").text
    assert "data-answered" in reader and 'data-choice="0" class="on"' in reader and "with counts" in reader


def test_try_it_sees_a_check_through_its_players_eyes(admin, db):
    """Brett's Board 1 (Nov 16): ▶ Try it turns on View as for the check's character's player; Testing stays the
    admin's own while viewing; marking it ends View as. View as's own rule decides: refused, it opens as you."""
    from tests.table_setup import char, owned_by

    cole = char(db, "Cole")
    owned_by(db, cole, "player@example.com")
    db.flush()
    c = _check(db, path=f"/characters/{cole.id}/battle")
    c.as_character = cole.id
    db.flush()
    r = admin.post(f"/manage/testing/checks/{c.id}/go", follow_redirects=False)
    assert r.headers["location"] == f"/characters/{cole.id}/battle" and "Viewing as" in admin.get("/").text
    assert f'data-check-card="{c.id}"' in admin.get("/manage/testing/card").text
    r = admin.post(f"/manage/testing/checks/{c.id}/try", data={"result": "passed"}, follow_redirects=False)
    assert r.status_code == 303 and "Viewing as" not in admin.get("/").text


def test_a_live_issue_names_its_checks_and_is_claudes_while_they_cant_be_tried(admin, db):
    """Issue 26 (Brett's round, Nov 18): an issue said Ready to try and Yours without naming its check, while that check
    was blocked. A live issue names its checks with where each stands, in Testing's words; while none of them is Brett's
    to try (blocked, being rewritten), the issue is Claude's."""
    from app.fft import views

    issue = rules.new_issue(db, "claude", "The card runs off the top", feature="testing")
    c = _check(db, title="A long check stays on screen", issue=issue)
    rules.start_fixing(db, "claude", issue)
    rules.fix_live(db, "askdnd", issue, "abc123")
    db.flush()
    assert views.issue_turn(db, issue) == ("yours", "")
    assert views.issue_sentence(db, issue) == "Live: try its check in For you."
    page = admin.get(f"/manage/feedback?tab=ready&open=i{issue.id}").text
    assert f'data-check="{c.id}"' in page and "· To try" in page and "· to_try" not in page

    blocker = rules.new_issue(db, "claude", "The page won't load")
    db.flush()
    admin.post(f"/manage/testing/checks/{c.id}/try", data={"result": "cant", "cant": "blocked", "blocked_by": blocker.id})
    db.expire_all()
    assert views.issue_turn(db, issue) == ("claude", "")  # (nothing to try: never Yours)
    assert views.issue_sentence(db, issue) == "Live, but its check can't be tried yet: Claude's to sort out."
    assert "· Blocked" in admin.get(f"/manage/feedback?tab=ready&open=i{issue.id}").text
    assert f'data-check="{c.id}"' in admin.get(f"/manage/testing?show=claudes&open=i{issue.id}").text  # (Testing names it too: Claude's list)
    assert '<span data-device="laptop"><b>Laptop</b> · Blocked</span>' in admin.get(f"/manage/testing?show=claudes&open=c{c.id}").text  # (Testing's words, never a code)


def test_bretts_order_and_an_area_with_open_work_never_archived(admin, db):
    """The review of PR #417: Brett's order (dragging items and areas) and the area actions had no test once the old
    browser test went. The order is kept as dragged; an area with open issues is never archived (pick_next skips an
    archived area, so its work would never reach Claude)."""
    from app.fft.models import FftArea, FftItem

    build = FftItem(title="A build", section="now", place=5)
    db.add(build)
    db.flush()
    a = rules.new_area(db, "claude", build, "First")
    b = rules.new_area(db, "claude", build, "Second")
    other = FftItem(title="Another", section="next", place=6)
    db.add(other)
    db.flush()
    assert admin.post("/manage/testing/order", data={"column": "items", "keys": [str(other.id), str(build.id)]}).status_code == 200
    db.expire_all()
    assert db.get(FftItem, other.id).place < db.get(FftItem, build.id).place
    assert admin.post("/manage/testing/order", data={"column": f"item-{build.id}", "keys": [str(b.id), str(a.id)]}).status_code == 200
    db.expire_all()
    assert db.get(FftArea, b.id).place < db.get(FftArea, a.id).place
    issue = rules.new_issue(db, "claude", "Still open", area_id=a.id)
    db.flush()
    with pytest.raises(rules.RuleError):
        rules.archive_area(db, "claude", db.get(FftArea, a.id))
    rules.close(db, "claude", issue, "withdrawn")
    rules.archive_area(db, "claude", db.get(FftArea, a.id))
    assert db.get(FftArea, a.id).archived
