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
from tests.menu import door, has_door, items
from tests.test_suggestions import client_for


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def test_admin_sees_both_groups_in_the_menu(monkeypatch, db):
    """Brett, 2026-10-27 (docs/mockups/manage-menu.html, round 2 option A): two doors, Manage for this campaign and
    Admin for askdnd as a whole; each lists what's opened most, and every page lists the rest of its half down the
    left, under a line in its half's colour."""
    import_bundle(db, {"campaign": {"slug": "main", "name": "The Lost Mine"}})
    import_bundle(db, {"campaign": {"slug": "second", "name": "Second Wind"}})
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/c/main/manage").text  # opens Needs you at the campaign's address
    assert "<h1>Needs you</h1>" in page and "What's waiting in The Lost Mine" in page
    menu = door(page, "manage")
    assert "The Lost Mine" in menu  # whose it is, at its head
    # the campaign's pages (the most used, then the rest on one line), then your other campaigns (tests/menu.py)
    assert items(page, "manage") == ["dm-tools", "needs", "inbox", "sessions", "table", "house", "settings", "history", "guide", "campaign:second"]
    assert 'href="/c/main/manage/inbox"' in menu and "/manage/askdnd" not in menu
    assert "askdnd admin" in door(page, "admin")
    assert items(page, "admin") == ["overview", "accounts", "campaigns", "feedback", "documents", "usage", "backups",
                                    "features", "askdnd-history", "corrections", "dice", "design"]

    band = page.split('class="manage-band')[1].split("</div>")[0]
    assert band.startswith(' camp"') and "The Lost Mine" in band and 'href="/manage/askdnd">⚙ Admin' in band
    side = page.split('class="manage-side"')[1].split("</nav>")[0]
    assert [s.split('class="manage-sec">')[1].split("<")[0] for s in side.split("<span")[1:] if 'manage-sec"' in s] == ["Every week", "The table", "Setup"]
    assert 'aria-current="page">Needs you' in side
    usage = admin.get("/manage/usage").text
    band = usage.split('class="manage-band')[1].split("</div>")[0]
    assert band.startswith(' tool"') and "askdnd admin" in band and "The Lost Mine's Manage" in band
    side = usage.split('class="manage-side"')[1].split("</nav>")[0]
    assert 'aria-current="page">Usage' in side and "Inbox" not in side and ">askdnd history<" in side
    assert side.index(">Overview<") < side.index(">Accounts<") < side.index(">Usage<") < side.index(">Design system<")

    overview = admin.get("/manage/askdnd").text
    assert "<h1>askdnd admin</h1>" in overview and "No backup recorded yet" in overview and 'href="/manage/accounts"' in overview
    assert admin.get("/c/main/manage/counts").json() == {"needs": 1, "inbox": 0, "feedback": 0}  # (the backup to check; notes for Claude, admins)


def test_reviewers_see_campaign_pages_only_and_players_none(monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    page = reviewer.get("/c/main/manage").text
    assert {"sessions", "inbox"} <= set(items(page, "manage")) and not has_door(page, "admin")  # Admin is for admins
    assert 'class="manage-band camp"' in page and "askdnd admin →" not in page
    assert not {"table", "settings"} & set(items(page, "manage"))  # those are the DM's and admins'
    assert reviewer.get("/manage/askdnd").status_code == 403
    player = client_for(monkeypatch, db, "mark@example.com")
    assert player.get("/c/main/manage").status_code == 403
    assert player.get("/c/main/manage/counts").json() == {}
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


def test_needs_you_reads_each_sessions_status_in_one_go(monkeypatch, db):
    """Needs you (and its count in the Manage menu) reads every session's review status in one query, the same as each
    session's own: no draft, a draft, published, or edited after publishing."""
    from app import review
    from app.models import Recap, Status

    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "sessions": [{"number": n, "played_on": f"2026-01-{n + 10}"} for n in range(1, 5)]})
    s1, s2, s3, s4 = db.scalars(select(GameSession).order_by(GameSession.number)).all()
    for s, recaps in ((s2, [Status.DRAFT]), (s3, [Status.PUBLISHED]), (s4, [Status.PUBLISHED, Status.DRAFT])):
        db.add_all(Recap(session_id=s.id, version=v, body="…", author="ai", status=st) for v, st in enumerate(recaps, 1))
    db.flush()
    db.expire_all()
    camp = db.scalar(select(Campaign))
    got = review.statuses(db, camp.id)
    assert {s.id: got.get(s.id, "no draft") for s in (s1, s2, s3, s4)} == {s.id: review.review_status(s, False) for s in (s1, s2, s3, s4)}
    assert [got.get(s.id, "no draft") for s in (s1, s2, s3, s4)] == ["no draft", "draft", "published", "edited"]
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    assert "2 sessions ready to review" in client_for(monkeypatch, db, "dm@example.com").get("/c/main/manage").text


def test_needs_you_says_when_a_character_couldnt_refresh(monkeypatch, db, no_network):
    """It reads only each sheet's status and when it was fetched, not the sheets themselves."""
    from app import characters
    from tests.table_setup import BUNDLE, char

    import_bundle(db, BUNDLE)
    cole = char(db, "Cole")
    characters.refresh(db, cole)
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    slug = db.scalar(select(Campaign.slug))
    assert "couldn&#39;t refresh" not in reviewer.get(f"/c/{slug}/manage").text
    cole.snapshot.status = "error"
    db.flush()
    assert "1 character couldn&#39;t refresh from D&amp;D Beyond" in reviewer.get(f"/c/{slug}/manage").text
