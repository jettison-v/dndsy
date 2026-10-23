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
from app.models import Campaign, Entity, ExtractionRun, Fact, GameSession, User
from app.review import latest_questions, publish
from tests.roles import set_role

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
    r = player.get(f"/campaign/{e.id}", follow_redirects=False)  # an old address: to the campaign's own
    assert r.status_code == 307 and r.headers["location"] == f"/c/main/campaign/{e.id}"
    r = player.get(f"/c/main/campaign/{e.id}", follow_redirects=False)  # no full page: the Campaign page opens its panel
    assert r.status_code == 303 and r.headers["location"] == f"/c/main/campaign?open={e.id}"
    page = player.get(f"/campaign/{e.id}/peek").text  # everything is in the side panel now
    assert "Tiefling bard." in page and "Also: LL" in page
    assert page.index("The party met Lillippi.") < page.index("Lillippi sang in")
    assert f'href="/c/main/campaign?open={e.id}"' in player.get("/campaign").text  # its name in the Reader's list
    assert f'href="/campaign/{e.id}"' in player.get("/").text  # key-moment entity names link to the page
    assert "/edit" not in page and player.get(f"/campaign/{e.id}/edit").status_code == 403  # editing: the DM, reviewers, admins


def test_fact_flow_merge_keeps_summary(player, db, monkeypatch):
    import_bundle(db, BUNDLE)
    e = lillippi(db)
    r = player.post(f"/campaign/{e.id}/facts?in=panel", data={"text": "She owes Cole 10 gold."}, headers=HX)
    assert "Your suggestions here" in r.text and 'tag draft">Waiting<' in r.text
    fact = db.scalar(select(Fact))
    assert fact.status == "pending" and fact.author_name == "Pat" and fact.author_email == "player@example.com"
    assert player.post(f"/campaign/facts/{fact.id}/merge", headers=HX).status_code == 403
    assert "owes Cole" not in _known_world(db, db.scalar(select(Campaign)))  # pending facts aren't used

    admin = login(monkeypatch, db, "admin@example.com", "Brett")
    page = admin.get(f"/campaign/{e.id}/edit").text
    assert "She owes Cole 10 gold." in page and "Merge" in page
    assert "She owes Cole 10 gold." in admin.get(f"/campaign/{e.id}/peek").text  # and in the side panel
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


def fake_claude(summary, seen, used=None):
    out = {"summary": summary} if used is None else {"summary": summary, "used_fact_ids": used}
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text=json.dumps(out))],
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
    assert f'data-entity="{ids["Anger"]}">Anger&#39;s</a> sword' in str(ln.text("Anger's sword"))  # possessive is part of the link
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
    assert "<html" not in frag and "Tiefling bard." in frag and "Open full page" not in frag
    assert "The party met Lillippi." in frag and "Lillippi sang in" in frag  # every key moment
    assert f'hx-post="/campaign/{e.id}/facts?in=panel"' in frag  # adding a fact answers with the panel


def test_misspellings_hidden_but_still_matched(admin, db):
    from app.extraction import _known_world
    from app.linking import entity_linker

    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": [
        {"kind": "npc", "name": "Bhal", "aliases": [{"alias": "Bhaal", "misspelling": True}, "Fire Lord"]}]})
    e = db.scalar(select(Entity).where(Entity.name == "Bhal"))
    assert [a.alias for a in e.display_aliases] == ["Fire Lord"]
    page = admin.get(f"/campaign/{e.id}/edit").text
    assert "Also known as Fire Lord" in page and "Mark as other name" in page
    cid = e.campaign_id
    assert f'data-entity="{e.id}">Bhaal</a>' in str(entity_linker(db, cid).text("Bhaal returned."))
    assert entities.mention_suggestions(db, cid, "bhaa")[0]["name"] == "Bhal"
    world = _known_world(db, db.get(Campaign, cid))
    assert "Also: Fire Lord." in world and "Often misspelled: Bhaal." in world

    # Re-import flips the flag; reviewers can toggle and remove
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": [
        {"kind": "npc", "name": "Bhal", "aliases": [{"alias": "Fire Lord", "misspelling": True}]}]})
    db.expire_all()
    assert db.scalar(select(Entity).where(Entity.name == "Bhal")).display_aliases == []
    alias = next(a for a in db.scalar(select(Entity).where(Entity.name == "Bhal")).aliases if a.alias == "Bhaal")
    admin.post(f"/campaign/{e.id}/aliases/{alias.id}/toggle", headers={"HX-Request": "true"})
    admin.post(f"/campaign/{e.id}/aliases", data={"alias": "Bael", "misspelling": "1"}, headers={"HX-Request": "true"})
    db.expire_all()
    e = db.get(Entity, e.id)
    assert sorted((a.alias, a.misspelling) for a in e.aliases) == [("Bael", True), ("Bhaal", False), ("Fire Lord", True)]


def test_the_dm_edits_entries_directly_and_marks_facts_done(monkeypatch, db):
    """Brett, 2026-10-22: DMs edit names and descriptions without Claude; a fact can be marked Done."""
    from tests.test_suggestions import client_for

    import_bundle(db, BUNDLE)
    e = lillippi(db)
    set_role(db, "dm@example.com")
    dm = client_for(monkeypatch, db, "dm@example.com")
    assert dm.get(f"/campaign/{e.id}/edit").status_code == 200
    r = dm.post(f"/campaign/{e.id}/description", data={"summary": "A tiefling bard who owes nobody."}, headers=HX)
    assert "Description saved" in r.headers["HX-Trigger"]
    dm.post(f"/campaign/{e.id}/name", data={"name": "Lillippi"}, headers=HX)
    db.refresh(e)
    assert e.summary == "A tiefling bard who owes nobody." and e.previous_summary == "Tiefling bard."
    assert e.name == "Lillippi" and "Lillippi Lemon" in [a.alias for a in e.aliases]  # the old name still links
    r = dm.post(f"/campaign/{e.id}/facts?in=panel", data={"text": "She sings sea shanties."}, headers=HX)
    assert "She sings sea shanties." in r.text and 'id="peek-title"' in r.text  # the panel, updated in place
    fact = db.scalar(select(Fact))
    r = dm.post(f"/campaign/facts/{fact.id}/done?in=panel", headers=HX)
    db.refresh(fact)
    assert fact.status == "done" and "Done (1)" in r.text
    dm.post(f"/campaign/facts/{fact.id}/undo?in=panel", headers=HX)
    db.refresh(fact)
    assert fact.status == "merged"  # Undo puts it back on the list


def test_accepting_a_regenerated_description_takes_used_facts_off_the_list(db):
    import_bundle(db, BUNDLE)
    e = lillippi(db)
    used = entities.add_fact(db, e, "She owes Cole 10 gold.", {"email": "a@x"}, merged=True)
    kept = entities.add_fact(db, e, "Her lute is cursed.", {"email": "a@x"}, merged=True)
    db.flush()
    seen = []
    entities.regenerate(db, e, client_factory=fake_claude("A tiefling bard in debt to Cole.", seen, used=[used.id, 999]))
    assert e.draft_fact_ids == [used.id]  # only facts that exist and are on the page
    assert f"[fact {used.id}]" in seen[0]["messages"][0]["content"][0]["text"]
    entities.accept_description(e)
    db.flush()
    from app import history

    history.mark("edit")  # accept_description marks its changes as Claude's; outside a request that would linger
    assert (used.status, kept.status) == ("done", "merged") and e.draft_fact_ids is None


def test_dm_tools_create_tidy_and_add_moments(monkeypatch, db):
    """Content workflows step 1 (docs/plans/2026-10-22-content-workflows.md): the DM writes the canon by hand."""
    from tests.test_suggestions import client_for

    import_bundle(db, BUNDLE)
    set_role(db, "dm@example.com")
    dm = client_for(monkeypatch, db, "dm@example.com")
    assert "+ New entry" in dm.get("/campaign").text and "New entry" in dm.get("/campaign/new?kind=place").text
    r = dm.post("/campaign/new", data={"kind": "npc", "name": "Captain Trager Grill", "summary": "Cult-marked captain."}, headers=HX)
    grill = db.scalar(select(Entity).where(Entity.name == "Captain Trager Grill"))
    assert r.headers["HX-Redirect"] == f"/c/main/campaign?open={grill.id}" and grill.status.value == "published"
    again = dm.post("/campaign/new", data={"kind": "npc", "name": "lillippi lemon"}, headers=HX).text
    assert "already in the campaign record" in again  # by name or other name, any case
    dm.post("/campaign/new", data={"kind": "quest", "name": "Find the bell", "hidden": "1"}, headers=HX)
    bell = db.scalar(select(Entity).where(Entity.name == "Find the bell"))
    assert bell.status.value == "draft" and bell.quest_open is True and "Hidden" in dm.get("/campaign").text

    dm.post(f"/campaign/{bell.id}/details", data={"kind": "quest", "quest_open": "done", "published": "1"}, headers=HX)
    db.refresh(bell)
    assert bell.quest_open is False and bell.status.value == "published"

    s1 = db.scalar(select(GameSession).where(GameSession.number == 1))
    dm.post(f"/campaign/{grill.id}/moments", data={"session_id": s1.id, "kind": "reveal", "text": "Grill bore the mark of the cult."}, headers=HX)
    assert "Grill bore the mark of the cult." in dm.get(f"/campaign/{grill.id}/peek").text

    dup = entities.create(db, grill.campaign_id, "npc", "Capt Trager Grill", "A captain on the road.")
    entities.add_fact(db, dup, "He carries a silver whistle.", {"email": "p@x"}, merged=True)
    db.commit()
    r = dm.post(f"/campaign/{dup.id}/merge", data={"into": grill.id}, headers=HX)
    assert r.headers["HX-Redirect"] == f"/c/main/campaign?open={grill.id}"
    db.expire_all()
    grill = db.get(Entity, grill.id)
    assert db.scalar(select(Entity).where(Entity.name == "Capt Trager Grill")) is None
    assert "Capt Trager Grill" in [a.alias for a in grill.aliases]  # links and transcripts still find it
    facts = [f.text for f in db.scalars(select(Fact).where(Fact.entity_id == grill.id))]
    assert "He carries a silver whistle." in facts and any("A captain on the road." in t for t in facts)  # nothing lost

    r = dm.post(f"/campaign/{bell.id}/delete", headers=HX)
    assert r.headers["HX-Redirect"] == "/campaign" and db.get(Entity, bell.id) is None


def test_player_characters_cant_be_deleted_or_merged_away(db):
    from app import characters
    from app.models import Character

    import_bundle(db, BUNDLE)
    e = lillippi(db)
    ch = Character(name=e.name)
    db.add(ch)
    characters.join(db, ch, e)
    other = db.scalar(select(Entity).where(Entity.name == "Saltmarsh"))
    with pytest.raises(entities.EntityError, match="player character"):
        entities.delete(db, e)
    with pytest.raises(entities.EntityError, match="player character"):
        entities.merge(db, e, other)
