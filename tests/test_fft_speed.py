"""Backstage pages read what they need once (Brett, Nov 20: "These pages are loading more slowly than I would
expect"): For you, its badge and Development used to ask the database about each check on its own, 150 to 500 small
queries a page, about a second on askdnd.ai. Their queries no longer grow with the number of checks, and what a request
changes is never read back stale."""

import pytest
from sqlalchemy import event

from app.db import engine
from app.fft import rules
from app.fft.models import FftItem
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


def _queries(client, path):
    seen = {"n": 0}

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
    few = _queries(admin, path)
    _make(db, 30, item)
    many = _queries(admin, path)
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
