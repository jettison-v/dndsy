"""The access chart and each person's line on Manage › Table (app/access.py `chart`, `summary`), and the loader that reads
who's who from the database. Written from mutation testing (foundation F8, Nov 13): these changes went unnoticed by
every other test: a chart whose groups listed each other's rows, a chart missing its groups or "not included", the
admin's extra line shown to everyone but admins, and the live loader reading no database."""

from app import access
from tests.test_dm_backup import table


def test_each_group_of_the_chart_holds_exactly_its_own_rows():
    c = access.chart()
    assert c["rows"] and c["groups"]
    for group, rows in c["groups"]:
        assert rows and all(r["group"] == group for r in rows)
    assert [r for _, rows in c["groups"] for r in rows] == sorted(c["rows"], key=lambda r: [g for g, _ in c["groups"]].index(r["group"]))
    assert len(c["rows"]) == sum(len(rows) for _, rows in c["groups"])
    assert c["not_included"], "the chart says what it leaves out"
    assert all(len(r["cells"]) == len(c["columns"]) for r in c["rows"])


def test_the_table_page_draws_every_row_of_the_chart(dm, table):
    """Jinja draws a missing part as nothing: the page must carry every row and what's left out."""
    page = dm.get("/c/main/manage/table").text
    c = access.chart()
    assert page.count('class="access-group"') == len(c["groups"])
    from markupsafe import escape

    for x in c["not_included"]:
        assert str(escape(x)) in page


def test_the_admin_line_goes_to_admins_only():
    for role in (access.DM, access.REVIEWER, access.PLAYER, None):
        plain, admin = access.summary(access.MEMBER, role), access.summary(access.ADMIN, role)
        assert admin != plain and admin.startswith(plain[:-1]), "an admin's line is the member's with more"
    assert access.summary(None, access.PLAYER) not in {access.summary(access.MEMBER, r) for r in (access.DM, access.REVIEWER, access.PLAYER, None)}


def test_the_live_loader_reads_the_database(db_engine, monkeypatch):
    """The tests swap the loader for one of their own (conftest `db`); this runs the real one, against the test database."""
    from sqlalchemy.orm import sessionmaker

    from app import db as app_db

    monkeypatch.setattr(app_db, "engine", db_engine)
    monkeypatch.setattr(app_db, "SessionLocal", sessionmaker(bind=db_engine))
    monkeypatch.setattr(app_db, "LoopSession", sessionmaker(bind=db_engine))
    out = access._load_from_db()
    assert access.CAMPAIGNS in out and access.TUNING in out
