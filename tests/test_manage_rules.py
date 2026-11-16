"""Manage's written rules (the UI review, part 3, Nov 16; docs/DESIGN.md): a page's own action is its title row's, a
form opening in a window from it; prices, dates and session names are written one way; every admin-only page says so;
Documents is one list on the shared list pieces."""

from datetime import date

from app.extraction import session_label
from app.models import GameSession
from app.templating import templates
from tests.table_setup import two_campaigns


def test_a_pages_own_action_is_its_title_rows(admin, db):
    """+ Add to the table and + Add an account are their pages' title actions, each opening a window with the form."""
    two_campaigns(db)
    table = admin.get("/c/main/manage/table").text
    title = table[table.index('<div class="title-row"><h1>Table</h1>'):table.index("</div>", table.index('<div class="title-row"><h1>Table</h1>'))]
    assert 'data-item="add-to-table"' in title and 'class="seat-add"' not in table
    window = admin.get("/c/main/manage/table/add").text
    assert 'action="/c/main/manage/table/add"' in window and 'id="peek-title"' in window
    accounts = admin.get("/manage/accounts").text
    assert 'data-item="add-account"' in accounts and 'action="/manage/accounts" class="form-narrow"' not in accounts
    assert 'action="/manage/accounts"' in admin.get("/manage/accounts/new").text
    assert 'data-item="new-campaign"' in admin.get("/manage/campaigns").text.split("</h1>", 1)[1].split("</div>", 1)[0]


def test_the_windows_are_for_whoever_runs_the_page(player, db):
    two_campaigns(db)
    assert player.get("/manage/accounts/new").status_code in (303, 403)
    assert player.get("/c/main/manage/table/add").status_code in (303, 403)


def test_money_dates_and_session_names_are_written_one_way():
    money = templates.env.filters["money"]
    assert (money(0.13), money(1.02), money(0.004), money(0), money(None)) == ("$0.13", "$1.02", "under $0.01", "$0.00", "$0.00")
    s = GameSession(id=9, number=29, played_on=date(2026, 2, 7))
    assert session_label(s) == "Session 29 · Feb 7, 2026"
    assert session_label(GameSession(id=9, number=20)) == "Session 20"


def test_every_admin_page_says_it_is_for_admins(admin, db):
    two_campaigns(db)
    for path in ("/manage/askdnd", "/manage/feedback", "/manage/documents", "/manage/usage", "/manage/features", "/manage/dice"):
        page = admin.get(path).text
        subtitle = page[page.index('<p class="subtitle">'):page.index("</p>", page.index('<p class="subtitle">'))]
        assert "Only admins can see this page." in subtitle, path


def test_documents_is_one_list_on_the_shared_pieces(admin, db):
    page = admin.get("/manage/documents").text
    assert 'data-list="documents"' in page and "data-ls-search" in page and page.count("data-ls-row") > 10
    assert 'class="doc-search" method="get"' not in page  # (the page's own search box, not a form of its own)
