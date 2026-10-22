"""Manage: the overview page and grouped menu show each person only what they can open (app/manage.py)."""

import pytest

from app import config
from app.config import parse_allowlist
from app.main import app
from tests.test_suggestions import client_for


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def test_admin_sees_every_area_grouped(monkeypatch, db):
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/manage").text
    for label in ("Suggestions", "Recaps", "People", "Characters", "Usage", "Data"):
        assert f"<b>{label}</b>" in page
    assert page.index('menu-group">Table') < page.index('menu-group">Party') < page.index('menu-group">Admin')  # menu groups in order
    assert 'class="on" aria-current="page">Recaps' in admin.get("/admin/notes").text  # the campaign doc lives under Recaps


def test_reviewers_see_table_pages_only_and_players_none(monkeypatch, db):
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    page = reviewer.get("/manage").text
    assert "<b>Recaps</b>" in page and "<b>Suggestions</b>" in page and "<b>People</b>" not in page and "<b>Usage</b>" not in page
    player = client_for(monkeypatch, db, "mark@example.com")
    assert player.get("/manage").status_code == 403
    assert 'href="/manage"' not in player.get("/").text


def test_design_system_page_is_for_admins(monkeypatch, db):
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/manage/design").text
    assert "<b>Design system</b>" in admin.get("/manage").text  # a card on the overview
    for part in ("--fs-2xl", "Roll chip", "search_box()", 'data-panel-url="/manage/design/panel"'):
        assert part in page
    assert 'id="peek-title">Fire Bolt' in admin.get("/manage/design/panel").text
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    assert reviewer.get("/manage/design").status_code == 403 and reviewer.get("/manage/design/panel").status_code == 403


def test_dm_guide_shows_the_backlog_to_the_dm_only(monkeypatch, db):
    from app.importer import import_bundle

    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": 1, "played_on": "2026-01-10"}]})
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    page = reviewer.get("/manage/dm-guide").text
    assert "You review" in page and "Draft the remaining sessions" in page and "of 1</b> sessions are published" in page
    assert "<b>DM guide</b>" in reviewer.get("/manage").text
    player = client_for(monkeypatch, db, "mark@example.com")
    assert player.get("/manage/dm-guide").status_code == 403
