"""Tests don't depend on each other's order (CLAUDE.md › Conventions): what the app keeps per request starts fresh in
every test (tests/conftest.py `_fresh_context`)."""

import re
from pathlib import Path

from tests.conftest import context_values

APP = Path(__file__).resolve().parent.parent / "app"


def test_every_context_value_in_the_app_is_reset_before_each_test():
    found = {name for f in APP.rglob("*.py") for name in re.findall(r"ContextVar\(\s*[\"']([^\"']+)[\"']", f.read_text())}
    reset = {var.name for var, _ in context_values()}
    assert found == reset, f"add each to tests/conftest.py context_values: {sorted(found - reset)}"


def test_a_value_one_test_leaves_never_reaches_the_next():
    from app import history

    history.set_actor("someone@example.com")
    with history.source("import", "b1"):
        pass
    history._source.set(("claude", None))  # (as a test that forgot to put it back would leave it)


def test_and_the_next_test_starts_from_the_defaults():
    from app import history

    assert history._actor.get() == "" and history._source.get() == ("edit", None)
