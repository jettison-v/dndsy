"""What the code review of Found, Fixed, Tried found (Nov 17, two independent reviewers), each kept fixed."""

import pytest
from sqlalchemy import select

from app.fft import keys, rules, views
from app.fft.models import FftArea, FftCheckIssue, FftIssue, FftItem, FftNote, FftRound
from app.fft.rules import Found, RuleError
from app.importer import import_bundle
from tests.table_setup import BUNDLE


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


def _check(db, issue=None, devices=None):
    c = rules.write_check(db, "claude", title="Rests keep slots", steps=["Press [Rest]."], expect="Slots stay.",
                          issue_ids=[issue.id] if issue else None, devices=devices)
    rules.preflight(db, "claude", c, True)
    db.flush()
    return c


def _live(db, issue):
    rules.start_fixing(db, "claude", issue)
    rules.fix_live(db, "askdnd", issue, "abc")
    db.flush()


def test_undoing_a_pass_reopens_what_it_closed(db):
    """R5, R6: a pass closed its issue as working; Undo puts it back to ready to try."""
    issue = rules.new_issue(db, "claude", "Rests restore slots")
    c = _check(db, issue)
    _live(db, issue)
    t = rules.record_try(db, "user:1", c, result="passed")
    assert issue.state == "closed"
    rules.correct_try(db, "user:1", t, "untried", "Undone")
    assert issue.state == "ready" and rules.check_state(db, c)["state"] == "to_try"


def test_same_as_keeps_the_check_held(db):
    """R8: a check whose issue closes as the same as another is held by the other, not released."""
    a, b = rules.new_issue(db, "claude", "A"), rules.new_issue(db, "claude", "B")
    c = _check(db)
    rules.record_try(db, "user:1", c, result="failed", found=[Found(issue_id=a.id)])
    rules.close(db, "user:1", a, "same", same_as=b)
    db.flush()
    assert rules.check_state(db, c)["state"] == "failed" and db.get(FftCheckIssue, (c.id, b.id)) is not None


def test_a_corrected_try_lets_go_of_an_issue_it_named_that_others_use(db):
    """R6: an issue the try found, kept for a note on it, no longer holds the check."""
    c = _check(db)
    t = rules.record_try(db, "user:1", c, result="failed", found=[Found(title="X")])
    x = db.scalar(select(FftIssue).where(FftIssue.title == "X"))
    n = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="problem", text="X too")
    rules.join_issue(db, "user:1", n, x)
    rules.correct_try(db, "user:1", t, "passed", "Wrong button")
    db.flush()
    assert x.state != "closed" and rules.check_state(db, c)["state"] == "passed"


def test_a_player_joining_an_issue_whose_fix_is_ready_waits_for_your_ok(db):
    """R17."""
    issue = rules.new_issue(db, "claude", "Mine first")
    rules.start_fixing(db, "claude", issue)
    rules.fix_ready(db, "claude", issue, "https://github.com/x/y/pull/9")
    n = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="problem", text="Me too")
    rules.join_issue(db, "user:1", n, issue)
    assert issue.state == "merge_ok" and not rules.may_merge(db, issue)[0]


def test_an_area_lock_is_its_owners(db):
    item = FftItem(title="Fixes", place=1)
    db.add(item)
    db.flush()
    a = FftArea(item_id=item.id, title="Manage")
    db.add(a)
    db.flush()
    rules.lock_area(db, "claude:main", a)
    with pytest.raises(RuleError):
        rules.lock_area(db, "claude:area-1", a)
    with pytest.raises(RuleError):
        rules.unlock_area(db, "claude:area-1", a)
    rules.unlock_area(db, "claude:main", a)


def test_three_days_on_and_the_fix_is_yours(admin, db):
    """R5: opening Testing hands a player's unanswered confirmation to Brett after three days."""
    from datetime import timedelta

    from app import picks

    pat = picks.user_row(db, {"email": "player@example.com"})
    n = rules.send_note(db, user_id=pat.id if pat else None, first_name="Pat", role="player", kind="problem", text="Rests")
    issue = rules.file_issue(db, "user:1", n)
    _live(db, issue)
    if issue.confirm_by:
        issue.confirm_since = rules.now() - timedelta(days=4)
        db.flush()
    admin.get("/manage/testing")
    assert issue.confirm_by is None


def test_a_round_of_one_never_ends_the_round_it_joined(admin, db):
    """R11: ▶ Try it from another device doesn't end the round Brett has open."""
    c = _check(db)
    me = views.person(db, {"email": "admin@example.com"})
    r = rules.open_round(db, "user:x", me["id"])
    db.flush()
    admin.post(f"/manage/testing/checks/{c.id}/go")
    admin.post(f"/manage/testing/checks/{c.id}/try", data={"result": "passed"})
    assert db.get(FftRound, r.id).ended_at is None


def test_an_approval_names_what_you_saw(admin, player, db):
    """T1, R14: words a player added after the page was drawn aren't approved unseen."""
    n = rules.send_note(db, user_id=None, first_name="Trah", role="player", kind="problem", text="Rests")
    db.flush()
    seen = 0
    rules.add_line(db, "askdnd", "And a secret added later", note=n, who="sender", approved=False)
    db.flush()
    admin.post(f"/manage/feedback/notes/{n.id}", data={"do": "issue", "seen": str(seen)})
    assert db.get(FftNote, n.id).state == "waiting"


def test_names_are_first_names_never_an_email(db):
    """T2."""
    me = views.person(db, {"email": "someone@example.com", "name": "someone@example.com"})
    assert "@" not in me["first_name"]
    n = rules.send_note(db, user_id=None, first_name="someone@example.com", role="player", kind="problem", text="x",
                        context={"viewing_as": "Pat Player", "nested": {"who": "a@example.com", "fine": "ok"}, "list": ["b@example.com", "c"]})
    assert "@" not in n.first_name and n.context == {"viewing_as": "Pat", "nested": {"fine": "ok"}, "list": ["c"]}


def test_a_strange_key_is_no_one(db):
    assert keys.actor_for(db, "ključ" * 10) is None
