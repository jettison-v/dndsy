import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import auth, config, entities
from app.config import parse_allowlist
from app.db import get_db
from app.extraction import _known_world, store_result
from app.importer import import_bundle
from app.main import app
from app.models import Campaign, Entity, ExtractionRun, Fact, GameSession
from app.review import latest_questions, publish

HX = {"HX-Request": "true"}

BUNDLE = {
    "campaign": {"slug": "main", "name": "Main"},
    "entities": [
        {"kind": "npc", "name": "Lillippi Lemon", "summary": "Tiefling bard.", "aliases": ["LL"]},
        {"kind": "place", "name": "Saltmarsh", "summary": "Fishing town."},
    ],
    "glossary": [{"term": "Lillippi", "misheard_as": ["Lollipy"]}],
    "sessions": [{"number": 1, "played_on": "2026-01-10"}, {"number": 2, "played_on": "2026-01-24"}],
}


def login(monkeypatch, db, email, name="Someone"):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com,player@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": email, "email_verified": True, "name": name}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    return c


@pytest.fixture
def admin(monkeypatch, db):
    yield login(monkeypatch, db, "admin@example.com", "Brett")
    app.dependency_overrides.clear()


@pytest.fixture
def player(monkeypatch, db):
    yield login(monkeypatch, db, "player@example.com", "Pat")
    app.dependency_overrides.clear()


def lillippi(db):
    return db.scalar(select(Entity).where(Entity.name == "Lillippi Lemon"))


def published_events(db):
    """Session 2 drafted first (out of order) to prove moments follow the timeline."""
    for number, text in ((2, "Lillippi sang in Saltmarsh."), (1, "The party met Lillippi.")):
        s = db.scalar(select(GameSession).where(GameSession.number == number))
        run = ExtractionRun(session_id=s.id, source="notes", status="done")
        db.add(run)
        db.flush()
        store_result(db, s, run, {
            "title": "", "recap": "Recap.", "events": [{"kind": "event", "text": text, "entities": ["Lillippi"]}],
            "entities": [], "glossary": [], "to_check": [], "relationships": [],
        })
        db.flush()
        db.refresh(s)
        publish(db, s)
    db.flush()


def test_entity_page_shows_moments_in_story_order(player, db):
    import_bundle(db, BUNDLE)
    published_events(db)
    e = lillippi(db)
    page = player.get(f"/campaign/{e.id}").text
    assert "Tiefling bard." in page and "Also known as LL" in page
    assert page.index("The party met Lillippi.") < page.index("Lillippi sang in")
    assert f'href="/campaign/{e.id}"' in player.get("/campaign").text
    assert f'href="/campaign/{e.id}"' in player.get("/").text  # key-moment entity names link to the page
    assert "Regenerate description" not in page  # reviewers only


def test_fact_flow_merge_keeps_summary(player, db, monkeypatch):
    import_bundle(db, BUNDLE)
    e = lillippi(db)
    r = player.post(f"/campaign/{e.id}/facts", data={"text": "She owes Cole 10 gold."}, headers=HX)
    assert "Waiting for a reviewer" in r.text
    fact = db.scalar(select(Fact))
    assert fact.status == "pending" and fact.author_name == "Pat" and fact.author_email == "player@example.com"
    assert player.post(f"/campaign/facts/{fact.id}/merge", headers=HX).status_code == 403
    assert "owes Cole" not in _known_world(db, db.scalar(select(Campaign)))  # pending facts aren't used

    admin = login(monkeypatch, db, "admin@example.com", "Brett")
    page = admin.get(f"/campaign/{e.id}").text
    assert "She owes Cole 10 gold." in page and "Merge" in page
    admin.post(f"/campaign/facts/{fact.id}/merge", headers=HX)
    db.refresh(fact)
    db.refresh(e)
    assert fact.status == "merged"
    assert e.summary == "Tiefling bard."  # merging never rewrites the summary
    assert "Lillippi Lemon: She owes Cole 10 gold." in _known_world(db, db.scalar(select(Campaign)))
    admin.post(f"/campaign/facts/{fact.id}/undo", headers=HX)
    db.refresh(fact)
    assert fact.status == "pending"
    admin.post(f"/campaign/facts/{fact.id}/reject", headers=HX)
    db.refresh(fact)
    assert fact.status == "rejected"
    app.dependency_overrides.clear()


def test_empty_fact_rejected(player, db):
    import_bundle(db, BUNDLE)
    db.commit()  # the failed action rolls back to here (the test's outer transaction still rolls back)
    r = player.post(f"/campaign/{lillippi(db).id}/facts", data={"text": "  "}, headers=HX)
    assert "Write the fact first" in r.headers["HX-Trigger"]
    assert db.scalar(select(Fact)) is None


class FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.response


def fake_claude(summary, seen):
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps({"summary": summary}))],
        usage=SimpleNamespace(input_tokens=300, output_tokens=60, cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )

    def stream(**kwargs):
        seen.append(kwargs)
        return FakeStream(response)

    return lambda: SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))


def test_regenerate_description_accept_and_undo(admin, db, monkeypatch):
    import_bundle(db, BUNDLE)
    published_events(db)
    e = lillippi(db)
    db.add(Fact(entity_id=e.id, text="She owes Cole 10 gold.", status="merged"))
    db.add(Fact(entity_id=e.id, text="Pending rumor.", status="pending"))
    db.flush()
    seen = []
    monkeypatch.setattr(entities.anthropic, "Anthropic", fake_claude("A tiefling bard who owes Cole money.", seen))
    r = admin.post(f"/campaign/{e.id}/description/regenerate", headers=HX)
    assert "A tiefling bard who owes Cole money." in r.text and "Accept" in r.text
    prompt = seen[0]["messages"][0]["content"][0]["text"]
    assert "She owes Cole 10 gold." in prompt and "Pending rumor." not in prompt and "Lillippi sang" in prompt
    assert seen[0]["model"] == "claude-opus-5-5" and seen[0]["fallbacks"] == "default"
    assert seen[0]["output_config"]["effort"] == "medium"
    run = db.scalar(select(ExtractionRun).where(ExtractionRun.source == "entity"))
    assert run.entity_id == e.id and run.session_id is None and run.status == "done" and run.cost_usd > 0
    db.refresh(e)
    assert e.summary == "Tiefling bard."  # nothing changes until accepted

    admin.post(f"/campaign/{e.id}/description/accept", data={"summary": "Edited by Brett."}, headers=HX)
    db.refresh(e)
    assert e.summary == "Edited by Brett." and e.draft_summary is None and e.previous_summary == "Tiefling bard."
    admin.post(f"/campaign/{e.id}/description/undo", headers=HX)
    db.refresh(e)
    assert e.summary == "Tiefling bard." and e.previous_summary is None

    # The entity run shows on the Usage page and doesn't count as a session draft.
    assert "Lillippi Lemon" in admin.get("/admin/usage").text
    s = db.scalar(select(GameSession).where(GameSession.number == 2))
    assert latest_questions(db, s) == []


def test_discard_description(admin, db):
    import_bundle(db, BUNDLE)
    e = lillippi(db)
    e.draft_summary = "Nope."
    db.flush()
    admin.post(f"/campaign/{e.id}/description/discard", headers=HX)
    db.refresh(e)
    assert e.draft_summary is None and e.summary == "Tiefling bard."


def test_mention_suggestions(db):
    import_bundle(db, BUNDLE)
    cid = db.scalar(select(Campaign)).id
    assert entities.mention_suggestions(db, cid, "lil")[0]["name"] == "Lillippi Lemon"
    assert entities.mention_suggestions(db, cid, "lem")[0]["name"] == "Lillippi Lemon"  # any word
    assert entities.mention_suggestions(db, cid, "ll")[0] == {"name": "Lillippi Lemon", "kind": "Person", "via": "LL"}
    # misheard_as on the glossary term "Lillippi" -> the term itself (it isn't an entity name)
    names = [m["name"] for m in entities.mention_suggestions(db, cid, "lollip")]
    assert names == ["Lillippi", "Lillippi Lemon"]  # the spelling, then full names using it
    assert entities.mention_suggestions(db, cid, "salt")[0]["kind"] == "Place"
    assert entities.mention_suggestions(db, cid, "zzz") == []


def test_mentions_endpoint(player, db):
    import_bundle(db, BUNDLE)
    assert player.get("/campaign/mentions", params={"q": "salt"}).json()[0]["name"] == "Saltmarsh"
    assert TestClient(app).get("/campaign/mentions", params={"q": "salt"}).status_code == 401


def test_mention_ranking_prefers_people_and_earlier_matches(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": [
        {"kind": "quest", "name": "Stop the Lich Queen and save Cole's sons", "quest_open": True},
        {"kind": "npc", "name": "The Lich Queen"},
        {"kind": "faction", "name": "The Lich Queen's cult"},
        {"kind": "npc", "name": "The Lich Queen's husband"},
    ]})
    cid = db.scalar(select(Campaign)).id
    names = [x["name"] for x in entities.mention_suggestions(db, cid, "lich")]
    assert names[0] == "The Lich Queen"
    assert names[-1] == "Stop the Lich Queen and save Cole's sons"
    assert entities.mention_suggestions(db, cid, "the lich")[0]["name"] == "The Lich Queen"


def test_linker_links_names_case_sensitively_and_longest_first(db):
    from app.linking import entity_linker

    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": [
        {"kind": "npc", "name": "Anger"},
        {"kind": "npc", "name": "The Lich Queen", "aliases": ["the queen"]},
        {"kind": "faction", "name": "The Lich Queen's cult"},
    ]})
    cid = db.scalar(select(Campaign)).id
    ln = entity_linker(db, cid)
    out = str(ln.text("Anger felt anger. The Lich Queen's cult serves the Lich Queen, the queen."))
    ids = {e.name: e.id for e in db.scalars(select(Entity))}
    assert f'data-entity="{ids["Anger"]}">Anger</a> felt anger.' in out  # the word "anger" isn't linked
    assert f'data-entity="{ids["The Lich Queen\'s cult"]}">The Lich Queen&#39;s cult</a>' in out  # longest wins
    assert f'the <a class="ent" href="/campaign/{ids["The Lich Queen"]}" data-entity="{ids["The Lich Queen"]}">Lich Queen</a>' in out
    assert "the queen." in out and out.count("<a ") == 3  # lowercase descriptive alias not linked
    html = str(ln.html('<p>Anger and <a href="/x">Anger</a></p>'))
    assert html.count("<a ") == 2  # no link nested inside an existing link
    assert str(entity_linker(db, cid, exclude_id=ids["Anger"]).text("Anger")) == "Anger"


def test_peek_fragment(player, db):
    import_bundle(db, BUNDLE)
    published_events(db)
    e = lillippi(db)
    frag = player.get(f"/campaign/{e.id}/peek").text
    assert "<html" not in frag and "Tiefling bard." in frag and "Open full page" in frag
    assert "The party met Lillippi." in frag or "Lillippi sang in" in frag
