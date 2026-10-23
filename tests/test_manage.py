"""Manage: the campaign's pages and askdnd's, the Needs you page, the menu and tabs, and old addresses
(app/manage.py)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update

from app import config
from app.importer import import_bundle
from app.models import Campaign, Entity, GameSession, JobRun, User
from app.config import parse_allowlist
from app.main import app
from tests.test_suggestions import client_for


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def test_admin_sees_both_groups_in_the_menu(monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "The Lost Mine"}})
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/c/main/manage").text  # opens Needs you at the campaign's address
    assert "<h1>Needs you</h1>" in page and "What's waiting in The Lost Mine" in page
    menu = page.split('id="manage-menu"')[1].split("</div>\n    </div>")[0]
    assert menu.index('menu-group">The Lost Mine') < menu.index('menu-group">askdnd · admins')
    for label, path in (("Needs you", ""), ("Inbox", "/inbox"), ("Sessions", "/sessions"), ("Table", "/table"),
                        ("House rules", "/house-rules"), ("History", "/history"), ("Settings", "/settings"), ("DM guide", "/dm-guide")):
        assert f'<a href="/c/main/manage{path}" class="' in menu and f">{label}</a>" in menu
    for href in ("/manage/campaigns", "/manage/accounts", "/manage/tool-corrections", "/manage/usage", "/manage/backups",
                 "/manage/history", "/manage/design"):
        assert f'href="{href}"' in menu
    assert menu.index(">Backups and imports</a>") < menu.index(">Design system</a>")  # the design system is last
    tabs = admin.get("/c/main/manage/sessions/doc").text.split('class="manage-tabs"')[1].split("</nav>")[0]
    assert 'class="on" aria-current="page">Sessions' in tabs and "Usage" not in tabs  # tabs for its own group
    tabs = admin.get("/manage/usage").text.split('class="manage-tabs"')[1].split("</nav>")[0]
    assert 'class="on" aria-current="page">Usage' in tabs and "Inbox" not in tabs


def test_reviewers_see_campaign_pages_only_and_players_none(monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    menu = reviewer.get("/c/main/manage").text.split('id="manage-menu"')[1].split("</div>\n    </div>")[0]
    assert ">Sessions</a>" in menu and ">Inbox</a>" in menu and "askdnd · admins" not in menu
    assert ">Table</a>" not in menu and ">Settings</a>" not in menu  # those are the DM's and admins'
    player = client_for(monkeypatch, db, "mark@example.com")
    assert player.get("/c/main/manage").status_code == 403
    assert "/manage" not in player.get("/").text.split('class="bar-end"')[1].split('class="account"')[0]


def test_needs_you_lists_whats_waiting_and_admin_items(monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "sessions": [{"number": 1, "played_on": "2026-01-10"}, {"number": 2, "played_on": "2026-01-17"}]})
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    page = reviewer.get("/c/main/manage").text
    assert "Backlog: 2 sessions not drafted yet" in page and "No backup recorded yet" not in page  # admins only
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/c/main/manage").text
    assert "No backup recorded yet" in page and 'href="/manage/backups"' in page
    db.add(JobRun(name="backup", status="ok", started_at=datetime.now(UTC)))
    db.flush()
    db.execute(update(GameSession).values(source="manual"))  # nothing to draft
    assert "✓ All caught up" in admin.get("/c/main/manage").text


def test_old_addresses_are_gone(monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    admin = client_for(monkeypatch, db, "brett@example.com")
    for old in ("/admin/sessions", "/admin/sessions/7", "/admin/notes", "/suggestions", "/admin/history?table=entities&row=3",
                "/admin/people", "/admin/characters", "/admin/import", "/admin/usage", "/manage/inbox", "/manage", "/c/main/manage/usage"):
        assert admin.get(old, follow_redirects=False).status_code == 404, old  # gone: one address per page (2026-10-23)
    assert admin.get("/manage/history", follow_redirects=False).status_code == 200  # askdnd's History has no campaign


def test_history_is_split_between_the_campaign_and_askdnd(monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": [{"kind": "npc", "name": "Sildar"}]})
    import_bundle(db, {"campaign": {"slug": "other", "name": "Other"}, "entities": [{"kind": "npc", "name": "Ireena"}]})
    for name in ("Sildar", "Ireena"):
        db.scalar(select(Entity).where(Entity.name == name)).name = name + " Hallwinter"
    db.add(User(email="nia@example.com", name="Nia", access="member"))
    db.flush()
    db.scalar(select(User).where(User.email == "nia@example.com")).access = "admin"
    db.scalar(select(Campaign).where(Campaign.slug == "main")).name = "The Lost Mine"
    db.flush()
    admin = client_for(monkeypatch, db, "brett@example.com")
    here = admin.get("/c/main/manage/history").text
    assert "Sildar Hallwinter" in here and "Ireena" not in here and "nia@example.com" not in here
    assert "Campaign: The Lost Mine" in here
    wide = admin.get("/manage/history").text
    assert "Person: nia@example.com" in wide and "Sildar" not in wide
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    assert reviewer.get("/manage/history").status_code == 403 and reviewer.get("/c/main/manage/history").status_code == 200


def test_design_system_page_is_for_admins(monkeypatch, db):
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/manage/design").text
    assert ">Design system</a>" in admin.get("/manage/design").text  # in the menu
    for part in ("--fs-2xl", "Roll chip", "search_box()", 'data-panel-url="/manage/design/panel"'):
        assert part in page
    assert 'id="peek-title">Fire Bolt' in admin.get("/manage/design/panel").text
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    assert reviewer.get("/manage/design").status_code == 403 and reviewer.get("/manage/design/panel").status_code == 403


def test_dm_guide_shows_the_backlog_to_the_dm_only(monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": 1, "played_on": "2026-01-10"}]})
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    page = reviewer.get("/c/main/manage/dm-guide").text
    assert "You review" in page and "One session at a time" in page and "of 1</b> sessions are published" in page
    assert ">DM guide</a>" in reviewer.get("/c/main/manage").text
    player = client_for(monkeypatch, db, "mark@example.com")
    assert player.get("/c/main/manage/dm-guide").status_code == 403
