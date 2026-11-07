"""View as (app/view_as.py): an admin sees askdnd as someone else does, read-only."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.importer import import_bundle
from app.main import app
from app.models import Fact, Entity
from tests.roles import set_role

BUNDLE = {"campaign": {"slug": "main", "name": "Main"}, "entities": [{"kind": "npc", "name": "Kieran", "summary": "A sailor."}],
          "sessions": [{"number": 1}]}


def client_for(monkeypatch, db, email):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("brett@example.com,mark@example.com,dm@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("brett@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": email, "email_verified": True, "name": email.split("@")[0].title()}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    return c


@pytest.fixture
def setup(monkeypatch, db):
    import_bundle(db, BUNDLE)
    set_role(db, "dm@example.com", "dm", name="Dee")
    set_role(db, "mark@example.com", "player", name="Mark")
    yield db
    app.dependency_overrides.clear()


def test_an_admin_sees_what_the_dm_and_a_player_see_and_changes_nothing(setup, monkeypatch):
    db = setup
    admin = client_for(monkeypatch, db, "brett@example.com")
    assert "View as" in admin.get("/manage/accounts").text

    admin.post("/view-as", data={"email": "dm@example.com"})
    page = admin.get("/").text
    assert "Viewing as <b>Dee</b>, DM in Main" in page and "Stop viewing" in page
    assert admin.get("/c/main/manage").status_code == 200  # the DM's Manage pages
    assert admin.get("/manage/usage", follow_redirects=False).status_code == 403  # but not an admin's

    kieran = db.scalar(select(Entity).where(Entity.name == "Kieran"))
    r = admin.post(f"/campaign/{kieran.id}/facts?in=panel", data={"text": "He sings."}, headers={"HX-Request": "true"})
    assert "nothing can be changed" in r.headers.get("HX-Trigger", "") and db.scalar(select(Fact)) is None
    admin.post(f"/campaign/{kieran.id}/suggest", data={"text": "He sings."})
    assert db.scalar(select(Fact)) is None  # a plain form is refused too

    admin.post("/view-as/stop")
    assert "Viewing as" not in admin.get("/").text and admin.get("/manage/usage").status_code == 200

    admin.post("/view-as", data={"email": "mark@example.com"})
    page = admin.get("/").text
    assert "Viewing as <b>Mark</b>, Player in Main" in page and 'href="/c/main/manage"' not in page


def test_only_admins_and_never_a_dm_into_their_players_notes(setup, monkeypatch):
    """A standing rule (CLAUDE.md › Privacy): character notes are visible to players but never the DM. View as is for
    admins, and never shows a DM their players' notes."""
    db = setup
    player = client_for(monkeypatch, db, "mark@example.com")
    player.post("/view-as", data={"email": "dm@example.com"})
    assert "Viewing as" not in player.get("/").text

    set_role(db, "brett@example.com", "dm", name="Brett")  # the admin is this campaign's DM
    admin = client_for(monkeypatch, db, "brett@example.com")
    admin.post("/view-as", data={"email": "mark@example.com"})
    assert "Viewing as" not in admin.get("/").text  # would show the DM their player's notes
    assert 'action="/view-as"' not in admin.get("/manage/accounts").text.split("mark@example.com")[1].split("</div>")[0]


def test_viewing_as_a_player_shows_their_notes_only_and_marks_nothing_seen(setup, monkeypatch):
    """Brett, Nov 7: viewing as Mark, Your notes showed Brett's own feedback. It shows the viewed person's, and looking
    changes nothing for them: their badge and cards stay theirs (View as is read-only)."""
    from app import picks
    from app.models import Feedback

    db = setup
    admin = client_for(monkeypatch, db, "brett@example.com")
    mark = picks.user_row(db, {"email": "mark@example.com", "name": "Mark"})
    brett = picks.user_row(db, {"email": "brett@example.com", "name": "Brett"})
    db.add_all([Feedback(user_id=brett.id, sender="Brett (admin)", text="Brett's own note", status="done"),
                Feedback(user_id=mark.id, sender="Mark (player)", text="Mark's note", status="done")])
    db.flush()
    admin.post("/view-as", data={"email": "mark@example.com"})
    page = admin.get("/your-notes?tab=askdnd").text
    assert "Mark&#39;s note" in page and "Brett&#39;s own note" not in page
    news = admin.get("/your-notes/news").json()
    assert news["count"] == 1 and news["cards"] == []  # (his count; his cards stay his)
    db.expire_all()
    assert db.scalar(select(Feedback).where(Feedback.user_id == mark.id)).seen == ""  # (nothing marked seen for him)
