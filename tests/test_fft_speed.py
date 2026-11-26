"""Backstage pages read what they need once (Brett, Nov 20: "These pages are loading more slowly than I would
expect"): For you, its badge and Development used to ask the database about each check on its own, 150 to 500 small
queries a page, about a second on askdnd.ai. Their queries no longer grow with the number of checks, and what a request
changes is never read back stale."""

import pytest
from sqlalchemy import event, select

from app.fft import rules, taxonomy
from app.fft.models import FftArea, FftItem
from app.importer import import_bundle
from tests.table_setup import BUNDLE


@pytest.fixture(autouse=True)
def table(db):
    import_bundle(db, BUNDLE)
    db.flush()


def _make(db, n, item=None):
    item = item or FftItem(title="A build", section="now", place=1)
    db.add(item)
    db.flush()
    area = rules.new_area(db, "claude", item, f"Batch {n}")
    for i in range(n):
        issue = rules.new_issue(db, "claude", f"Thing {i}", area_id=area.id)
        c = rules.write_check(db, "claude", title=f"Check {i}", steps=["Look."], expect="Fine.", area_id=area.id, issue_ids=[issue.id])
        rules.preflight(db, "claude", c, True)
        if i % 2:
            rules.record_try(db, "user:1", c, result="failed", found=[rules.Found(issue_id=issue.id)])
    db.flush()
    return item


def _queries(db, client, path):
    """How many reads a page makes (on the test's own database: app.db's engine is never the one tests use)."""
    seen = {"n": 0}
    engine = db.get_bind().engine
    db.flush()
    db.expunge_all()  # (cold, as a request on askdnd.ai starts)
    db.expire_on_commit = False  # (as askdnd.ai's sessions: app/db.py; a page's commit keeps what it read)

    def count(*_):
        seen["n"] += 1

    event.listen(engine, "before_cursor_execute", count)
    try:
        assert client.get(path).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", count)
    return seen["n"]


@pytest.mark.parametrize("path", ["/manage/for-you/count", "/manage/for-you", "/manage/work", "/manage/work?tab=checks"])
def test_a_pages_queries_dont_grow_with_its_checks(db, admin, path):
    item = _make(db, 3)
    few = _queries(db, admin, path)
    _make(db, 30, db.get(FftItem, item.id))  # (the page read starts cold: the item is fetched again)
    many = _queries(db, admin, path)
    assert many - few <= 12, f"{path}: {few} queries with 3 checks, {many} with 33"


def test_what_a_request_changes_is_read_fresh(db):
    c = rules.write_check(db, "claude", title="On its own", steps=["Look."], expect="Fine.")
    rules.preflight(db, "claude", c, True)
    db.flush()
    assert rules.check_state(db, c)["state"] == "to_try"
    rules.record_try(db, "user:1", c, result="passed")  # (not flushed yet: the next read must see it)
    assert rules.check_state(db, c)["state"] == "passed"
    from sqlalchemy import update

    from app.fft.models import FftTry
    db.execute(update(FftTry).where(FftTry.check_id == c.id).values(replaced=True))  # (a write the ORM didn't make)
    assert rules.check_state(db, c)["state"] == "to_try"


def _plan(db, feature):
    """A Product Area's batch with an issue to fix and one with its check waiting on Brett."""
    fix = rules.new_issue(db, "claude", "To fix", feature=feature)
    tried = rules.new_issue(db, "claude", "Fixed", feature=feature)
    c = rules.write_check(db, "claude", title="Try it", steps=["Look."], expect="Fine.", area_id=fix.area_id, issue_ids=[tried.id])
    rules.preflight(db, "claude", c, True)
    db.flush()


@pytest.mark.parametrize("path", ["/manage/work", "/manage/work?tab=checks", "/manage/for-you"])
def test_a_pages_queries_dont_grow_with_its_plans(db, admin, path):
    """Issue 142: Development read each plan's issues, checks and scope one query at a time, several times over."""
    features = [a.features[0].key for a in taxonomy.areas()]
    for f in features[:2]:
        _plan(db, f)
    few = _queries(db, admin, path)
    for f in features[2:]:
        _plan(db, f)
    many = _queries(db, admin, path)
    assert many - few <= 4, f"{path}: {few} queries with 2 plans, {many} with {len(features)}"


def test_an_areas_issues_are_read_fresh_after_a_change(db):
    item = _make(db, 2)
    area = db.scalar(select(FftArea).where(FftArea.item_id == item.id))
    issues = rules.area_open_issues(db, area)
    assert len(issues) == 2 and rules.area_checks(db, area)
    issues[0].state = "closed"  # (not flushed yet: the next read must see it)
    assert [i.id for i in rules.area_open_issues(db, area)] == [issues[1].id]
    rules.new_issue(db, "claude", "One more", area_id=area.id)
    assert len(rules.area_open_issues(db, area)) == 2
