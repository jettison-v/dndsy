import json
from types import SimpleNamespace

from sqlalchemy import select

from app import extraction
from app.extraction import Source, extract_session, split_notes, store_result
from app.importer import import_bundle
from app.models import Entity, ExtractionRun, GameSession, Proposal, Recap, StoryEvent

BUNDLE = {
    "campaign": {"slug": "main", "name": "Main", "dm_name": "Mary"},
    "entities": [
        {"kind": "pc", "name": "No Name", "aliases": ["Sarkas"], "character": {"player_name": "Tim"}},
        {"kind": "npc", "name": "Lillippi Lemon", "summary": "Tiefling bard.", "aliases": ["LL"]},
        {"kind": "place", "name": "The Leviathan", "summary": "Huge ship.", "aliases": ["Leviathan"]},
    ],
    "glossary": [{"term": "Lillippi Lemon", "misheard_as": ["Lollipy"]}],
    "sessions": [{"number": 28, "title": "Shipwreck"}, {"number": 29}],
}

RESULT = {
    "title": "Devils in the sea cave",
    "recap": "The party fought devils in a sea cave.",
    "events": [
        {"kind": "event", "text": "Lillippi bloodied an imp.", "entities": ["LL", "Imp"]},
        {"kind": "theory", "text": "The locket may hold the captain's lost love.", "entities": []},
    ],
    "entities": [
        {"name": "Lillippi", "kind": "npc", "summary": "Tiefling bard.", "aliases": ["Lollipy"], "quest_status": "not_a_quest"},
        {"name": "Leviathan", "kind": "place", "summary": "Huge ship.", "aliases": [], "quest_status": "not_a_quest"},
        {"name": "Horn Devil", "kind": "creature", "summary": "Stunned by No Name.", "aliases": [], "quest_status": "not_a_quest"},
    ],
    "glossary": [{"term": "Lillippi Lemon", "description": "", "misheard_as": []}, {"term": "Hellhound", "description": "", "misheard_as": []}],
    "to_check": ["Was the potion identified?"],
}


def setup(db):
    import_bundle(db, BUNDLE)
    return db.scalar(select(GameSession).where(GameSession.number == 29))


class FakeStream:
    def __init__(self, response):
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return self.response


def fake_client(result=RESULT, stop_reason="end_turn", seen=None):
    response = SimpleNamespace(
        stop_reason=stop_reason,
        stop_details=SimpleNamespace(category="cyber"),
        model="claude-opus-5-5",
        content=[SimpleNamespace(type="text", text=json.dumps(result))],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500, cache_creation_input_tokens=0, cache_read_input_tokens=0),
    )

    def stream(**kwargs):
        if seen is not None:
            seen.append(kwargs)
        return FakeStream(response)

    return lambda: SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(stream=stream)))


def test_split_notes_sections_and_background():
    text = "# Notes\n##### General\n- house\n###### Session 17\n- a\n###### Session 18 (1/2/25)\n- b\n###### Sub topic\n- c\n##### Side Quests\n- egg"
    bg, secs = split_notes(text)
    assert sorted(secs) == [17, 18]
    assert "- c" in secs[18] and "egg" not in secs[18]
    assert "house" in bg and "egg" in bg


def test_extraction_stores_drafts_and_proposals(db):
    session = setup(db)
    seen = []
    run = extract_session(db, session, Source("notes", "###### Session 29\n- fought devils"), fake_client(seen=seen))
    assert run.status == "done", run.error
    assert run.cost_usd == round((1000 * 4 + 500 * 20) / 1e6, 4)
    assert run.to_check == ["Was the potion identified?"]
    assert session.title == "Devils in the sea cave"

    recap = db.scalar(select(Recap))
    assert (recap.version, recap.author, recap.status.value) == (1, "ai", "draft")
    events = list(db.scalars(select(StoryEvent).order_by(StoryEvent.position)))
    assert [e.kind.value for e in events] == ["event", "theory"]
    assert [x.name for x in events[0].entities] == ["Lillippi Lemon"]  # matched by alias "LL"

    proposals = {p.payload["name"]: p for p in db.scalars(select(Proposal).where(Proposal.kind == "entity"))}
    assert set(proposals) == {"Lillippi Lemon", "Horn Devil"}  # Leviathan unchanged -> no proposal
    assert proposals["Lillippi Lemon"].payload["new_aliases"] == ["Lollipy"]
    assert proposals["Horn Devil"].payload["entity_id"] is None
    glossary = [p.payload["term"] for p in db.scalars(select(Proposal).where(Proposal.kind == "glossary"))]
    assert glossary == ["Hellhound"]  # existing term not re-proposed

    kwargs = seen[0]
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["fallbacks"] == "default"
    assert kwargs["output_config"]["format"]["type"] == "json_schema"
    content = kwargs["messages"][0]["content"]
    assert any("cache_control" in block for block in content)
    joined = " ".join(b.get("text", "") for b in content)
    assert "No Name — Tim" in joined and "Dungeon Master: Mary" in joined


def test_rerun_adds_recap_version_and_replaces_drafts(db):
    session = setup(db)
    extract_session(db, session, Source("notes", "x"), fake_client())
    extract_session(db, session, Source("notes", "x"), fake_client())
    assert [r.version for r in db.scalars(select(Recap).order_by(Recap.version))] == [1, 2]
    assert len(list(db.scalars(select(StoryEvent)))) == 2
    assert len(list(db.scalars(select(Proposal).where(Proposal.kind == "entity")))) == 2


def test_refusal_is_recorded_not_raised(db):
    session = setup(db)
    run = extract_session(db, session, Source("notes", "x"), fake_client(stop_reason="refusal"))
    assert run.status == "error" and "declined" in run.error
    assert db.scalar(select(Recap)) is None


def test_story_so_far_uses_earlier_recaps(db):
    session = setup(db)
    s28 = db.scalar(select(GameSession).where(GameSession.number == 28))
    store_result(db, s28, ExtractionRun(session_id=s28.id, source="notes"), {**RESULT, "recap": "They found a shipwreck."})
    db.flush()
    db.refresh(s28)
    text = extraction._story_so_far(db, session)
    assert "Session 28" in text and "They found a shipwreck." in text


def test_timeline_orders_undated_numbered_and_added_sessions(db):
    import_bundle(db, {"campaign": {"slug": "main", "name": "Main"}, "sessions": [
        {"played_on": "2026-08-29", "title": "transcript"},
        {"number": 21, "played_on": "2025-03-22"},
        {"number": 18},
        {"number": 29, "played_on": "2026-02-07"},
        {"played_on": "2026-05-01", "title": "added gap"},
        {"number": 17},
    ]})
    from app.extraction import timeline

    campaign_id = db.scalar(select(GameSession)).campaign_id
    labels = [s.title or str(s.number) for s in timeline(db, campaign_id)]
    assert labels == ["17", "18", "21", "29", "added gap", "transcript"]


def test_a_standing_rule_a_hidden_entry_is_as_if_it_did_not_exist(db, player):
    """A standing rule (Brett, Nov 6: hidden content can't be used in recaps, World updates or questions; it's as if it
    doesn't exist until shown): a hidden entry, its facts and its relationships never reach Claude, whether drafting a
    session or describing another entry; a draft's key moments never link to it; and its name never shows on a key
    moment to the table."""
    from app import entities, relations
    from app.models import Campaign, EventEntity, EventKind, Fact, Status

    s = setup(db)
    campaign = db.get(Campaign, s.campaign_id)
    shown = Entity(campaign_id=campaign.id, kind=extraction.EntityKind.NPC, name="Mara Quill", summary="A harbour clerk.", status=Status.PUBLISHED)
    hidden = Entity(campaign_id=campaign.id, kind=extraction.EntityKind.NPC, name="The Veiled Duke", summary="Secretly runs the cult.", status=Status.DRAFT)
    db.add_all([shown, hidden])
    db.flush()
    db.add(Fact(entity_id=hidden.id, kind="addition", text="He owns the brig.", status="merged", author_name="DM", author_email=""))
    relations.add(db, hidden, "ally_of", shown)
    db.flush()
    world = extraction._known_world(db, campaign)
    assert "Mara Quill" in world and "Veiled Duke" not in world and "owns the brig" not in world and "runs the cult" not in world
    assert "Veiled Duke" not in json.dumps(entities.build_describe_messages(db, shown))
    assert "the veiled duke" not in extraction._entity_index(db, campaign.id)
    ev = StoryEvent(session_id=s.id, position=1, kind=EventKind.EVENT, text="Mara Quill met the Veiled Duke.", status=Status.PUBLISHED)
    db.add(ev)
    db.flush()
    db.add_all([EventEntity(event_id=ev.id, entity_id=shown.id), EventEntity(event_id=ev.id, entity_id=hidden.id)])
    db.add(Recap(session_id=s.id, version=1, body="They met.", author="ai", status=Status.PUBLISHED))
    db.flush()
    db.expire_all()
    page = player.get("/c/main/").text
    assert "Mara Quill</a>" in page and "Veiled Duke</a>" not in page
