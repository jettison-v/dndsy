import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import admin_sessions, auth, config
from app.config import parse_allowlist
from app.db import get_db
from app.extraction import Source, build_messages, store_result
from app.importer import import_bundle
from app.main import app
from app.models import Correction, Entity, ExtractionRun, GameSession, GlossaryTerm, Proposal, Recap, StoryEvent

RESULT = {
    "title": "Devils",
    "recap": "The party fought devils.",
    "events": [{"kind": "event", "text": "Big fight.", "entities": []}],
    "entities": [
        {"name": "Horn Devil", "kind": "creature", "summary": "Stunned.", "aliases": ["horned devil"], "quest_status": "not_a_quest"},
        {"name": "Lillippi Lemon", "kind": "npc", "summary": "Bard who fought devils.", "aliases": ["Lollipy"], "quest_status": "not_a_quest"},
    ],
    "glossary": [{"term": "Hellhound", "description": "Fiery dog", "misheard_as": ["hell hound"]}],
    "to_check": ["Check the imp count.", "Was the potion identified?"],
}
HX = {"HX-Request": "true"}


@pytest.fixture
def client(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("admin@example.com"))
    monkeypatch.setattr(config, "ADMIN_EMAILS", parse_allowlist("admin@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "admin@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    yield c
    app.dependency_overrides.clear()


def drafted_session(db):
    import_bundle(db, {
        "campaign": {"slug": "main", "name": "Main"},
        "entities": [{"kind": "npc", "name": "Lillippi Lemon", "summary": "Tiefling bard."}],
        "sessions": [{"number": 29}],
    })
    s = db.scalar(select(GameSession))
    run = ExtractionRun(session_id=s.id, source="notes", status="done")
    db.add(run)
    db.flush()
    store_result(db, s, run, RESULT)
    db.flush()
    db.expire_all()
    return db.scalar(select(GameSession))


def proposal(db, name):
    return next(p for p in db.scalars(select(Proposal)) if p.payload.get("name") == name or p.payload.get("term") == name)


def test_review_list_and_draft_button(client, db, monkeypatch):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": 29}]})
    page = client.get("/admin/sessions").text
    assert "Session 29" in page and "Not drafted" in page
    started = []
    monkeypatch.setattr(admin_sessions, "_draft_in_background", lambda ids: started.append(ids) or True)
    sid = db.scalar(select(GameSession)).id
    r = client.post("/admin/sessions/draft", data={"session_ids": [sid]}, follow_redirects=False)
    assert started == [[sid]] and r.headers["location"] == f"/admin/sessions/{sid}"


def test_review_page_shows_draft(client, db):
    s = drafted_session(db)
    page = client.get(f"/admin/sessions/{s.id}").text
    assert "The party fought devils." in page
    assert "Check the imp count." in page and "2 to answer" in page
    assert "Horn Devil" in page and "Hellhound" in page
    assert "Publish to the table" in page


def test_answer_skip_reopen_and_redraft_prompt(client, db, monkeypatch):
    s = drafted_session(db)
    r = client.post(f"/admin/sessions/{s.id}/questions/answer", data={"q": "Check the imp count.", "answer": "Two imps.", "remember": "1"}, headers=HX)
    assert '"toast": "Answer saved"' in r.headers["HX-Trigger"]
    assert 'id="review"' in r.text and "1 to answer" in r.text and "Done (1)" in r.text
    assert "1 new answer" in r.text  # redraft prompt
    r = client.post(f"/admin/sessions/{s.id}/questions/skip", data={"q": "Was the potion identified?"}, headers=HX)
    assert "All questions handled" in r.text and "Skipped" in r.text

    text = " ".join(b.get("text", "") for b in build_messages(db, s, Source("notes", "x"))[0]["content"])
    assert "Two imps." in text  # answer reaches Claude
    assert "Was the potion identified?" not in text  # skips don't

    client.post(f"/admin/sessions/{s.id}/questions/reopen", data={"q": "Check the imp count."}, headers=HX)
    assert db.scalar(select(Correction).where(Correction.kind == "answer")) is None

    started = []
    monkeypatch.setattr(admin_sessions, "_draft_in_background", lambda ids: started.append(ids) or True)
    client.post(f"/admin/sessions/{s.id}/redraft", headers=HX)
    assert started == [[s.id]]


def test_edit_recap_and_publish_records_correction(client, db):
    s = drafted_session(db)
    client.post(f"/admin/sessions/{s.id}/recap", data={"body": "The party fought three devils.", "note": "Count the devils", "standing": "1"}, headers=HX)
    r = client.post(f"/admin/sessions/{s.id}/publish", headers=HX)
    assert "Published ✓" in r.text
    db.expire_all()
    recaps = list(db.scalars(select(Recap).order_by(Recap.version)))
    assert [(x.author, x.status.value) for x in recaps] == [("ai", "draft"), ("brett", "published")]
    c = db.scalar(select(Correction).where(Correction.kind == "edit"))
    assert (c.after, c.note, c.standing_instruction) == ("The party fought three devils.", "Count the devils", True)
    r = client.post(f"/admin/sessions/{s.id}/recap", data={"body": "Changed again."}, headers=HX)
    assert "Edited since publishing" in r.text and "Publish changes" in r.text


def test_key_moments_edit_add_delete(client, db):
    s = drafted_session(db)
    ev = db.scalar(select(StoryEvent))
    client.post(f"/admin/sessions/{s.id}/events", data={"event_id": ev.id, "kind": "reveal", "text": "A huge fight."}, headers=HX)
    client.post(f"/admin/sessions/{s.id}/events", data={"kind": "decision", "text": "They rested."}, headers=HX)
    db.expire_all()
    events = list(db.scalars(select(StoryEvent).order_by(StoryEvent.position)))
    assert [(e.kind.value, e.text) for e in events] == [("reveal", "A huge fight."), ("decision", "They rested.")]
    client.post(f"/admin/sessions/{s.id}/events/{events[0].id}/delete", headers=HX)
    db.expire_all()
    assert [e.text for e in db.scalars(select(StoryEvent))] == ["They rested."]


def test_accept_edit_and_undo_existing_entity(client, db):
    drafted_session(db)
    p = proposal(db, "Lillippi Lemon")
    r = client.post(f"/admin/proposals/{p.id}/accept", headers=HX)
    assert "Now in askdnd" in r.text
    lil = db.scalar(select(Entity).where(Entity.name == "Lillippi Lemon"))
    assert lil.summary == "Bard who fought devils." and [a.alias for a in lil.aliases] == ["Lollipy"]

    client.post(f"/admin/proposals/{p.id}/edit", data={"summary": "Bard; fought devils in the cave."}, headers=HX)
    db.expire_all()
    assert db.get(Entity, lil.id).summary == "Bard; fought devils in the cave."

    client.post(f"/admin/proposals/{p.id}/undo", headers=HX)
    db.expire_all()
    lil = db.get(Entity, lil.id)
    assert lil.summary == "Tiefling bard." and lil.aliases == []  # back to before
    assert db.get(Proposal, p.id).status == "pending"


def test_accept_with_edit_then_undo_new_entity_and_glossary(client, db):
    drafted_session(db)
    devil, hound = proposal(db, "Horn Devil"), proposal(db, "Hellhound")
    client.post(f"/admin/proposals/{devil.id}/accept", data={"summary": "Stunned by No Name."}, headers=HX)
    client.post(f"/admin/proposals/{hound.id}/accept", headers=HX)
    db.expire_all()
    assert db.scalar(select(Entity).where(Entity.name == "Horn Devil")).summary == "Stunned by No Name."
    assert db.scalar(select(GlossaryTerm)).term == "Hellhound"
    client.post(f"/admin/proposals/{devil.id}/undo", headers=HX)
    client.post(f"/admin/proposals/{hound.id}/undo", headers=HX)
    db.expire_all()
    assert db.scalar(select(Entity).where(Entity.name == "Horn Devil")) is None
    assert db.scalar(select(GlossaryTerm)) is None


def test_reject_and_undo(client, db):
    drafted_session(db)
    p = proposal(db, "Horn Devil")
    r = client.post(f"/admin/proposals/{p.id}/reject", headers=HX)
    assert "Rejected" in r.text and "1 rejected" in r.text
    client.post(f"/admin/proposals/{p.id}/undo", headers=HX)
    db.expire_all()
    assert db.get(Proposal, p.id).status == "pending"


def test_double_accept_is_refused(client, db):
    drafted_session(db)
    p = proposal(db, "Horn Devil")
    client.post(f"/admin/proposals/{p.id}/accept", headers=HX)
    r = client.post(f"/admin/proposals/{p.id}/accept", headers=HX)
    assert "already decided" in r.headers["HX-Trigger"]


def test_public_pages_show_only_published(client, db):
    s = drafted_session(db)
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "entities": [{"kind": "quest", "name": "Reach the library", "quest_open": True}]})
    assert "Nothing published yet" in client.get("/").text
    client.post(f"/admin/sessions/{s.id}/publish", headers=HX)
    home = client.get("/").text
    assert "The party fought devils." in home and "Big fight." in home and "Reach the library" in home
    assert "The party fought devils." in client.get("/sessions").text
    campaign = client.get("/campaign").text
    assert "Lillippi Lemon" in campaign and "Reach the library" in campaign
    assert '<span class="count">1 open</span>' in campaign and '<main class="page sheet wide">' in campaign
    assert '<main class="page wide">' in home and '<aside class="session-side">' in home
    assert client.get("/characters").status_code == 200


def test_player_cannot_open_admin_review(monkeypatch, db):
    monkeypatch.setattr(config, "ALLOWED_EMAILS", parse_allowlist("player@example.com"))
    app.dependency_overrides[get_db] = lambda: db
    c = TestClient(app)

    async def token(request):
        return {"userinfo": {"email": "player@example.com", "email_verified": True}}

    monkeypatch.setattr(auth.oauth.google, "authorize_access_token", token)
    c.get("/auth/callback", follow_redirects=False)
    assert c.get("/admin/sessions").status_code == 403
    assert "Manage" not in c.get("/").text
    app.dependency_overrides.clear()


def test_next_session_button(client, db):
    s = drafted_session(db)
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [{"number": 30}]})
    page = client.get(f"/admin/sessions/{s.id}").text
    assert "Next: Session 30" in page
    assert "Draft next session" not in page  # no synced notes for session 30 in this test


def test_publishing_drafts_the_next_session_and_late_duplicates_join_the_entry(client, db, monkeypatch):
    """Brett, 2026-10-22: the notes backlog goes one at a time. Publishing starts the next draft; a "new" entry
    suggested again by a later draft adds to the entry made since, instead of a duplicate."""
    from app.models import Fact

    s29 = drafted_session(db)
    s30 = GameSession(campaign_id=s29.campaign_id, number=30, source="notes")
    db.add(s30)
    db.flush()
    started = []
    monkeypatch.setattr(admin_sessions, "_draft_in_background", lambda ids: started.append(ids) or True)
    r = client.post(f"/admin/sessions/{s29.id}/publish", headers=HX)  # locally, automatic drafting is off
    assert started == [] and "Automatic drafting is off here" in r.headers["HX-Trigger"]
    monkeypatch.setattr(config, "AUTO_DRAFT", True)  # as on beta
    r = client.post(f"/admin/sessions/{s29.id}/publish", headers=HX)
    assert started == [[s30.id]] and "drafting Session 30 next" in r.headers["HX-Trigger"]

    late = Proposal(session_id=s30.id, kind="entity", payload={"entity_id": None, "name": "Horn Devil", "kind": "creature",
                                                                "old_summary": "", "summary": "Fled to the sea cave.", "new_aliases": ["horny"]})
    db.add(late)
    db.flush()
    client.post(f"/admin/proposals/{proposal(db, 'Horn Devil').id}/accept", headers=HX)  # session 29's: creates it
    client.post(f"/admin/proposals/{late.id}/accept", headers=HX)  # session 30's: joins it
    db.expire_all()
    devils = list(db.scalars(select(Entity).where(Entity.name == "Horn Devil")))
    assert len(devils) == 1 and devils[0].summary == "Stunned."  # kept, not replaced
    assert "Fled to the sea cave." in [f.text for f in db.scalars(select(Fact).where(Fact.entity_id == devils[0].id))]
    assert "horny" in [a.alias for a in devils[0].aliases]
    client.post(f"/admin/proposals/{late.id}/undo", headers=HX)
    db.expire_all()
    assert db.scalar(select(Fact).where(Fact.text == "Fled to the sea cave.")) is None  # Undo takes the fact back


def test_the_dms_words_are_kept(client, db):
    """Content workflows step 3: who wrote each description and recap is recorded; Claude's updates to a person's
    words are asked to keep them and arrive as marked-up edits; a stale update can't overwrite a newer edit."""
    from app import entities
    from app.render import word_diff

    assert str(word_diff("She owes Cole.", "She owes Cole 10 gold.")) == "She owes Cole <ins>10 gold</ins>."

    s = drafted_session(db)
    lil = db.scalar(select(Entity).where(Entity.name == "Lillippi Lemon"))
    assert lil.written_by_person == ""  # imported
    accept = proposal(db, "Lillippi Lemon")
    client.post(f"/admin/proposals/{accept.id}/accept", headers=HX)
    db.expire_all()
    assert db.get(Entity, lil.id).summary_by == "claude"
    client.post(f"/admin/proposals/{accept.id}/undo", headers=HX)
    db.expire_all()
    assert db.get(Entity, lil.id).summary_by == ""

    # The DM writes the description: Claude is told to keep it, and the update shows as a marked-up edit
    client.post(f"/campaign/{lil.id}/description", data={"summary": "A tiefling bard with a silver lute."}, headers=HX)
    db.expire_all()
    lil = db.get(Entity, lil.id)
    assert lil.written_by_person
    world = build_messages(db, s, Source("notes", "x"))[0]["content"][0]["text"]
    assert "Lillippi Lemon [npc] (written by " in world and "keep their wording" in world
    run = ExtractionRun(session_id=s.id, source="notes", status="done")
    db.add(run)
    db.flush()
    store_result(db, s, run, {**RESULT, "entities": [{**RESULT["entities"][1], "summary": "A tiefling bard with a silver lute, who fought devils."}]})
    db.flush()
    p = proposal(db, "Lillippi Lemon")
    assert p.payload["written_by"] == lil.written_by_person and p.payload["old_summary"] == "A tiefling bard with a silver lute."
    page = client.get(f"/admin/sessions/{s.id}").text
    assert "Keeps " in page and "lute<ins>, who fought devils</ins>." in page

    # Edited since the draft: accepting is refused until combined by hand
    entities.set_description(lil, "A tiefling bard.", by="Dee")
    db.commit()  # the refused accept below rolls back whatever wasn't committed
    r = client.post(f"/admin/proposals/{p.id}/accept", headers=HX)
    assert "changed since this draft" in r.text
    client.post(f"/admin/proposals/{p.id}/accept", data={"summary": "A tiefling bard who fought devils."}, headers=HX)
    db.expire_all()
    assert (db.get(Entity, lil.id).summary, db.get(Proposal, p.id).status) == ("A tiefling bard who fought devils.", "accepted")
    assert db.get(Entity, lil.id).written_by_person  # the edit made it theirs

    # Recaps: the redraft is asked to keep the person's recap, shown marked up, and they can keep theirs
    client.post(f"/admin/sessions/{s.id}/recap", data={"body": "We fought **devils** at the gate."}, headers=HX)
    db.expire_all()
    s = db.get(GameSession, s.id)
    assert s.recaps[-1].author_name
    prompt = "".join(b["text"] for b in build_messages(db, s, Source("notes", "x"))[0]["content"] if b["type"] == "text")
    assert "<current_recap written_by=" in prompt and "We fought **devils** at the gate." in prompt
    run = ExtractionRun(session_id=s.id, source="notes", status="done")
    db.add(run)
    db.flush()
    store_result(db, s, run, {**RESULT, "recap": "We fought **devils** at the north gate."})
    db.commit()
    db.expire_all()
    page = client.get(f"/admin/sessions/{s.id}").text
    assert "Claude redrafted" in page and "<ins>north</ins>" in page and "/recap/keep-mine" in page
    client.post(f"/admin/sessions/{s.id}/recap/keep-mine", headers=HX)
    db.expire_all()
    s = db.get(GameSession, s.id)
    assert s.recaps[-1].body == "We fought **devils** at the gate." and s.recaps[-1].author == "brett"
    assert "Claude redrafted" not in client.get(f"/admin/sessions/{s.id}").text
