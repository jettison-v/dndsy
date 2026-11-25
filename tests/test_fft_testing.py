"""Testing (Found, Fixed, Tried: app/fft/testing_page.py; screens 1–8 of docs/mockups/found-fixed-tried/): For you is
everything that's Brett's turn; a round takes the checks for this device page by page with the card; Something's
wrong…, Can't try… and Change result go through the rules."""

import re

import pytest
from sqlalchemy import func, select

from app.fft import rules, testing_page
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
    untried = _check(db, title="Not tried by Claude yet", area=a, preflight=False)  # (R18: Claude's try first)
    phone = _check(db, title="On a phone", area=a, devices=["iphone"])
    _check(db, title="The Mini runs this", area=a, devices=["mac_mini"])  # (Claude's own: never in your list)
    rules.ask(db, "claude", about="area", about_id=a.id, text="Should the card start on the left?", choices=[{"label": "Left"}, {"label": "Right"}], mine=0)
    n = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="problem", text="Rests are wrong.")
    rules.send_note(db, user_id=None, first_name="Brett", role="admin", kind="idea", text="A dice tray.")
    road = FftItem(title="Retire the old environment", place=2, next_whose="brett", next_step="A click in Railway")
    db.add(road)
    db.flush()
    page = admin.get("/manage/for-you").text
    assert f'data-row="c{mine.id}"' in page and f'data-row="c{phone.id}"' in page and f'data-row="c{untried.id}"' not in page  # (it's in Claude's hands, the bar's quiet line)
    assert "The Mini runs this" not in page and "The Mini runs this" in admin.get("/manage/work?tab=checks").text
    assert "on your iPhone" in page and f'data-row="n{n.id}"' in page and f'data-row="r{road.id}"' in page and 'data-kind="question"' in page
    assert f'data-row="d{db.scalar(select(FftIdea.id))}"' in page
    assert 'data-need="laptop"' in page and 'data-need="iphone"' in page  # (a group per need, each its own round: Clearer checks)
    # (each need's round starts from any device, saying where its steps are done: he reads on the laptop and taps on the
    # iPhone; issue 104, Nov 23, in place of "only what this device can try starts here")
    assert page.count('name="need" value="laptop"') >= 1 and 'name="need" value="iphone"' in page and "data-need-elsewhere" in page
    on_phone = admin.get("/manage/for-you", headers=IPHONE).text
    assert 'name="need" value="iphone"' in on_phone and 'name="need" value="laptop"' in on_phone


def test_for_you_is_its_own_page_grouped_by_what_you_do(admin, db):
    """Brett, Nov 19 (the work flow's slice 2): For you leaves Testing for its own page, in tables by what you do (since
    issue 111: Decide, From the Roadmap, Try); its count is on the Admin gear; old links to it still arrive."""
    a = _area(db)
    c = _check(db, area=a)
    rules.ask(db, "claude", about="area", about_id=a.id, text="Left or right?", choices=[{"label": "Left"}, {"label": "Right"}], mine=0)
    rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="problem", text="Rests are wrong.")
    db.add(FftItem(title="A click in Railway", place=2, next_whose="brett", next_step="Rename the service"))
    db.flush()
    page = admin.get("/manage/for-you").text
    tables = re.findall(r'data-table="(\w+)"', page)
    assert tables == ["decide", "roadmap", "try"]  # (three tables, quick ones first: issue 111, Brett's picks Nov 24)
    assert f'data-group="laptop:a{a.id}"' in page and 'data-group="decide"' not in page  # (Try by area; Decide one list, its area in From)
    assert 'data-act="question"' in page and f">{a.title}</td>" in page
    assert 'data-fft-page="for-you"' in page and 'data-tab="stands"' not in page and 'data-do="start-round"' in page
    assert 'data-fft-tabs' not in page and 'data-item="for-you" aria-current="page"' in page  # (one way between them: the side list's Our work, Nov 20)
    for old in ("/manage/testing?show=foryou", f"/manage/testing?open=c{c.id}"):
        r = admin.get(old, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"].startswith("/manage/for-you")
    for old, to in (("/manage/testing", "/manage/work"), ("/manage/testing?show=stands", "/manage/work"),  # (Testing became Work, Nov 20)
                    ("/manage/testing?show=claudes", "/manage/work?tab=checks"), (f"/manage/testing?show=done&open=c{c.id}", f"/manage/work?tab=checks&open=c{c.id}")):
        r = admin.get(old, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == to, old
    work = admin.get("/manage/work").text
    assert 'class="on" data-tab="board"' in work and 'data-item="work" aria-current="page"' in work and 'data-do="start-round"' not in work
    assert admin.get("/manage/for-you/count").json() == {"n": 4}
    assert "data-for-you-count" in admin.get("/party").text  # (the badge's place on the Admin gear, on every page)
    assert "4 waiting on you: " in admin.get("/manage/askdnd").text  # (its card on Overview says how much)
    menu = admin.get("/manage/feedback").text
    assert 'data-item="for-you"' in menu and 'data-manage-count="for-you"' in menu and 'data-manage-count="testing"' not in menu


def test_for_you_is_three_tables_with_an_action_word_and_number_on_each_row(admin, db):
    """Issue 111 (Brett's picks on docs/mockups/for-you-tables/, Nov 24): three tables, quick ones first, each with its own
    head above its columns; ten kinds become five action words (Try locally, Try, Answer, Approve, Do); each row says its
    number; a fix live with no check isn't his to look at (it's Claude's gap); an empty table keeps its head and a line."""
    a = _area(db)
    c = _check(db, area=a)
    q = rules.ask(db, "claude", about="area", about_id=a.id, text="Left or right?", choices=[{"label": "Left"}, {"label": "Right"}], mine=0)
    n = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="problem", text="Rests are wrong.")
    bare = rules.new_issue(db, "claude", "Fixed, with nothing to try it by")
    rules.start_fixing(db, "claude", bare)
    rules.fix_live(db, "askdnd", bare, "abc")
    db.flush()
    page = admin.get("/manage/for-you").text
    for key, words in ((f"c{c.id}", ("Try", f"C{c.id}", f"check {c.id}")), (f"q{q.id}", ("Answer", f"Q{q.id}", f"question {q.id}")),
                       (f"n{n.id}", ("Approve", f"N{n.id}", f"note {n.id}"))):
        row = page.split(f'data-row="{key}"', 1)[1].split("</tr>", 1)[0]
        assert f">{words[0]}</span>" in row and f'title="{words[2]}" data-mark="{key}">{words[1]}</abbr>' in row, key  # (P4: short marks, the word on hover)
    assert f'data-row="i{bare.id}"' not in page  # (Claude's: a fix with no check is its gap)
    assert page.count('class="tbx-head"') == 3 and 'data-table="roadmap"' in page and "Nothing from the Roadmap." in page
    assert page.index('data-table="decide"') < page.index('data-table="roadmap"') < page.index('data-table="try"')
    assert "1 to answer · 1 to approve · 1 to try (about" in page


def test_a_check_reads_as_the_card_will_show_it(admin, db):
    issue = rules.new_issue(db, "claude", "The ⋯ menu won't close")
    c = _check(db, issue=issue, why="")
    rules.start_fixing(db, "claude", issue)
    rules.fix_live(db, "askdnd", issue, "abc")
    db.flush()
    page = admin.get(f"/manage/item/c{c.id}").text
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


def test_a_check_for_the_iphone_marked_on_the_laptop_counts_for_the_iphone(admin, db):
    """Issue 104 (Brett, Nov 23: "I started the check on my laptop and executed it on my phone ... so I can read the check
    on the laptop and do the taps on my phone"): ▶ Try it or ▶ Start round on an iPhone check from the laptop counts
    his mark for the iPhone, and the card says to do the steps there. Before, it was a laptop try and the check stayed."""
    phone = _check(db, title="On a phone", devices=["iphone"])
    admin.post(f"/manage/testing/checks/{phone.id}/go")
    card = admin.get("/manage/testing/card").text
    assert f'data-check-card="{phone.id}"' in card and 'data-cc-elsewhere="iphone"' in card
    assert admin.get(f"/manage/testing/checks/{phone.id}/wrong", headers={"Accept": "application/json"}).json()["elsewhere"] is True
    admin.post(f"/manage/testing/checks/{phone.id}/try", data={"result": "passed", "seen": "to_try"})
    t = db.scalar(select(FftTry).where(FftTry.check_id == phone.id))
    assert t.device == "iphone" and rules.check_state(db, phone)["devices"]["iphone"] == "passed"
    again = _check(db, title="Another on a phone", devices=["iphone"])
    admin.post("/manage/testing/round", data={"need": "iphone"})  # (a round of iPhone checks, started on the laptop)
    assert f'data-check-card="{again.id}"' in admin.get("/manage/testing/card").text
    admin.post(f"/manage/testing/checks/{again.id}/try", data={"result": "passed", "seen": "to_try"})
    assert db.scalar(select(FftTry).where(FftTry.check_id == again.id)).device == "iphone"
    lap = _check(db, title="On the laptop")
    admin.post(f"/manage/testing/checks/{lap.id}/go", headers=IPHONE)  # (and the other way round)
    assert "data-cc-elsewhere" in admin.get("/manage/testing/card", headers=IPHONE).text
    admin.post(f"/manage/testing/checks/{lap.id}/try", data={"result": "passed", "seen": "to_try"}, headers=IPHONE)
    assert db.scalar(select(FftTry).where(FftTry.check_id == lap.id)).device == "laptop"
    mine = _check(db, title="Mine here")  # (on its own device, nothing is said)
    admin.post(f"/manage/testing/checks/{mine.id}/go")
    assert "data-cc-elsewhere" not in admin.get("/manage/testing/card").text


def test_end_round_ends_the_round_the_bar_shows_wherever_it_was_started(admin, db):
    """Issue 106 (Brett's note, Nov 23: "The round does not seem to end even though I am clicking it"): the bar shows the
    open round from askdnd, but End round ended only one this browser was holding; a round started on the other device
    (or one this browser had let go of) stayed open, and the press did nothing."""
    c = _check(db)
    from app.models import User

    me = db.scalar(select(User).where(User.email == "admin@example.com"))
    r = rules.open_round(db, f"user:{me.id}", me.id, None, holds=False)  # (opened elsewhere: this browser holds nothing)
    db.flush()
    assert 'data-do="end-round"' in admin.get("/manage/for-you").text
    admin.post("/manage/testing/round/end")
    assert rules.round_open(db) is None and db.get(FftRound, r.id).ended_at is not None
    assert 'data-do="end-round"' not in admin.get("/manage/for-you").text
    admin.post(f"/manage/testing/checks/{c.id}/go")  # (and its own round of one still ends as before)
    admin.post("/manage/testing/round/end")
    assert rules.round_open(db) is None
    admin.post(f"/manage/testing/checks/{c.id}/go")  # (ended from elsewhere: this browser's card goes too)
    rules.end_round(db, "user:other", rules.round_open(db))
    db.flush()
    assert f'data-check-card="{c.id}"' not in admin.get("/manage/testing/card").text


def test_a_round_over_every_area_holds_an_issue_in_none(admin, db):
    """R11: a sitting over every area holds an issue in no area; ending it lets it go."""
    issue = rules.new_issue(db, "claude", "Something else")
    rules.start_fixing(db, "claude", issue)
    _check(db)
    admin.post("/manage/testing/round")
    assert rules.may_merge(db, issue) == (False, "Brett's round is testing this area: it merges when the round ends (only an issue that stops his round may).")
    admin.post("/manage/testing/round/end")
    assert rules.may_merge(db, issue)[0] and db.scalar(select(FftRound)).ended_at is not None


def test_a_round_holds_only_its_own_area(admin, db):
    """A lighter round (Brett's pick, Nov 19, docs/plans/2026-11-19-lighter-rounds.md): ▶ Just this area holds Claude's
    merges in that area only; work in another area still merges."""
    item = rules.new_item(db, "claude", "Two areas", "now", False)
    a, b = rules.new_area(db, "claude", item, "Battle"), rules.new_area(db, "claude", item, "Sheet")
    in_a, in_b = rules.new_issue(db, "claude", "In Battle", area_id=a.id), rules.new_issue(db, "claude", "In Sheet", area_id=b.id)
    for i in (in_a, in_b):
        rules.start_fixing(db, "claude", i)
    _check(db, area=a)
    db.flush()
    admin.post("/manage/testing/round", data={"area": a.id})
    assert rules.round_open(db) is not None and rules.in_open_round(db, a) and not rules.in_open_round(db, b)
    assert not rules.may_merge(db, in_a)[0] and rules.may_merge(db, in_b)[0]


def test_try_it_on_one_check_holds_nothing(admin, db):
    """A lighter round (Brett's pick, Nov 19): ▶ Try it on one check opens its round of one for the card, but never
    stops a merge, its own area's included."""
    item = rules.new_item(db, "claude", "One area", "now", False)
    a = rules.new_area(db, "claude", item, "Battle")
    issue = rules.new_issue(db, "claude", "In Battle", area_id=a.id)
    rules.start_fixing(db, "claude", issue)
    c = _check(db, area=a)
    admin.post(f"/manage/testing/checks/{c.id}/go")
    assert rules.round_open(db) is not None and rules.holding_round(db) is None
    assert not rules.in_open_round(db, a) and rules.may_merge(db, issue)[0]


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


def test_failing_with_an_issue_sent_from_the_check_needs_no_second_note(admin, db):
    """Issue 16 (Brett, Nov 17): "I had already added issues … Should I be allowed to skip logging the last issue?"
    Something's wrong… offers what was sent from this check and didn't stop it; failing with one writes nothing again."""
    c = _check(db)
    sent = wrong(admin, c, text="A typo in the heading.", blocking=False).json()["issue"]
    asked = admin.get(f"/manage/testing/checks/{c.id}/wrong").json()
    assert [(i["id"], i.get("sent")) for i in asked["issues"]] == [(sent, True)]
    notes = db.scalar(select(func.count()).select_from(FftNote))
    assert wrong(admin, c, text="", issue=sent + 99).status_code == 400  # (not one of this check's)
    assert wrong(admin, c, text="").status_code == 400  # (something new needs its words)
    assert wrong(admin, c, text="", issue=sent, blocking=False).status_code == 400  # (named again but not failing it: say what's new)
    r = wrong(admin, c, text="", issue=sent)
    assert r.json()["failed"] and r.json()["issue"] == sent and rules.check_state(db, c)["state"] == "failed"
    assert db.scalar(select(func.count()).select_from(FftNote)) == notes  # (no second note)
    assert not admin.get(f"/manage/testing/checks/{c.id}/wrong").json()["issues"]  # (it stops the check now: not offered again)


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
    history = admin.get(f"/manage/item/c{c.id}").text
    assert "<s>" in history and "Pressed the wrong one" in history


def test_a_question_answered_in_for_you_names_itself(admin, db):
    """R13: the answer names its question and moves the issue back to Claude."""
    issue = rules.new_issue(db, "claude", "How should a closed issue say why?")
    q = rules.ask(db, "claude", about="issue", about_id=issue.id, text="Words or a pill?", choices=[{"label": "Words"}, {"label": "A pill"}], mine=0)
    db.flush()
    assert issue.state == "asks"
    page = admin.get(f"/manage/item/q{q.id}").text
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
    page = admin.get(f"/manage/item/q{q.id}").text
    assert 'data-modal-url="/manage/documents/mockups-fft-reader-index?part=1" data-modal-size="full" data-open-doc>Open mockup</a>' in page
    assert "Feedback&#39;s Reader: Sections" in page
    window = admin.get("/manage/documents/mockups-fft-reader-index?part=1").text  # (the mockup alone, in a window over For you)
    assert 'id="peek-title"' in window and 'class="doc-frame"' in window and "<main" not in window
    reader = admin.get(f"/manage/item/i{issue.id}").text
    assert f'data-question="{q.id}"' in reader and f'href="/manage/for-you?open=q{q.id}" data-panel-url="/manage/item/q{q.id}" data-do="answer"' in reader  # (M2: in the same window)
    assert reader.index("I&#39;ll draw it.") < reader.index(f'data-question="{q.id}"')
    admin.post(f"/manage/testing/questions/{q.id}", data={"choice": "0", "text": "with counts"})
    reader = admin.get(f"/manage/item/i{issue.id}").text
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
    page = admin.get(f"/manage/item/i{issue.id}").text
    assert f'data-check="{c.id}"' in page and "· To try" in page and "· to_try" not in page

    blocker = rules.new_issue(db, "claude", "The page won't load")
    db.flush()
    admin.post(f"/manage/testing/checks/{c.id}/try", data={"result": "cant", "cant": "blocked", "blocked_by": blocker.id})
    db.expire_all()
    assert views.issue_turn(db, issue) == ("claude", "")  # (nothing to try: never Yours)
    assert views.issue_sentence(db, issue) == "Live, but its check can't be tried yet: Claude's to sort out."
    assert "· Blocked" in admin.get(f"/manage/item/i{issue.id}").text
    assert f'data-check="{c.id}"' in admin.get(f"/manage/item/i{issue.id}").text  # (Testing names it too: Claude's list)
    assert '<span data-device="laptop"><b>Laptop</b> · Blocked</span>' in admin.get(f"/manage/item/c{c.id}").text  # (Testing's words, never a code)


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


def test_the_heads_up_before_a_round_holds_a_change_about_to_go_live(admin, player, db):
    """A lighter round, item 3 (Brett's pick A on docs/mockups/round-heads-up/, Nov 19): ▶ Start round first says what
    it would hold when a change of Claude's is about to go live there; Let it go live first opens the round by itself
    once it's live; Cancel lets it go; with nothing in flight the button starts the round at once, as before."""
    item = rules.new_item(db, "claude", "One area", "now", False)
    a = rules.new_area(db, "claude", item, "Battle")
    _check(db, area=a)
    page = admin.get("/manage/for-you").text
    assert 'data-modal-url="/manage/testing/round/heads-up"' not in page  # (nothing in flight: it starts at once)
    issue = rules.new_issue(db, "claude", "The Count wraps", area_id=a.id)
    rules.start_fixing(db, "claude", issue)
    rules.fix_ready(db, "claude", issue, "https://github.com/x/y/pull/431")
    db.flush()
    assert [g["n"] for g in rules.in_flight(db, rules.round_areas(db), whole=True)] == ["431"]
    page = admin.get("/manage/for-you").text
    assert 'data-modal-url="/manage/testing/round/heads-up?need=laptop" data-do="start-round"' in page
    window = admin.get("/manage/testing/round/heads-up").text
    assert 'data-pr="431"' in window and 'data-do="round-after"' in window and 'data-do="round-now"' in window
    assert player.post("/manage/testing/round/after").status_code in (303, 403) and not rules.after_state(db)["on"]  # (admins only)
    admin.post("/manage/testing/round/after")
    assert rules.after_state(db)["on"] and rules.round_open(db) is None
    assert 'data-stat="after"' in admin.get("/manage/for-you").text
    rules.fix_live(db, "claude", issue, "abc1234")  # (it's live: the round opens by itself, and holds)
    assert not rules.after_state(db)["on"] and rules.holding_round(db) is not None
    admin.post("/manage/testing/round/end")
    issue2 = rules.new_issue(db, "claude", "Another", area_id=a.id)
    rules.start_fixing(db, "claude", issue2)
    rules.fix_ready(db, "claude", issue2, "https://github.com/x/y/pull/432")
    admin.post("/manage/testing/round/after")
    admin.post("/manage/testing/round/after/cancel")
    assert not rules.after_state(db)["on"]


def test_pausing_says_what_it_would_hold(admin, db):
    """The heads-up's second part: Deploys › Paused's reason box says what pausing holds, when something's in flight."""
    assert "data-holds-flight" not in admin.get("/manage/for-you").text
    issue = rules.new_issue(db, "claude", "The Count wraps")
    rules.start_fixing(db, "claude", issue)
    rules.fix_ready(db, "claude", issue, "https://github.com/x/y/pull/433")
    db.flush()
    page = admin.get("/manage/for-you").text
    assert "data-holds-flight" in page and "The Count wraps" in page[page.index("data-holds-flight"):]


def test_a_pause_lets_what_was_merged_finish_and_says_when_askdnd_last_updated(admin, db):
    """Issue 110 (Brett, Nov 23: "a pause is not a nuclear option. I would want inflight work to finish, not stop"):
    paused, the bar says what was merged before still goes live and when askdnd.ai started running, so he sees it settle."""
    from app import config

    rules.set_freeze(db, "user:1", True, why="Game night")
    db.flush()
    page = admin.get("/manage/for-you").text
    bar = page[page.index('data-stat="paused"'):]
    assert "data-paused-drain" in bar and f'datetime="{config.STARTED_AT.isoformat()}"' in bar[:bar.index("</div>")]
    rules.set_freeze(db, "user:1", False)
    db.flush()
    assert "data-paused-drain" not in admin.get("/manage/for-you").text


def test_one_item_opens_in_its_window_with_the_next_and_the_old_link_opens_it_there(admin, dm, db):
    """Issue 44 and The Work Pages (Brett, Nov 20): any single item opens in one window, from any page, ↑ ↓ walking the
    list it came from; an old link to one item (?open=) opens it in that window over its page. Admins only."""
    first = rules.new_issue(db, "claude", "Check buttons: Passed looks already chosen")
    a, b = _check(db, issue=first, why=""), _check(db, issue=first, why="")
    rules.start_fixing(db, "claude", first)
    rules.fix_live(db, "askdnd", first, "abc")
    db.flush()
    keys = [k for k in testing_page.listed_keys(db, "foryou", "laptop") if k in (f"c{a.id}", f"c{b.id}")]
    assert len(keys) == 2
    win = admin.get(f"/manage/item/{keys[0]}?from=foryou").text
    assert f'data-item-panel="{keys[0]}"' in win and f'data-fft-check="{keys[0][1:]}"' in win
    assert f'/manage/item/{keys[1]}?from=foryou" data-item-next' in win and "data-item-prev" not in win
    assert f'data-next-url="/manage/item/{keys[1]}?from=foryou"' in win  # (after a press it moves on to this one)
    last = admin.get(f"/manage/item/{keys[1]}?from=foryou").text
    assert "data-item-prev" in last and "data-next-url" not in last
    assert f'data-fft-issue="{first.id}"' in admin.get(f"/manage/item/i{first.id}").text
    assert admin.get("/manage/item/i999999").status_code == 404
    assert dm.get(f"/manage/item/i{first.id}").status_code in (303, 403, 404)  # (admins only, as the pages it opens from)
    page = admin.get(f"/manage/feedback?tab=ready&open=i{first.id}").text  # (an old link: its page, the item over it)
    assert f'data-open-item="/manage/item/i{first.id}?from=feedback%3Aready%3A%3A%3A%3A"' in page
    assert f'data-panel-url="/manage/item/{keys[0]}?from=foryou"' in admin.get("/manage/for-you").text


def test_a_check_reads_goal_first_and_a_round_keeps_to_one_need(admin, db):
    """Clearer checks (Roadmap item 6, Brett's picks Nov 21): a check's goal (before, now) sits above its steps in its
    window and a tap away on the round's card; For you's Try is a group per need, and a round keeps to one: a check that
    needs more than one person is never in a laptop round."""
    a = _area(db)
    solo = _check(db, title="Alone", path="/party", area=a, before="It wrapped.", now="It fits on one line.")
    duo = _check(db, title="Two of us", path="/party", area=a, before="Only one saw it.", now="Both see it.", people=True)
    window = admin.get(f"/manage/item/c{solo.id}?from=foryou").text
    assert "data-goal" in window and "It fits on one line." in window and window.index("data-goal") < window.index('class="walk"')
    page = admin.get("/manage/for-you").text
    assert 'data-need="laptop"' in page and 'data-need="people"' in page and "Now: It fits on one line." in page
    admin.post("/manage/testing/round", data={"need": "laptop"})
    card = admin.get("/manage/testing/card?at=/party").text
    assert f'data-check-card="{solo.id}"' in card and '<details class="cc-goal" data-goal>' in card
    admin.post(f"/manage/testing/checks/{solo.id}/try", data={"result": "passed", "seen": "to_try"})
    assert f'data-check-card="{duo.id}"' not in admin.get("/manage/testing/card?at=/party").text  # (the laptop round is done: never the two-person check)
    admin.post("/manage/testing/round/end")
    admin.post("/manage/testing/round", data={"need": "people"})
    assert f'data-check-card="{duo.id}"' in admin.get("/manage/testing/card?at=/party").text


def test_comments_on_a_mockup_wait_for_an_open_question_and_go_with_the_picks(admin, db):
    """Issue 24 (Brett's picks, Nov 21): a comment pinned to a mockup needs its open question (it goes with the picks),
    is his alone to take back while held, and Save my picks sends it with his answer; the layer is on every mockup."""
    from app.fft.models import FftDocComment

    doc = "docs/mockups/fft-round-2/index.html"
    pin = {"doc": doc, "x": 0.4, "y": 120, "near": "Split into 3", "words": "Say the count first."}
    assert admin.post("/manage/testing/comments", json=pin).status_code == 409  # (no open question: nothing to go with)
    q = rules.ask(db, "claude", about="document", about_id=None, text="Which?", doc_path=doc)
    db.flush()
    assert admin.post("/manage/testing/comments", json=pin | {"words": " "}).status_code == 400
    rail = admin.post("/manage/testing/comments", json=pin).text
    assert 'data-open="yes"' in rail and "Say the count first." in rail and "data-comment-drop" in rail
    c = db.scalar(select(FftDocComment))
    assert (c.n, c.near, c.sent_at) == (1, "Split into 3", None)
    other = FftDocComment(doc=doc, n=2, x=0.1, y=10, words="Someone else's", user_id=None)
    db.add(other)
    db.flush()
    assert admin.post(f"/manage/testing/comments/{other.id}/drop").status_code == 404  # (only your own, while held)
    r = admin.post("/manage/testing/picks", json={"doc": doc, "picks": [{"name": "queue", "value": "quiet", "label": "1 A"}], "notes": ""})
    assert r.status_code == 200 and r.json()["comments"] == 1
    db.refresh(q)
    db.refresh(c)
    assert "Comments on the mockup:" in q.answer_text and "Pin 1 (near “Split into 3”): Say the count first." in q.answer_text
    assert c.sent_at is not None and c.question_id == q.id
    assert admin.post(f"/manage/testing/comments/{c.id}/drop").status_code == 404  # (sent: it's in the answer now)
    from app.documents import doc_id

    frame = admin.get(f"/manage/documents/{doc_id(doc)}").text
    url = frame.split('class="doc-frame" src="')[1].split('"')[0]
    assert "doc-layer.js" in admin.get(url).text  # (the layer on every mockup, older ones too)


def test_send_now_sends_your_comments_before_your_picks(admin, db):
    """Issue 116 (Brett, Nov 25: "I do not want to Save my picks when my comments could change my decision"): Send now
    sends his held comments to Claude at once, says so in Claude's inbox, and leaves the question open for his picks; a
    comment made after waits again, and goes with the picks."""
    from app.fft import views
    from app.fft.models import FftDocComment, FftEvent

    doc = "docs/mockups/fft-round-2/index.html"
    pin = {"doc": doc, "x": 0.4, "y": 120, "near": "Split into 3", "words": "Would a fourth pick change it?"}
    assert admin.post("/manage/testing/comments/send", json={"doc": doc}).status_code == 409  # (no open question)
    q = rules.ask(db, "claude", about="document", about_id=None, text="Which?", doc_path=doc)
    db.flush()
    rail = admin.post("/manage/testing/comments", json=pin).text
    assert 'data-held="1"' in rail
    rail = admin.post("/manage/testing/comments/send", json={"doc": doc}).text
    assert 'data-held="0"' in rail and "Sent to Claude" in rail
    c = db.scalar(select(FftDocComment))
    db.refresh(c)
    db.refresh(q)
    assert c.sent_at is not None and c.question_id == q.id and q.answered_at is None  # (sent; the question still open)
    ev = db.scalar(select(FftEvent).where(FftEvent.kind == "doc_comments_sent"))
    assert ev.thing_id == q.id and views.event_words(ev).startswith("Brett sent 1 comment on question") and "fourth pick" not in views.event_words(ev)
    admin.post("/manage/testing/comments", json=pin | {"words": "And one more."})
    r = admin.post("/manage/testing/picks", json={"doc": doc, "picks": [{"name": "queue", "value": "quiet", "label": "1 A"}], "notes": ""})
    assert r.json()["comments"] == 1  # (only the one made after Send now went with the picks)
    db.refresh(q)
    assert "And one more." in q.answer_text and "fourth pick" not in q.answer_text
