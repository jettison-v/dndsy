"""Manage: the campaign's pages and askdnd's, the Needs you page, the menu and tabs, and old addresses
(app/manage.py)."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select, update

from app import config
from app.config import parse_allowlist
from app.importer import import_bundle
from app.main import app
from app.models import Campaign, Entity, GameSession, JobRun, User
from tests.menu import door, half, half_items, has_half, items
from tests.test_suggestions import client_for


@pytest.fixture(autouse=True)
def _clear():
    yield
    app.dependency_overrides.clear()


def test_admin_sees_both_groups_in_the_menu(monkeypatch, db):
    """Brett, 2026-10-27 (docs/mockups/manage-menu.html, round 2 option A): two halves, this campaign's and askdnd's as
    a whole, every page listing its half down the left under a line in its half's colour; since Nov 13 (The Three Menus,
    docs/mockups/menus/) each in fixed groups, the campaign's by the DM's week with DM Tools inside, the DM guide in the
    account menu instead, the rarely opened pages on Tuning's line; since Nov 20 (Menu Bar Doors) one door, Backstage,
    its two halves side by side: This campaign and Global (its groups Our work, General, People, Tuning)."""
    import_bundle(db, {"campaign": {"slug": "main", "name": "The Lost Mine"}})
    import_bundle(db, {"campaign": {"slug": "second", "name": "Second Wind"}})
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/c/main/manage").text  # opens Needs you at the campaign's address
    assert "<h1>Needs you</h1>" in page and "What's waiting in The Lost Mine" in page
    menu = half(page, "campaign")
    assert "The Lost Mine" in menu and "This campaign" in menu  # whose it is, at its head
    # the campaign's pages (the most used, then the rest on one line), then your other campaigns (tests/menu.py)
    assert half_items(page, "campaign") == ["needs", "inbox", "sessions", "dm-tools", "table", "house", "settings", "history", "campaign:second"]
    assert items(page, "manage") == half_items(page, "campaign") + half_items(page, "askdnd")  # (one door, both halves)
    assert [g.split("<")[0] for g in menu.split('class="menu-group">')[1:]] == ["After the game", "The next game", "The table", "Your other campaigns"]
    assert "guide" in items(page, "account") and "guide" not in items(page, "manage")  # (read, not run: Help in your menu)
    assert 'href="/c/main/manage/inbox"' in menu and "/manage/askdnd" not in menu
    assert "Global" in half(page, "askdnd")
    assert half_items(page, "askdnd") == ["for-you", "feedback", "roadmap", "work", "overview", "product-areas", "documents", "usage", "backups", "features", "books", "accounts", "campaigns",
                                    "askdnd-history", "corrections", "dice", "sync", "design"]  # (Sync, beside the bridge: Roadmap item 44)
    assert [g.split("<")[0] for g in half(page, "askdnd").split('class="menu-group">')[1:]] == ["Workshop", "General", "People", "Tuning"]

    band = page.split('class="manage-band')[1].split("</div>")[0]
    assert band.startswith(' camp"') and "The Lost Mine" in band and "manage-cross" not in band  # (the way across is Backstage in the bar: issue 23)
    side = page.split('class="manage-side"')[1].split("</nav>")[0]
    assert [s.split('class="manage-sec">')[1].split("<")[0] for s in side.split("<span")[1:] if 'manage-sec"' in s] == ["After the game", "The next game", "The table"]
    assert 'aria-current="page">Needs you' in side
    usage = admin.get("/manage/usage").text
    band = usage.split('class="manage-band')[1].split("</div>")[0]
    assert band.startswith(' tool"') and "Global" in band
    side = usage.split('class="manage-side"')[1].split("</nav>")[0]
    assert 'aria-current="page">Usage' in side and "Inbox" not in side and ">askdnd history<" in side
    assert side.index(">Overview<") < side.index(">Usage<") < side.index(">Accounts<") < side.index(">Design system<")  # (the menu is the page list)

    overview = admin.get("/manage/askdnd").text
    assert "<h1>Overview</h1>" in overview and "No backup recorded yet" in overview and 'href="/manage/accounts"' in overview
    assert admin.get("/c/main/manage/counts").json() == {"needs": 1, "inbox": 0, "feedback": 0, "for-you": 0}  # (the backup to check; notes for Claude and checks to try, admins)


def test_reviewers_see_campaign_pages_only_and_players_none(monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    page = reviewer.get("/c/main/manage").text
    assert {"sessions", "inbox"} <= set(items(page, "manage")) and not has_half(page, "askdnd")  # Global is for admins
    assert 'class="manage-band camp"' in page
    assert not {"table", "settings"} & set(items(page, "manage"))  # those are the DM's and admins'
    assert reviewer.get("/manage/askdnd").status_code == 403
    player = client_for(monkeypatch, db, "mark@example.com")
    assert player.get("/c/main/manage").status_code == 403
    assert player.get("/c/main/manage/counts").json() == {}
    assert "/manage" not in player.get("/").text.split('class="bar-end"')[1].split('class="account"')[0]


def test_needs_you_lists_whats_waiting_and_admin_items(monkeypatch, db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"},
                       "sessions": [{"number": 1, "played_on": "2026-01-10"}, {"number": 2, "played_on": "2026-01-17"}]})
    from app.models import NoteSnapshot, NoteSource

    src = NoteSource(campaign_id=db.scalar(select(Campaign)).id, google_doc_id="d" * 30, title="Campaign doc")  # (what Draft from notes drafts)
    src.snapshots.append(NoteSnapshot(content_hash="h", text="# Session 1\nA.\n# Session 2\nB."))
    db.add(src)
    db.flush()
    monkeypatch.setattr(config, "REVIEWER_EMAILS", parse_allowlist("dm@example.com"))
    reviewer = client_for(monkeypatch, db, "dm@example.com")
    page = reviewer.get("/c/main/manage").text
    assert "2 sessions not drafted yet" in page and 'data-item="draft-next"' in page and "No backup recorded yet" not in page  # admins only (a button that does it: NY1)
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/c/main/manage").text
    assert "No backup recorded yet" in page and 'href="/manage/backups"' in page
    db.add(JobRun(name="backup", status="ok", started_at=datetime.now(UTC)))
    db.flush()
    src.snapshots.append(NoteSnapshot(content_hash="h2", text="Nothing per session yet."))  # nothing to draft from notes
    db.flush()
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


def test_round_one_overview_backups_usage_and_rule_books(monkeypatch, db):
    """Brett's picks on docs/mockups/backstage-round-1/ (Nov 25): Overview's cards in the menu's sections, every card a
    state, what needs you amber and what's broken red where it sits (OV1 C, OV2 B); Backups a panel saying what
    happened and what to check, its runs a table marking only failures (BK1, BK2); rule books a page of their own (BK3);
    Usage's limit first, amber until set, changed from its tile; a top-up and an import from their windows (US1, S4)."""
    from datetime import UTC, datetime, timedelta

    from app.models import JobRun

    import_bundle(db, {"campaign": {"slug": "main", "name": "The Lost Mine"}})
    admin = client_for(monkeypatch, db, "brett@example.com")
    now = datetime.now(UTC)
    db.add(JobRun(name="backup", status="ok", detail="v2/backups/a.json.gz · 4.8 MB · 10,682 rows · 236 files", started_at=now, finished_at=now - timedelta(days=3)))
    db.flush()
    ov = admin.get("/manage/askdnd").text
    heads = [h.split("</h2>")[0] for h in ov.split('class="ov-section-h"')[1:]]
    assert [h.split(">", 1)[1] for h in heads] == ["Workshop", "General", "People", "Tuning"]
    assert 'data-card="backups" data-tone="bad"' in ov and "No backup for 3 nights" in ov
    assert 'data-card="usage" data-tone="warn"' in ov and "No monthly limit set" in ov
    for key in ("feedback", "roadmap", "work", "books", "features", "askdnd-history", "dice"):  # (every card a state: OV2 B)
        card = ov.split(f'data-card="{key}"')[1].split("</a>")[0]
        assert 'class="ov-state' in card, key
    bk = admin.get("/manage/backups").text
    assert 'data-needs="backup-attention"' in bk and "3 nights missed" in bk and "4.8 MB" in bk and "10,682" in bk
    assert "v2/backups/" not in bk and 'id="books"' not in bk and 'action="/manage/backups/import"' not in bk  # (the form opens on demand)
    assert 'data-modal-url="/manage/backups/import-window"' in bk and 'type="file"' in admin.get("/manage/backups/import-window").text
    books = admin.get("/manage/books").text
    assert "<h1>Rule books</h1>" in books and 'data-modal-url="/manage/books/upload-window"' in books
    assert 'action="/manage/backups/books"' in admin.get("/manage/books/upload-window").text
    usage = admin.get("/manage/usage").text
    assert 'data-tile="limit"' in usage and "None set" in usage and 'data-modal-url="/manage/usage/limit-window"' in usage
    assert 'action="/manage/usage/topups"' not in usage and 'action="/manage/usage/topups"' in admin.get("/manage/usage/topup-window").text
    assert admin.post("/manage/usage/limit", data={"amount": "20"}, follow_redirects=False).status_code == 303
    usage = admin.get("/manage/usage").text
    assert "$20.00" in usage.split('data-tile="limit"')[1].split("</div>")[0] and 'class="stat needs"' not in usage


def test_round_two_settings_in_tabs_and_tables_one_action(monkeypatch, db):
    """Brett's picks on docs/mockups/backstage-round-2/ (Nov 25): Settings in four tabs, each feature one line with what
    to know first beside its switch and the longer story in its More fold (SE1, SE2); the page's own links land on their
    tab; Table one action and a ⋯ for Refresh all, each player's Sheet ↗ (TA1)."""
    from markupsafe import escape

    from app import vtt

    import_bundle(db, {"campaign": {"slug": "main", "name": "The Lost Mine"}})
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/c/main/manage/settings").text
    tabs = [t.split('data-tab="t-')[1].split('"')[0] for t in page.split('role="tab"')[1:]]
    assert tabs == ["campaign", "books", "pictures", "features"]
    assert 'id="t-campaign" role="tabpanel">' in page and 'id="t-features" role="tabpanel" hidden' in page
    feat = admin.get("/c/main/manage/settings?tab=features").text
    assert 'id="t-features" role="tabpanel">' in feat and "Roadmap:" not in feat
    sync = feat.split('data-feature="sync"')[1].split("</li>")[0]
    assert str(escape(vtt.feature("sync").line)) in sync and 'data-warn' in sync and "More</summary>" in sync
    r = admin.post("/c/main/manage/settings/vtt/sync", data={"on": "1"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/c/main/manage/settings?tab=features#features"  # (back on its tab)
    table = admin.get("/c/main/manage/table").text
    head = table.split('class="title-row"')[1].split("</div>")[0]
    assert head.count('class="btn"') <= 1


def test_round_four_pages_dm_guide_accounts_and_product_areas(monkeypatch, db):
    """Brett's picks DG1, AC1 and PA1 (docs/mockups/backstage-round-4/, Nov 25): the DM guide in the tab bar with only
    what's on; Accounts a line each, test accounts tagged Test with a filter, Rename… in the ⋯; Product areas busiest
    first."""
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    admin = client_for(monkeypatch, db, "brett@example.com")
    guide = admin.get("/c/main/manage/dm-guide?tab=recaps").text
    assert 'role="tablist" data-tab-param' in guide and 'aria-selected="true" data-tab="t-recaps"' in guide
    assert 'id="table"' not in guide and 'id="dm-backup"' not in guide  # (askdnd's table and Sync are off here)
    db.scalar(select(Campaign)).vtt_pieces = ["vtt", "labs"]
    db.commit()
    assert 'id="table"' in admin.get("/c/main/manage/dm-guide").text
    test_camp = Campaign(slug="vtt-test", name="VTT test", is_test=True)
    db.add(test_camp)
    db.flush()
    from app.models import CampaignMember, Role
    tester = User(email="seat@example.com", name="ΩSeat one", access="member")
    db.add(tester)
    db.flush()
    db.add(CampaignMember(campaign_id=test_camp.id, user_id=tester.id, role=Role.PLAYER))
    db.commit()
    from app import access
    access.invalidate()
    page = admin.get("/manage/accounts").text
    row = next(li for li in page.split("<li ") if 'data-name="seat one' in li)
    assert 'data-views="test all"' in row and 'data-test-account' in row and "Ω" not in row.split("<span")[0]
    assert 'data-modal-url="/manage/accounts/rename?email=seat%40example.com"' in row and "Change name" not in page
    assert 'name="name" value="ΩSeat one"' in admin.get("/manage/accounts/rename?email=seat@example.com").text
    cards = admin.get("/manage/product-areas").text
    assert 'class="panel pa-card"' in cards


def test_usage_keeps_the_newest_calls_of_each_kind(monkeypatch, db):
    """The end-of-day review (Nov 25): recent calls were cut to the newest 20 before All · Claude · OpenAI filtered them,
    so OpenAI's view could be empty though there were OpenAI calls. Now every call is in the page and the list shows the
    newest 20 of the kind that's on, the rest one fold away (Brett's pick AU5)."""
    from app.admin_usage import CALLS_SHOWN, OPENAI
    from app.models import ExtractionRun

    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}})
    openai = next(iter(OPENAI))
    db.add(ExtractionRun(source=openai, status="done", cost_usd=0.01))
    db.flush()
    db.add_all([ExtractionRun(source="notes", status="done", cost_usd=0.1) for _ in range(CALLS_SHOWN + 5)])
    db.commit()
    admin = client_for(monkeypatch, db, "brett@example.com")
    page = admin.get("/manage/usage").text
    assert page.count('data-views="openai all"') == 1 and page.count('data-views="claude all"') == CALLS_SHOWN + 5
    assert f'data-ls-cap="{CALLS_SHOWN}"' in page and "data-ls-unfold" in page  # (each kind's newest few, the rest in place: AU5)
