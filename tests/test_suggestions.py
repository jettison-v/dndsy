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
from tests.roles import set_role

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
    assert "The DM or a reviewer will take a look" in r.text
    f = db.scalar(select(Fact))
    assert (f.kind, f.status, f.author_name) == ("correction", "pending", "Mark")
    f.status = "merged"
    db.flush()
    text = build_describe_messages(db, e)[0]["content"][0]["text"]
    assert "Correction: He is Cole's father, not uncle." in text
    assert f'hx-post="/campaign/{e.id}/facts?in=panel"' in player.get(f"/campaign/{e.id}/peek").text  # add one from the panel


def test_session_suggestion_flows_to_review_and_redraft(player, admin, db):
    import_bundle(db, BUNDLE)
    s = db.scalar(select(GameSession))
    player.post(f"/sessions/{s.id}/suggest", data={"kind": "correction", "text": "Kieran, not Kiera."}, headers=HX)
    assert "1 suggestion or draft waiting for your OK" in admin.get("/manage/sessions").text
    page = admin.get("/suggestions").text
    assert "Kieran, not Kiera." in page and "Edit the recap" in page and "I fixed it" in page
    x = db.scalar(select(Suggestion))
    admin.post(f"/admin/suggestions/{x.id}/use")
    db.expire_all()
    assert db.get(Suggestion, x.id).status == "used"
    c = db.scalar(select(Correction).where(Correction.session_id == s.id))
    assert (c.kind, c.after) == ("answer", "Kieran, not Kiera.") and "Correction from" in c.before
    assert "Kieran, not Kiera." not in admin.get("/suggestions").text  # handled, so gone from the list


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

    set_role(db, "dm@example.com")
    yield client_for(monkeypatch, db, "dm@example.com")
    app.dependency_overrides.clear()


def test_the_dms_entries_skip_review(dm, player, db):
    from app.models import Recap, Status

    import_bundle(db, BUNDLE)
    e = db.scalar(select(Entity).where(Entity.name == "Kieran"))
    assert "so it goes straight on." in dm.get(f"/campaign/{e.id}/peek").text
    assert "The DM or a reviewer adds it." in player.get(f"/campaign/{e.id}/peek").text
    # People, places, factions…: straight onto the page, from the panel or the page
    assert "Added to the page" in dm.post(f"/campaign/{e.id}/suggest", data={"kind": "addition", "text": "He sails."}, headers=HX).text
    dm.post(f"/campaign/{e.id}/facts", data={"kind": "addition", "text": "He fishes."}, headers=HX)
    assert [f.status for f in db.scalars(select(Fact).order_by(Fact.id))] == ["merged", "merged"]
    assert "He sails." in player.get(f"/campaign/{e.id}/peek").text
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
    story = player.get("/").text  # Previously on… and All sessions, one page
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


def test_suggestions_go_to_the_dm_and_admins(dm, player, db):
    import_bundle(db, BUNDLE)
    e = db.scalar(select(Entity).where(Entity.name == "Kieran"))
    s = db.scalar(select(GameSession))
    player.post(f"/campaign/{e.id}/suggest", data={"kind": "addition", "text": "He sails."}, headers=HX)
    player.post(f"/sessions/{s.id}/suggest", data={"kind": "correction", "text": "Kieran, not Kiera."}, headers=HX)
    assert player.get("/c/main/manage/inbox", follow_redirects=False).headers["location"] == "/your-suggestions"
    assert "Manage" not in player.get("/").text
    home = dm.get("/").text
    assert "2 suggestions or drafts are waiting" in home and 'href="/c/main/manage/inbox"' in home
    page = dm.get("/suggestions").text
    assert "He sails." in page and "Kieran, not Kiera." in page
    fact = db.scalar(select(Fact))
    dm.post(f"/suggestions/facts/{fact.id}/merge")
    x = db.scalar(select(Suggestion))
    dm.post(f"/admin/suggestions/{x.id}/use")
    db.expire_all()
    assert db.get(Fact, fact.id).status == "merged" and db.get(Suggestion, x.id).status == "used"
    assert "Nothing waiting from the table" in dm.get("/suggestions").text
    # A player can't decide on suggestions
    player.post(f"/campaign/{e.id}/suggest", data={"kind": "addition", "text": "He sings."}, headers=HX)
    sings = db.scalar(select(Fact).where(Fact.text == "He sings."))
    player.post(f"/suggestions/facts/{sings.id}/merge")
    player.post(f"/campaign/facts/{sings.id}/merge", headers=HX)
    db.expire_all()
    assert db.get(Fact, sings.id).status == "pending"
    dm.post(f"/campaign/facts/{sings.id}/reject", headers=HX)  # the DM can also decide on the entry's own page
    db.expire_all()
    assert db.get(Fact, sings.id).status == "rejected"


def test_one_inbox_same_actions_and_players_see_the_outcome(dm, player, db, monkeypatch):
    """Content workflows step 2: Accept · Edit · Ask Claude to work it in · Dismiss, and Waiting / Added / Used / Not used."""
    from app import admin_sessions, entities
    from app.models import Recap, Status

    import_bundle(db, BUNDLE)
    e = db.scalar(select(Entity).where(Entity.name == "Kieran"))
    s = db.scalar(select(GameSession))
    s.source = "notes"
    db.add(Recap(session_id=s.id, version=1, body="The party met Kiera.", author="ai", status=Status.PUBLISHED))
    for text in ("He sails.", "He sings.", "He fishes.", "He hums."):
        r = player.post(f"/campaign/{e.id}/suggest", data={"kind": "addition", "text": text}, headers=HX)
    assert 'href="/your-suggestions"' in r.text
    player.post(f"/sessions/{s.id}/suggest", data={"kind": "correction", "text": "Kieran, not Kiera."}, headers=HX)
    player.post("/campaign/glossary/suggest", data={"text": "Womford is a fishing village."}, headers=HX)
    fact = {f.text: f for f in db.scalars(select(Fact))}

    page = dm.get("/suggestions").text
    assert page.count("/claude\"") == 5 and "Add the term" in page and "Sessions to review" in page

    dm.post(f"/suggestions/facts/{fact['He sails.'].id}/accept")
    dm.post(f"/suggestions/facts/{fact['He sings.'].id}/edit", data={"text": "He sings sea shanties."})
    dm.post(f"/suggestions/facts/{fact['He hums.'].id}/dismiss")

    def fake_regenerate(db, entity):
        entity.draft_summary = "Cole's father, a sailor who fishes."
        entity.draft_fact_ids = [fact["He fishes."].id]
        db.commit()
        return entity.draft_summary
    monkeypatch.setattr(entities, "regenerate", fake_regenerate)
    dm.post(f"/suggestions/facts/{fact['He fishes.'].id}/claude")
    page = dm.get("/suggestions").text
    assert "Claude's drafts to check" in page and f'data-modal-url="/campaign/{e.id}/edit"' in page
    dm.post(f"/campaign/{e.id}/description/accept", headers=HX)

    started = []
    monkeypatch.setattr(admin_sessions, "_draft_in_background", lambda ids: started.append(ids) or True)
    x = db.scalar(select(Suggestion).where(Suggestion.target_type == "session"))
    dm.post(f"/admin/suggestions/{x.id}/claude")
    assert started == [[s.id]]
    g = db.scalar(select(Suggestion).where(Suggestion.target_type == "glossary"))
    dm.post(f"/admin/suggestions/{g.id}/glossary", data={"term": "Womford", "description": "A fishing village", "misheard_as": "Wombford"})

    db.expire_all()
    assert [db.get(Fact, fact[t].id).status for t in ("He sails.", "He sings.", "He fishes.", "He hums.")] == ["merged", "merged", "done", "rejected"]
    assert db.get(Fact, fact["He sings."].id).text == "He sings sea shanties."
    assert db.scalar(select(Correction).where(Correction.session_id == s.id)).after == "Kieran, not Kiera."
    assert db.scalar(select(GlossaryTerm).where(GlossaryTerm.term == "Womford")).misheard_as == ["Wombford"]
    assert "Nothing waiting from the table" in dm.get("/suggestions").text

    mine = player.get("/your-suggestions").text
    assert (mine.count(">Added</span>"), mine.count(">Used</span>"), mine.count(">Not used</span>")) == (3, 2, 1)
    peek = player.get(f"/campaign/{e.id}/peek").text
    assert "Your suggestions here" in peek and ">Not used<" in peek and "He hums." in peek
    assert "Your suggestions here" not in dm.get(f"/campaign/{e.id}/peek").text
