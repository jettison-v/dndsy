import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.entities import build_describe_messages
from app.importer import import_bundle
from app.main import app
from app.models import Correction, Entity, Fact, GameSession, GlossaryTerm, Suggestion

HX = {"HX-Request": "true"}
BUNDLE = {
    "campaign": {"slug": "main", "name": "Main"},
    "entities": [{"kind": "npc", "name": "Kieran", "summary": "Cole's father."}],
    "glossary": [{"term": "Bhaal", "description": "old spelling"}, {"term": "Bhal", "description": "Big C's father"}],
    "sessions": [{"number": 17}],
}


def client_for(monkeypatch, db, email, reviewer=False):
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
def player(monkeypatch, db):
    yield client_for(monkeypatch, db, "mark@example.com")
    app.dependency_overrides.clear()


@pytest.fixture
def admin(monkeypatch, db):
    yield client_for(monkeypatch, db, "brett@example.com")
    app.dependency_overrides.clear()


def test_entity_correction_becomes_labeled_fact(player, db):
    import_bundle(db, BUNDLE)
    e = db.scalar(select(Entity).where(Entity.name == "Kieran"))
    r = player.post(f"/campaign/{e.id}/suggest", data={"kind": "correction", "text": "He is Cole's father, not uncle."}, headers=HX)
    assert "A reviewer will take a look" in r.text
    f = db.scalar(select(Fact))
    assert (f.kind, f.status, f.author_name) == ("correction", "pending", "Mark")
    f.status = "merged"
    db.flush()
    text = build_describe_messages(db, e)[0]["content"][0]["text"]
    assert "Correction: He is Cole's father, not uncle." in text
    assert "Suggest a correction or addition" in player.get(f"/campaign/{e.id}/peek").text


def test_session_suggestion_flows_to_review_and_redraft(player, admin, db):
    import_bundle(db, BUNDLE)
    s = db.scalar(select(GameSession))
    player.post(f"/sessions/{s.id}/suggest", data={"kind": "correction", "text": "Kieran, not Kiera."}, headers=HX)
    page = admin.get("/admin/sessions").text
    assert "From the table" in page and "Kieran, not Kiera." in page and "Use in next draft" in page
    x = db.scalar(select(Suggestion))
    admin.post(f"/admin/suggestions/{x.id}/use")
    db.expire_all()
    assert db.get(Suggestion, x.id).status == "used"
    c = db.scalar(select(Correction).where(Correction.session_id == s.id))
    assert (c.kind, c.after) == ("answer", "Kieran, not Kiera.") and "Correction from" in c.before
    assert "Kieran, not Kiera." not in admin.get("/admin/sessions").text  # handled, so gone from the list


def test_glossary_panel_suggest_edit_delete(player, admin, db):
    import_bundle(db, BUNDLE)
    old = db.scalar(select(GlossaryTerm).where(GlossaryTerm.term == "Bhaal"))
    assert "Bhal" in player.get(f"/campaign/glossary/{db.scalar(select(GlossaryTerm).where(GlossaryTerm.term == 'Bhal')).id}/peek").text
    player.post("/campaign/glossary/suggest", data={"text": "Add Womford, a fishing village."}, headers=HX)
    assert db.scalar(select(Suggestion)).target_id is None
    # Players can't edit or delete
    player.post(f"/campaign/glossary/{old.id}/delete", headers=HX)
    assert db.get(GlossaryTerm, old.id) is not None
    # Reviewers can
    r = admin.post(f"/campaign/glossary/{old.id}/edit", data={"term": "Bhal", "description": "x"}, headers=HX)
    assert "already in the glossary" in r.text
    admin.post(f"/campaign/glossary/{old.id}/delete", headers=HX)
    db.expire_all()
    assert db.get(GlossaryTerm, old.id) is None
    assert "Delete this term" not in player.get("/campaign/glossary/%d" % db.scalar(select(GlossaryTerm)).id).text


@pytest.fixture
def dm(monkeypatch, db):
    from app.models import User

    db.add(User(email="dm@example.com", name="Dee", is_dm=True))
    db.flush()
    yield client_for(monkeypatch, db, "dm@example.com")
    app.dependency_overrides.clear()


def test_the_dms_entries_skip_review(dm, player, db):
    from app.models import Recap, Status

    import_bundle(db, BUNDLE)
    e = db.scalar(select(Entity).where(Entity.name == "Kieran"))
    assert "doesn't wait for a reviewer" in dm.get(f"/campaign/{e.id}/peek").text
    assert "Send to a reviewer" in player.get(f"/campaign/{e.id}/peek").text
    # People, places, factions…: straight onto the page, from the panel or the page
    assert "Added to the page" in dm.post(f"/campaign/{e.id}/suggest", data={"kind": "addition", "text": "He sails."}, headers=HX).text
    dm.post(f"/campaign/{e.id}/facts", data={"kind": "addition", "text": "He fishes."}, headers=HX)
    assert [f.status for f in db.scalars(select(Fact).order_by(Fact.id))] == ["merged", "merged"]
    assert "He sails." in player.get(f"/campaign/{e.id}").text
    player.post(f"/campaign/{e.id}/suggest", data={"kind": "addition", "text": "He sings."}, headers=HX)
    assert db.scalar(select(Fact).where(Fact.text == "He sings.")).status == "pending"  # everyone else still waits

    # Sessions: into the next redraft, and shown under the recap until then
    s = db.scalar(select(GameSession))
    db.add(Recap(session_id=s.id, version=1, body="The party met Kiera.", author="ai", status=Status.PUBLISHED))
    db.flush()
    r = dm.post(f"/sessions/{s.id}/suggest", data={"kind": "correction", "text": "It was Kieran, not Kiera."}, headers=HX)
    assert "shows under the recap now" in r.text
    x = db.scalar(select(Suggestion).where(Suggestion.target_type == "session"))
    assert (x.status, x.from_dm) == ("used", True)
    c = db.scalar(select(Correction).where(Correction.session_id == s.id))
    assert (c.kind, c.before, c.after) == ("answer", "Correction from the DM", "It was Kieran, not Kiera.")
    story = player.get("/").text + player.get("/sessions").text
    assert story.count("From the DM") == 2 and story.count(", not Kiera.") == 2  # (Kieran is linked)

    # Glossary: the DM edits and adds terms directly
    term = db.scalar(select(GlossaryTerm).where(GlossaryTerm.term == "Bhal"))
    peek = dm.get(f"/campaign/glossary/{term.id}/peek").text
    assert "Delete this term" in peek and "Suggest a correction" not in peek
    dm.post(f"/campaign/glossary/{term.id}/edit", data={"term": "Bhal", "description": "Big C's father, a god"}, headers=HX)
    assert "Added Womford" in dm.post("/campaign/glossary/add", data={"term": "Womford", "description": "A fishing village"}, headers=HX).text
    assert "Only the DM" in player.post("/campaign/glossary/add", data={"term": "Nope"}, headers=HX).text
    db.expire_all()
    assert db.get(GlossaryTerm, term.id).description == "Big C's father, a god"
    assert {t.term for t in db.scalars(select(GlossaryTerm))} == {"Bhaal", "Bhal", "Womford"}
