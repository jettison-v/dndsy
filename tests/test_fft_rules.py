"""Found, Fixed, Tried's rules (app/fft/rules.py; the v2 brief's R1–R18 and T1–T8,
docs/mockups/feedback-and-testing/index.html): every state change goes through them, so these walk each rule through
its cases, then a randomized run checks the invariants and a replay checks the record of events matches the rows."""

import random
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.fft import lanes, rules
from app.fft.models import FftArea, FftCheck, FftEvent, FftIssue, FftItem, FftNote, FftRound, FftTry
from app.fft.rules import Found, RuleError
from tests.table_setup import plain_id


def _player_note(db, text="The coins don't add up.", kind="problem", uid=None):
    return rules.send_note(db, user_id=uid, first_name="Cole Player", role="player", kind=kind, text=text,
                           context={"page": "Cole · Battle", "signed_in_as": "Cole (player)", "viewing_as_email": "x@example.com",
                                    "who": "someone@example.com"})


def _issue_with_check(db, title="Short Rest restores slots", area=None, devices=None):
    issue = rules.new_issue(db, "claude", title, area_id=area.id if area else None)
    check = rules.write_check(db, "claude", title="Short Rests keep slots", steps=["Press [Short Rest]."], expect="Slots stay spent.",
                              area_id=area.id if area else None, issue_ids=[issue.id], devices=devices)
    rules.preflight(db, "claude", check, True)  # (R18: Claude's own try passed, so it can reach Brett)
    return issue, check


def _live(db, issue, commit="abc123"):
    rules.start_fixing(db, "claude", issue)
    rules.fix_live(db, "askdnd", issue, commit)


def _area(db, title="Manage", item=None, place=0):
    item = item or FftItem(title="Fixes and polish", standing=True, section="now")
    if item.id is None:
        db.add(item)
        db.flush()
    a = FftArea(item_id=item.id, title=title, place=place)
    db.add(a)
    db.flush()
    return a


# ------------------------------------------------------------------ notes


def test_r1_a_players_note_waits_and_an_admins_is_filed_with_no_email_kept(db):
    """A standing rule (Brett, Nov 6; T1, T2): a player's note waits for an admin; nothing about it keeps an email."""
    n = _player_note(db)
    assert n.state == "waiting" and n.issue_id is None and n.first_name == "Cole"
    assert "signed_in_as" not in n.context and "viewing_as_email" not in n.context and "who" not in n.context and n.context["page"]
    mine = rules.send_note(db, user_id=None, first_name="Brett", role="admin", kind="problem", text="Rest wraps.")
    assert mine.state == "filed" and mine.filed_as == "issue" and db.get(FftIssue, mine.issue_id).state == "to_fix"
    idea = rules.send_note(db, user_id=None, first_name="Brett", role="admin", kind="idea", text="A dice tray.")
    assert idea.filed_as == "idea" and idea.idea_id
    relayed = rules.send_note(db, user_id=None, first_name="Brett", role="admin", kind="problem", text="From staging.", staging=True)
    assert relayed.state == "waiting"  # (T6: the relay can't prove who sent it)
    with pytest.raises(RuleError):
        rules.send_note(db, user_id=None, first_name="x", role="player", kind="", text="No kind picked")


def test_r2_same_as_joins_and_unjoin_undoes_it(db):
    a = _player_note(db, "Slots back after a rest.")
    issue = rules.file_issue(db, "user:1", a)
    b = _player_note(db, "Same here after resting.")
    joined = rules.join_issue(db, "user:1", b, issue)
    assert joined.id == issue.id and b.issue_id == issue.id and issue.from_player
    with pytest.raises(RuleError):
        rules.join_issue(db, "user:1", b, issue)  # (already decided)
    own = rules.unjoin(db, "user:1", b)
    assert b.issue_id == own.id != issue.id


def test_undo_within_a_minute_removes_what_the_approval_made(db):
    n = _player_note(db)
    issue = rules.file_issue(db, "user:1", n)
    db.flush()
    rules.undo_decision(db, "user:1", n)
    db.flush()
    assert n.state == "waiting" and db.get(FftIssue, issue.id) is None
    rules.decline(db, "user:1", n, "Works as designed.")
    db.execute(update(FftEvent).where(FftEvent.thing == "note", FftEvent.thing_id == n.id).values(at=rules.now() - timedelta(minutes=5)))
    with pytest.raises(RuleError):
        rules.undo_decision(db, "user:1", n)


def test_a_players_added_words_wait_for_approval(db):
    """T1: a player's own line isn't approved until an admin approves it."""
    n = _player_note(db)
    line = rules.add_line(db, "user:9", "Also on my phone.", note=n, who="sender", approved=False)
    assert not line.approved
    rules.file_issue(db, "user:1", n)
    db.flush()
    db.refresh(line)
    assert line.approved


# ------------------------------------------------------------------ fixing, trying, passing


def test_r5_an_issue_closes_only_once_every_device_its_checks_need_has_passed(db):
    """Brett's round, Nov 18: passing a check on the laptop closed issues whose checks still waited for the iPhone. An
    issue closes as working only once every device each of its checks needs has passed; one closed early goes back to
    ready to try."""
    issue, check = _issue_with_check(db, devices=["laptop", "iphone"])
    _live(db, issue)
    rules.record_try(db, "user:1", check, result="passed", device="laptop", user_id=None)
    assert issue.state == "ready"  # (the iPhone still to try)
    rules.record_try(db, "user:1", check, result="passed", device="iphone", user_id=None)
    assert issue.state == "closed" and issue.close_reason == "works"
    with pytest.raises(rules.RuleError):
        rules.back_to_ready(db, "claude", issue)  # (closed rightly: nothing left to try)
    early, both = _issue_with_check(db, title="Closed too soon", devices=["laptop", "iphone"])
    _live(db, early)
    early.state, early.close_reason = "closed", "works"  # (as the old rule left it)
    db.flush()
    rules.back_to_ready(db, "claude", early)
    assert early.state == "ready" and early.close_reason == ""


def test_a_check_retired_by_mistake_comes_back_as_it_was(db):
    issue, check = _issue_with_check(db)
    rules.retire(db, "claude", check, "no longer needed")
    with pytest.raises(rules.RuleError):
        rules.restore(db, "claude", check, "")  # (say why)
    rules.restore(db, "claude", check, "retired by mistake")
    assert not check.retired and check.version == 1
    with pytest.raises(rules.RuleError):
        rules.restore(db, "claude", check, "again")


def test_r4_r5_a_fix_goes_live_the_check_comes_back_and_a_pass_closes_it(db):
    issue, check = _issue_with_check(db)
    assert rules.check_state(db, check)["state"] == "fixing"  # (its fix isn't live: Claude's)
    _live(db, issue)
    st = rules.check_state(db, check)
    assert issue.state == "ready" and st["state"] == "to_try" and st["turn"] == "brett"
    rules.record_try(db, "user:1", check, result="passed", user_id=None)
    assert issue.state == "closed" and issue.close_reason == "works" and rules.check_state(db, check)["state"] == "passed"


def test_r5_a_players_fix_waits_for_them_then_is_brett_after_three_days(db, admin):
    from app.models import User

    player = db.scalar(select(User).where(User.email == "player@example.com"))
    if player is None:
        player = User(email="player@example.com", name="Big C")
        db.add(player)
        db.flush()
    n = _player_note(db, uid=player.id)
    issue = rules.file_issue(db, "user:1", n)
    check = rules.write_check(db, "claude", title="t", steps=["s"], expect="e", issue_ids=[issue.id])
    _live(db, issue)
    assert issue.confirm_by == player.id
    rules.record_try(db, "user:1", check, result="passed", user_id=None)
    assert issue.state == "ready"  # (the player's to confirm first)
    issue.confirm_since = rules.now() - timedelta(days=4)
    assert rules.confirm_due(db) == [issue.id] and issue.confirm_by is None
    rules.player_confirms(db, "user:2", issue, True, user_id=None)
    assert issue.state == "closed"


def test_r3_r5_a_non_blocking_issue_survives_the_pass_and_doesnt_hold_the_check(db):
    issue, check = _issue_with_check(db)
    _live(db, issue)
    t = rules.record_try(db, "user:1", check, result="failed", found=[Found(title="Name cut off", blocking=False)])
    side = db.scalar(select(FftIssue).where(FftIssue.origin_try_id == t.id))
    assert side.state == "to_fix" and rules.check_state(db, check)["state"] == "to_try"  # (only the side issue was found)
    rules.record_try(db, "user:1", check, result="passed")
    assert issue.state == "closed" and side.state == "to_fix"  # (a pass never closes a non-blocking issue)


def test_r3_still_happening_sends_it_back_and_a_closed_one_comes_back(db):
    issue, check = _issue_with_check(db)
    _live(db, issue)
    rules.record_try(db, "user:1", check, result="failed", found=[Found(issue_id=issue.id)])
    st = rules.check_state(db, check)
    assert issue.state == "to_fix" and st["state"] == "failed" and st["turn"] == "claude"
    rules.start_fixing(db, "claude", issue)
    rules.fix_live(db, "askdnd", issue, "def456")
    assert rules.check_state(db, check) == {"state": "to_try", "turn": "brett", "devices": {"laptop": "to_try"}, "again": True}
    rules.record_try(db, "user:1", check, result="passed")
    assert issue.state == "closed"
    rules.record_try(db, "user:1", check, result="failed", found=[Found(issue_id=issue.id)])
    assert issue.state == "to_fix" and issue.reopened == 1  # (it came back)


def test_r5_an_issue_still_failing_on_another_check_stays_open(db):
    issue, check = _issue_with_check(db)
    other = rules.write_check(db, "claude", title="Other", steps=["s"], expect="e", issue_ids=[issue.id])
    _live(db, issue)
    rules.record_try(db, "user:1", other, result="failed", found=[Found(issue_id=issue.id)])
    rules.start_fixing(db, "claude", issue)
    rules.fix_live(db, "askdnd", issue, "f1")
    rules.record_try(db, "user:1", other, result="failed", found=[Found(title="Something else there")])
    issue.state = "ready"  # (its own fix is live; the other check still fails on a device)
    assert rules.check_state(db, other)["devices"]["laptop"] == "failed"


def test_devices_a_check_required_on_two_devices_passes_only_when_both_do(db):
    issue, check = _issue_with_check(db, devices=["laptop", "iphone"])
    _live(db, issue)
    rules.record_try(db, "user:1", check, result="passed", device="iphone")
    assert rules.check_state(db, check)["state"] == "to_try"  # (the laptop hasn't passed)
    rules.record_try(db, "user:1", check, result="passed", device="laptop")
    assert rules.check_state(db, check)["state"] == "passed"


def test_r10_r16_the_mac_minis_pass_confirms_nothing(db):
    issue, check = _issue_with_check(db, devices=["laptop"])
    _live(db, issue)
    rules.record_try(db, "mini", check, result="passed", device="mac_mini")
    assert issue.state == "ready" and rules.check_state(db, check)["state"] == "to_try"


def test_r6_a_correction_keeps_both_withdraws_what_only_it_made_and_unmarks_the_rest(db):
    issue, check = _issue_with_check(db)
    _live(db, issue)
    t = rules.record_try(db, "user:1", check, result="failed", found=[Found(issue_id=issue.id), Found(title="New thing")])
    made = db.scalar(select(FftIssue).where(FftIssue.origin_try_id == t.id))
    assert issue.state == "to_fix" and made.state == "to_fix"
    new = rules.correct_try(db, "user:1", t, "untried", "Pressed the wrong one")
    assert t.replaced and new.replaces_id == t.id
    assert made.state == "closed" and made.close_reason == "withdrawn"
    assert issue.state == "ready" and rules.check_state(db, check)["state"] == "to_try"
    with pytest.raises(RuleError):
        rules.correct_try(db, "user:1", t, "passed", "again")  # (already corrected)


def test_r7_cant_try_later_blocked_and_wrong(db):
    issue, check = _issue_with_check(db)
    _live(db, issue)
    blocker = rules.new_issue(db, "claude", "The page won't open")
    rules.record_try(db, "user:1", check, result="cant", cant_kind="blocked", blocked_by=blocker.id)
    assert rules.check_state(db, check)["state"] == "blocked"
    rules.start_fixing(db, "claude", blocker)
    rules.fix_live(db, "askdnd", blocker, "b1")
    assert rules.check_state(db, check)["state"] == "to_try"  # (back when it's fixed)
    rules.record_try(db, "user:1", check, result="cant", cant_kind="wrong", why="No player's note was open")
    assert rules.check_state(db, check)["turn"] == "claude"
    rules.new_version(db, "claude", check, steps=["Open note 2."], expect="e", why="Open a player's note straight away")
    assert check.version == 2 and rules.check_state(db, check)["state"] == "preflight"  # (R18: each version, Claude's try first)
    rules.preflight(db, "claude", check, True)
    assert rules.check_state(db, check)["state"] == "to_try"
    rules.record_try(db, "user:1", check, result="cant", cant_kind="later")
    assert rules.check_state(db, check) | {} == {"state": "later", "turn": "brett", "devices": {"laptop": "later"}, "again": False}
    with pytest.raises(RuleError):
        rules.record_try(db, "user:1", check, result="cant", cant_kind="blocked")  # (blocked by which issue?)


def test_r18_a_check_that_fails_its_own_try_never_reaches_brett(db):
    issue, check = _issue_with_check(db)
    _live(db, issue)
    rules.preflight(db, "claude", check, False, "Its page didn't open")
    assert rules.check_state(db, check)["turn"] == "claude"
    rules.preflight(db, "claude", check, True)
    assert rules.check_state(db, check)["turn"] == "brett"


# ------------------------------------------------------------------ merging, rounds, the order


def test_approving_a_players_note_is_the_ok_for_its_fix(db):
    """Brett's pick 5 (Nov 19, Work Flow, Sized to Grow; R17 retired): approving a player's note is the OK for its fix,
    so its pull request waits for no second OK; its plan's lane decides the testing."""
    n = _player_note(db)
    issue = rules.file_issue(db, "user:1", n)
    rules.start_fixing(db, "claude", issue)
    rules.fix_ready(db, "claude", issue, "https://github.com/x/y/pull/1")
    assert issue.state == "fixing" and issue.pr and rules.may_merge(db, issue)[0]
    held = rules.new_issue(db, "claude", "Held from before")
    held.state = "merge_ok"  # (one held before R17 went still needs its OK)
    assert not rules.may_merge(db, held)[0]
    rules.ok_merge(db, "user:1", held)
    assert held.state == "fixing"


def test_a_plans_lane_goes_up_by_anyone_and_down_only_on_bretts_word(db):
    """The work flow's slice 3 (Brett's picks, Nov 19): Ship, Look or Careful; Claude moves a plan up, saying why,
    never down; Brett may move it either way; each change is kept with who and why."""
    a = _area(db, "Battle")
    rules.set_lane(db, "claude", a, "look", "People see it")
    rules.set_lane(db, "claude", a, "careful", "It touches sign-in")
    with pytest.raises(rules.RuleError):
        rules.set_lane(db, "claude", a, "ship")
    rules.set_lane(db, "user:1", a, "look", "Brett chose it", admin=True)
    assert rules.lane_of(a) == "look" and a.lane_by == "user:1"
    moves = [e.data for e in db.scalars(select(FftEvent).where(FftEvent.kind == "area_lane", FftEvent.thing_id == a.id).order_by(FftEvent.id))]
    assert [(m["from"], m["to"]) for m in moves] == [("", "look"), ("look", "careful"), ("careful", "look")]
    with pytest.raises(rules.RuleError):
        rules.set_lane(db, "claude", a, "fast")


def test_an_incident_keeps_only_its_area_careful_for_30_days(db):
    a, b = _area(db, "Battle"), _area(db, "Sheet")
    rules.set_lane(db, "claude", a, "look")
    rules.incident(db, "claude", a, "Hit points vanished mid-fight")
    assert rules.lane_of(a) == "careful" and rules.lane_of(b) == ""
    with pytest.raises(rules.RuleError):
        rules.set_lane(db, "user:1", a, "look", admin=True)  # (not even Brett, until the days are up)
    a.careful_until = rules.now() - timedelta(minutes=1)
    rules.set_lane(db, "user:1", a, "look", admin=True)
    assert rules.lane_of(a) == "look"


def test_the_game_night_freeze_holds_every_merge_until_its_turned_off(db):
    """Brett, Nov 19: a switch, on before a game and off after; while it's on nothing merges."""
    issue, _ = _issue_with_check(db)
    rules.start_fixing(db, "claude", issue)
    assert rules.may_merge(db, issue)[0] and not rules.frozen(db)
    rules.set_freeze(db, "user:1", True, by="Brett")
    assert rules.frozen(db) and not rules.may_merge(db, issue)[0] and rules.freeze_state(db)["by"] == "Brett"
    rules.set_freeze(db, "user:1", False)
    assert not rules.frozen(db) and rules.may_merge(db, issue)[0]
    assert [e.kind for e in db.scalars(select(FftEvent).where(FftEvent.kind.like("freeze_%")).order_by(FftEvent.id))] == ["freeze_on", "freeze_off"]


@pytest.mark.parametrize(("files", "lane"), [
    (["tests/test_x.py", "docs/MAP.md"], "ship"),
    (["app/fft/rules.py"], "ship"),
    (["app/templates/party.html", "app/fft/rules.py"], "look"),
    (["app/static/app.css"], "look"),
    (["app/access.py", "app/templates/party.html"], "careful"),
    (["extension/askdnd-bridge/vtt-page.js"], "careful"),
], ids=plain_id)
def test_the_lane_is_picked_from_the_files_a_change_touches(files, lane):
    assert lanes.pick(files)[0] == lane


def test_a_database_change_that_alters_data_is_careful_and_one_that_only_adds_isnt():
    adds = "def upgrade():\n    op.add_column('x', sa.Column('y', sa.String()))\ndef downgrade():\n    op.drop_column('x', 'y')\n"
    alters = "def upgrade():\n    op.execute(\"UPDATE x SET y = 1\")\n"
    f = "migrations/versions/2026_12_09-abc_x.py"
    assert lanes.pick([f], read=lambda _: adds)[0] == "ship"  # (its downgrade's drop doesn't count)
    assert lanes.pick([f], read=lambda _: alters)[0] == "careful"


def test_r11_nothing_merges_while_a_round_is_open_except_what_stops_it(db):
    issue, check = _issue_with_check(db)
    rules.start_fixing(db, "claude", issue)
    r = rules.open_round(db, "user:1", None)
    assert not rules.may_merge(db, issue)[0]
    other, other_check = _issue_with_check(db, "Second")
    _live(db, other)
    rules.record_try(db, "user:1", other_check, result="failed", found=[Found(title="Can't continue", stops_round=True)], round_id=r.id)
    stopper = db.scalar(select(FftIssue).where(FftIssue.title == "Can't continue"))
    assert rules.may_merge(db, stopper)[0] and not rules.may_merge(db, issue)[0]
    r.last_at = rules.now() - timedelta(hours=13)
    assert rules.round_open(db) is None and r.ended_at is not None  # (idle 12 hours: ended itself)


def test_r11_one_area_is_claudes_at_a_time(db):
    a, b = _area(db, "Manage"), _area(db, "Menu bar")
    rules.lock_area(db, "claude:main", a)
    with pytest.raises(RuleError):
        rules.lock_area(db, "claude:area", b)
    a.lock_until = rules.now() - timedelta(minutes=1)  # (lapsed)
    rules.lock_area(db, "claude:area", b)


def test_r15_claude_takes_a_blocker_first_then_the_roadmap_from_the_top(db):
    fixes = FftItem(title="Fixes and polish", standing=True, section="now", place=1)
    feature = FftItem(title="Feedback and Testing", section="now", place=2, next_whose="brett", next_step="your verdict")
    later = FftItem(title="Homebrew", section="next", place=3)
    db.add_all([fixes, feature, later])
    db.flush()
    manage, menu = _area(db, "Manage", fixes, 1), _area(db, "Menu bar", fixes, 2)
    fft_area, builder = _area(db, "Found, Fixed, Tried", feature), _area(db, "Item Builder", later)
    for a in (manage, menu, fft_area, builder):
        rules.new_issue(db, "claude", f"An issue in {a.title}", area_id=a.id)
    pick = rules.pick_next(db)
    assert pick.area.id == manage.id and ("Feedback and Testing", "its next step is Brett's (your verdict)") not in pick.skipped
    fixes.place, later.place, later.section = 9, 0, "now"  # (the Roadmap's order is its sections, then Brett's drag in each)
    pick = rules.pick_next(db)
    assert pick.area.id == builder.id
    for i in rules.area_open_issues(db, builder):
        rules.close(db, "claude", i, "wont")
    pick = rules.pick_next(db)
    assert pick.area.id == manage.id and ("Feedback and Testing", "its next step is Brett's (your verdict)") in pick.skipped
    # a blocker in an open round goes first
    issue, check = _issue_with_check(db, "Under test", area=menu)
    _live(db, issue)
    r = rules.open_round(db, "user:1", None, menu.id)
    rules.record_try(db, "user:1", check, result="failed", found=[Found(title="Can't go on", stops_round=True)], round_id=r.id)
    pick = rules.pick_next(db)
    assert pick.blocker and pick.area.id == menu.id


def test_r12_an_area_is_done_when_its_issues_close_and_its_checks_pass(db):
    a = _area(db)
    issue, check = _issue_with_check(db, area=a)
    assert not rules.area_done(db, a) and rules.area_turn(db, a) == "claude"
    _live(db, issue)
    assert rules.area_turn(db, a) == "brett"
    rules.record_try(db, "user:1", check, result="passed")
    assert rules.area_done(db, a) and rules.area_turn(db, a) == "done"


def test_r13_a_question_waits_for_brett_and_the_answer_names_it(db):
    issue = rules.new_issue(db, "claude", "Which reason words?")
    q = rules.ask(db, "claude", about="issue", about_id=issue.id, text="Words or a pill?",
                  choices=[{"label": "Words"}, {"label": "A pill"}], mine=0)
    assert issue.state == "asks" and rules.ISSUE_TURN["asks"] == "brett"
    with pytest.raises(RuleError):
        rules.answer(db, "user:1", q, choice=5)
    rules.answer(db, "user:1", q, choice=1, text="Pills read faster")
    assert issue.state == "to_fix" and q.answer_choice == 1
    with pytest.raises(RuleError):
        rules.answer(db, "user:1", q, choice=0)  # (answered: a second answer can't take it)


def test_a_superseded_question_is_withdrawn_with_why_and_its_issue_moves_on(db):
    """A standing rule (Brett, Nov 19: "if Test or Try is superseded, it should be removed or canceled"): a question a
    later pick replaced leaves For you, says why, and its issue goes back to Claude as an answer would."""
    issue = rules.new_issue(db, "claude", "Where you are")
    q = rules.ask(db, "claude", about="issue", about_id=issue.id, text="Which way?", choices=[{"label": "A"}, {"label": "B"}])
    with pytest.raises(RuleError):
        rules.withdraw(db, "claude", q, "  ")  # (it says why)
    rules.withdraw(db, "claude", q, "Answered on Menu Bar Doors")
    assert q.answered_at is not None and q.answer_text == "Withdrawn: Answered on Menu Bar Doors" and q.answered_by is None
    assert issue.state == "to_fix"
    with pytest.raises(RuleError):
        rules.answer(db, "user:1", q, choice=0)  # (gone from For you: it can't be answered after)


def test_r14_a_stale_page_is_refused_with_what_changed(db):
    issue = rules.new_issue(db, "claude", "x")
    rules.start_fixing(db, "claude", issue)
    with pytest.raises(RuleError) as e:
        rules.close(db, "user:1", issue, "wont", seen="to_fix")
    assert e.value.code == "stale" and "fixing" in e.value.words


def test_r9_a_rolled_back_fix_is_claudes_again(db):
    issue, check = _issue_with_check(db)
    _live(db, issue, "bad1")
    assert rules.rollback(db, "askdnd", "bad1") == [issue.id]
    assert issue.state == "fixing" and rules.check_state(db, check)["state"] == "fixing"


def test_closing_needs_a_reason_and_same_as_moves_its_notes(db):
    a, b = rules.new_issue(db, "claude", "a"), rules.new_issue(db, "claude", "b")
    n = _player_note(db)
    rules.join_issue(db, "user:1", n, a)
    with pytest.raises(RuleError):
        rules.close(db, "user:1", a, "")
    rules.close(db, "user:1", a, "same", same_as=b)
    assert n.issue_id == b.id and a.same_as_id == b.id
    rules.reopen(db, "user:1", a)
    assert a.state == "to_fix" and a.reopened == 1 and not a.close_reason


# ------------------------------------------------------------------ listeners (T8)


def test_t8_each_listener_reads_its_own_and_nothing_fresh_is_skipped(db):
    a = _area(db)
    rules.new_issue(db, "claude", "In the area", area_id=a.id)
    rules.new_issue(db, "claude", "Elsewhere")
    main, own = rules.listener(db, "main"), rules.listener(db, "area-chat", area_id=a.id)
    assert rules.unread(db, main) == []  # (too fresh: read once it's settled)
    db.execute(update(FftEvent).values(at=rules.now() - timedelta(seconds=30)))
    assert len(rules.unread(db, main)) == 2
    assert [e.area_id for e in rules.unread(db, own)] == [a.id]  # (the main chat's read took nothing from it)
    assert rules.unread(db, main) == []


# ------------------------------------------------------------------ invariants and the record


def test_invariants_hold_through_random_sequences(db):
    """Whatever happens, in any order: no check is left failed with no open issue holding it; a closed issue is never
    to try; every issue's state is one the record of events reached last."""
    rng = random.Random(17)
    issues, checks = [], []
    for k in range(3):
        i, c = _issue_with_check(db, f"Issue {k}")
        issues.append(i)
        checks.append(c)
    for _ in range(160):
        issue, check = rng.choice(issues), rng.choice(checks)
        op = rng.choice(["fix", "live", "pass", "fail_still", "fail_new", "correct", "close", "reopen", "cant", "version"])
        try:
            if op == "fix":
                rules.start_fixing(db, "claude", issue)
            elif op == "live":
                rules.fix_live(db, "askdnd", issue, f"c{rng.randint(1, 99)}")
            elif op == "pass":
                rules.record_try(db, "user:1", check, result="passed")
            elif op == "fail_still":
                rules.record_try(db, "user:1", check, result="failed", found=[Found(issue_id=issue.id, blocking=rng.random() < .7)])
            elif op == "fail_new":
                rules.record_try(db, "user:1", check, result="failed", found=[Found(title="New", blocking=rng.random() < .7)])
            elif op == "correct":
                last = db.scalar(select(FftTry).where(FftTry.check_id == check.id, FftTry.replaced.is_(False), FftTry.result != "untried").order_by(FftTry.id.desc()))
                if last is not None:
                    rules.correct_try(db, "user:1", last, rng.choice(["passed", "untried", "cant"]), "oops")
            elif op == "close":
                rules.close(db, "user:1", issue, rng.choice(["works", "wont", "cant_repro"]))
            elif op == "reopen":
                rules.reopen(db, "user:1", issue)
            elif op == "cant":
                rules.record_try(db, "user:1", check, result="cant", cant_kind="later")
            elif op == "version":
                rules.new_version(db, "claude", check, steps=["s2"], expect="e", why="rewritten")
                rules.preflight(db, "claude", check, True)
        except RuleError:
            pass
        db.flush()
        for c in checks:
            st = rules.check_state(db, c)
            if st["state"] == "failed":
                holding = [i for i in rules._blocking_issues(db, c) if i.state not in ("ready", "closed")]
                assert holding, f"check {c.id} failed with nothing open holding it"
        issues = list(db.scalars(select(FftIssue)))
    for issue in issues:
        last = db.scalar(select(FftEvent.data).where(FftEvent.thing == "issue", FftEvent.thing_id == issue.id,
                                                     FftEvent.data.has_key("to")).order_by(FftEvent.id.desc()))
        assert (last or {}).get("to", "to_fix") == issue.state, f"issue {issue.id}: the record says {last}, the row {issue.state}"


def test_every_state_change_writes_its_event(db):
    n = _player_note(db)
    issue = rules.file_issue(db, "user:1", n)
    rules.start_fixing(db, "claude", issue)
    kinds = list(db.scalars(select(FftEvent.kind).order_by(FftEvent.id)))
    assert kinds == ["note_sent", "issue_new", "note_filed", "issue_fixing"]
    assert db.scalar(select(FftNote).where(FftNote.id == n.id)).state == "filed"
    assert db.scalar(select(FftRound)) is None and db.scalar(select(FftCheck)) is None


# ------------------------------------------------------------------ the review of PR #417 (Nov 18)


def test_correcting_a_try_puts_back_only_what_that_try_changed(db):
    """A try named an issue that was already to fix (still happening): correcting it to passed must not mark that
    issue fixed, let alone close it as working. One the try did move (ready → to fix) goes back to ready."""
    issue, check = _issue_with_check(db)
    rules.start_fixing(db, "claude", issue)
    issue.state = "to_fix"  # (never fixed: as a carried-over failed check, or the Mac Mini's, names it)
    db.flush()
    t = rules.record_try(db, "user:1", check, result="failed", found=[Found(issue_id=issue.id)])
    assert issue.state == "to_fix"
    rules.correct_try(db, "user:1", t, "passed", "I misread it")
    assert issue.state == "to_fix" and issue.close_reason != "works"  # (it was to fix before the try: it stays)

    live, check2 = _issue_with_check(db, title="Another")
    _live(db, live)
    t2 = rules.record_try(db, "user:1", check2, result="failed", found=[Found(issue_id=live.id)])
    assert live.state == "to_fix"  # (the try saw it again)
    rules.correct_try(db, "user:1", t2, "untried", "Pressed the wrong one")
    assert live.state == "ready"  # (what this try changed, put back)


def test_undo_after_same_as_keeps_the_issue_that_was_there(db):
    """Undo within a minute of joining a note to an issue that existed before takes the note back out, and leaves the
    issue, its checks and its tries as they were; what the join set (a player's issue) goes back."""
    issue, check = _issue_with_check(db)
    rules.start_fixing(db, "claude", issue)
    issue.pr = "https://github.com/x/y/pull/1"
    db.flush()
    n = _player_note(db)
    rules.join_issue(db, "user:1", n, issue)
    assert issue.from_player and issue.state == "fixing"  # (R17 retired, Nov 19: nothing is held for a second OK)
    rules.undo_decision(db, "user:1", n)
    db.flush()
    assert db.get(FftIssue, issue.id) is not None  # (never deleted)
    assert not issue.from_player and issue.state == "fixing" and n.state == "waiting"


def test_closing_a_players_issue_as_the_same_as_another_makes_that_one_a_players(db):
    """Close as the same: a player's words now share the other issue (its sender hears its outcome); since R17 went
    (Nov 19) its fix waits for no second OK."""
    theirs = rules.new_issue(db, "claude", "Coins are off")
    theirs.from_player = True
    ours, _ = _issue_with_check(db, title="Coins total")
    rules.start_fixing(db, "claude", ours)
    ours.pr = "https://github.com/x/y/pull/2"
    db.flush()
    rules.close(db, "claude", theirs, "same", same_as=ours)
    assert ours.from_player and ours.state == "fixing"


def test_unjoin_makes_a_recorded_issue_in_the_same_feature(db):
    issue = rules.new_issue(db, "claude", "Coins are off", feature="hp")
    a, b = _player_note(db), _player_note(db, text="Rest wraps.")
    rules.join_issue(db, "user:1", a, issue)
    rules.join_issue(db, "user:1", b, issue)
    made = rules.unjoin(db, "user:1", b)
    kinds = set(db.scalars(select(FftEvent.kind).where(FftEvent.thing == "issue", FftEvent.thing_id == made.id)))
    assert "issue_new" in kinds and made.feature == "hp" and made.area_id == issue.area_id


def test_an_areas_own_listener_hears_only_its_area(db):
    li = rules.listener(db, "area-7")
    assert li.area_id is None
    assert rules.listener(db, "area-7", area_id=7).area_id == 7  # (one made before it said its area takes it now)


def test_a_check_that_makes_something_runs_in_a_test_campaign(db):
    """The old tool refused it; the review of PR #417 found the new one didn't, so Brett could be sent to make things in
    the table's own campaign. A check that makes something needs a page in a test campaign, written or rewritten."""
    from app.models import Campaign

    db.add(Campaign(name="Lab", slug="lab", is_test=True))
    db.add(Campaign(name="Main", slug="main-table"))
    db.flush()
    with pytest.raises(RuleError):
        rules.write_check(db, "claude", title="Make an item", steps=["Press [+ New]."], expect="It's there.", path="/c/main-table/dm/items/new", makes=True)
    c = rules.write_check(db, "claude", title="Make an item", steps=["Press [+ New]."], expect="It's there.", path="/c/lab/dm/items/new", makes=True)
    with pytest.raises(RuleError):
        rules.new_version(db, "claude", c, steps=["Press [+ New]."], expect="It's there.", path="/c/main-table/dm/items/new", why="moved")
    assert rules.write_check(db, "claude", title="Look", steps=["Look."], expect="It's there.", path="/c/main-table/party").makes is False


def test_an_issue_asked_about_while_its_fix_is_under_way_goes_back_to_fixing(db):
    """The review of PR #417: answered, it went back to to fix, so its merged fix wasn't marked live."""
    issue, _ = _issue_with_check(db)
    rules.start_fixing(db, "claude", issue)
    q = rules.ask(db, "claude", about="issue", about_id=issue.id, text="Which way?")
    assert issue.state == "asks"
    rules.answer(db, "user:1", q, choice=None, text="This way.")
    assert issue.state == "fixing"


def test_an_add_only_sql_line_doesnt_make_a_plan_careful():
    f = "migrations/versions/2026_12_09-abc_x.py"
    index = "def upgrade():\n    op.execute(\"CREATE INDEX x_y ON x (y)\")\n"
    assert lanes.pick([f], read=lambda _: index)[0] == "ship"
    assert lanes.higher("careful", "look") and not lanes.higher("look", "careful")


# ------------------------------------------------------------------ Available (Brett, Nov 19: local tries while he's around)


def test_available_lets_claude_ask_for_a_local_try_and_turning_it_off_leaves_what_waits(db):
    with pytest.raises(rules.RuleError):  # (not Available: Look work merges, he tries it after)
        rules.new_local_try(db, "claude", "Battle: the Count pill", None, ["The Count is a pill."], "A fight running.", "/party")
    rules.set_available(db, "user:1", True, by="Brett")
    st = rules.available_state(db)
    assert st["on"] and st["actor"] == "user:1" and st["until"]
    lt = rules.new_local_try(db, "claude", "Battle: the Count pill", None, ["The Count is a pill."], "A fight running.", "/party")
    other = rules.new_local_try(db, "claude", "Sheet: rests", None, ["Rests line up."], "", "/party")
    rules.answer_local_try(db, "user:1", lt, "good")
    with pytest.raises(rules.RuleError):
        rules.answer_local_try(db, "user:1", other, "off")  # (say what's off)
    rules.set_available(db, "user:1", False)
    assert lt.answer == "good" and other.answer == "left" and not rules.available_state(db)["on"]
    kinds = [e.kind for e in db.scalars(select(FftEvent).where(FftEvent.thing.in_(("local", "tool"))).order_by(FftEvent.id))]
    assert kinds == ["available_on", "local_new", "local_new", "local_good", "local_left", "available_off"]


def test_available_turns_itself_off_on_any_of_its_signals(db):
    """Brett's picks (Nov 19): quiet in askdnd for 30 minutes, a local try unanswered for 30 minutes, game night, or the
    2 hours (the backstop); the bar says why."""
    real = rules.now
    try:
        rules.set_available(db, "user:1", True)
        assert rules.check_available(db)["on"]
        rules.now = lambda: real() + timedelta(minutes=31)
        assert rules.check_available(db)["why"] == "quiet for 30 minutes"
        rules.now = real
        rules.set_available(db, "user:1", True)
        rules.new_local_try(db, "claude", "Battle", None, ["x"], "", "/party")
        db.flush()
        rules.now = lambda: real() + timedelta(minutes=31)
        assert rules.check_available(db, last_seen=real() + timedelta(minutes=30))["why"] == "a try waited 30 minutes"
        rules.now = real
        rules.set_available(db, "user:1", True)
        rules.now = lambda: real() + timedelta(hours=2, minutes=1)
        assert rules.check_available(db, last_seen=real() + timedelta(hours=2))["why"] == "the 2 hours are up"
        rules.now = real
        rules.set_available(db, "user:1", True)
        rules.set_freeze(db, "user:1", True)
        assert not rules.available_state(db)["on"] and not rules.available_state(db)["why"]  # (his own choice: nothing to explain)
        rules.set_mode(db, "user:1", "available")
        assert rules.mode_of(db) == "available" and not rules.frozen(db)  # (one at a time, Brett, Nov 19)
        rules.set_mode(db, "user:1", "independent")
        assert rules.mode_of(db) == "independent"
        with pytest.raises(rules.RuleError):
            rules.set_mode(db, "user:1", "both")
    finally:
        rules.now = real
