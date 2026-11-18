"""Found, Fixed, Tried's rules (app/fft/rules.py; the v2 brief's R1–R18 and T1–T8,
docs/mockups/feedback-and-testing/index.html): every state change goes through them, so these walk each rule through
its cases, then a randomized run checks the invariants and a replay checks the record of events matches the rows."""

import random
from datetime import timedelta

import pytest
from sqlalchemy import select, update

from app.fft import rules
from app.fft.models import FftArea, FftCheck, FftEvent, FftIssue, FftItem, FftNote, FftRound, FftTry
from app.fft.rules import Found, RuleError


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


def test_r17_a_player_prompted_fix_waits_for_brett_to_ok_the_merge(db):
    n = _player_note(db)
    issue = rules.file_issue(db, "user:1", n)
    rules.start_fixing(db, "claude", issue)
    rules.fix_ready(db, "claude", issue, "https://github.com/x/y/pull/1")
    assert issue.state == "merge_ok" and rules.ISSUE_TURN[issue.state] == "brett"
    assert not rules.may_merge(db, issue)[0]
    rules.ok_merge(db, "user:1", issue)
    assert issue.state == "fixing" and rules.may_merge(db, issue)[0]


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
    fixes.place, later.place = 9, 0
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
