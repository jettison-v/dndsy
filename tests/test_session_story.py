"""Session Story (Brett, Nov 7; docs/mockups/session-story/): the cleaned transcript kept for drafting, the recap drafted
after the questions and suggestions are settled, the full tale on the session's own page, awards, who talked, fights and
story, and the night's dice."""

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app import admin_sessions, extraction, files, narration, review, session_story
from app.extraction import Source, extract_session
from app.importer import import_bundle
from app.models import Campaign, Correction, ExtractionRun, GameSession, Proposal, Recap, Status, StoryEvent, TableRoll
from tests.roles import set_role
from tests.table_setup import BUNDLE, char, owned_by
from tests.test_extraction import fake_client

HX = {"HX-Request": "true"}
ASKED = {"title": "The Drowned Bell", "entities": [], "relationships": [], "glossary": [],
         "to_check": ["Who is the captain?", "Was the bell rung twice?"]}
TOLD = {
    "title": "The Drowned Bell",
    "recap": "Fog rolled off the Reach. **Trah** read the runes.",
    "tale": [
        {"title": "The Reach", "kind": "exploring", "starts_at": "0:00:00", "text": "Nobody spoke for the first mile."},
        {"title": "What the Runes Said", "kind": "story", "starts_at": "1:00:00", "text": "Trah knelt by the bell."},
        {"title": "The Crew Comes Aboard", "kind": "fight", "starts_at": "2:30:00", "text": "Steel rang on the deck."},
    ],
    "events": [{"kind": "event", "text": "Trah read the runes.", "entities": ["Trah"], "major": True}],
    "awards": [
        {"award": "Most Strategic", "nominees": [
            {"character": "Trah", "why": "Read the runes before anyone touched the bell.", "quote": "", "at": "1:05:00"},
            {"character": "Cole", "why": "Kept the boat off the rocks.", "quote": "", "at": "0:20:00"},
            {"character": "", "why": "No one: dropped.", "quote": "", "at": ""}]},
        {"award": "Line of the Night", "nominees": [
            {"character": "Big C", "why": "To the drowned crew.", "quote": "If it rings for the dead, it rings them home.", "at": ""}]},
        {"award": "DM Shining Moment", "nominees": [
            {"character": "The DM", "why": "The captain's voice from under the water.", "quote": "", "at": "2:31:00"},
            {"character": "The DM", "why": "The bell ringing on its own.", "quote": "", "at": "3:00:00"}]},
        {"award": "Best Decision", "nominees": [{"character": " ", "why": "No one: dropped.", "quote": "", "at": ""}]},
    ],
}


@pytest.fixture
def story(db):
    """Main with Cole (player@'s), Trah (other@'s) and Big C; dm@ its DM; a transcript session played Nov 6."""
    import_bundle(db, {**BUNDLE, "sessions": [{"played_on": "2026-11-06", "source": "transcript"}]})
    owned_by(db, char(db, "Cole"), "player@example.com", name="Alex Moore")
    owned_by(db, char(db, "Trah"), "other@example.com", name="Sam Rivera")
    campaign = db.scalar(select(Campaign))
    set_role(db, "player@example.com", "player", "Alex Moore", campaign)
    set_role(db, "other@example.com", "player", "Sam Rivera", campaign)
    set_role(db, "dm@example.com", "dm", "Jordan Vale", campaign)
    s = db.scalar(select(GameSession))
    session_story.keep(db, s, "[0:00:01] Jordan Vale: You row into the fog.",
                       {"speakers": {"Jordan Vale": 3000.0, "Alex Moore": 1500.0, "Sam Rivera": 500.0, "Claude AI": 120.0}, "length": 4 * 3600})
    db.flush()
    return s


def read(db, s, result=ASKED):
    return extract_session(db, s, Source("transcript", session_story.text(s)), fake_client(result=result), step="ask")


def told(db, s, seen=None):
    return extract_session(db, s, Source("transcript", session_story.text(s)), fake_client(result=TOLD, seen=seen), step="tell")


def test_the_first_read_asks_and_suggests_and_writes_no_recap(db, story, dm):
    seen = []
    run = extract_session(db, story, Source("transcript", session_story.text(story)), fake_client(result=ASKED, seen=seen), step="ask")
    assert run.status == "done" and run.source == "transcript"
    assert seen[0]["output_config"]["format"]["schema"]["required"] == extraction.STEPS["ask"]
    assert "first read" in seen[0]["messages"][0]["content"][-1]["text"]
    db.expire_all()
    s = db.get(GameSession, story.id)
    assert s.recaps == [] and review.review_status(s, False) == "read" and review.statuses(db, s.campaign_id)[s.id] == "read"
    page = dm.get(f"/c/main/manage/sessions/{s.id}").text
    assert "Who is the captain?" in page and "Draft the recap" in page and "Recap to draft" in page
    assert page.index('data-tab="t-questions"') < page.index('data-tab="t-suggestions"') < page.index('data-tab="t-recap"')  # (in order)
    assert "has Claude&#39;s questions and suggestions" in dm.get("/c/main/manage").text  # Needs you


def test_draft_the_recap_reads_the_kept_transcript_with_the_answers_and_keeps_the_questions(db, story, dm, monkeypatch):
    read(db, story)
    review.answer_question(db, story, "Who is the captain?", "Captain Oyelaran, of the drowned crew.", False)
    db.flush()
    for c in db.scalars(select(Correction)):
        c.updated_at = datetime(2026, 11, 7, 9, tzinfo=session_story.TABLE_TIME)  # (answered before drafting: one test transaction has one clock)
    db.flush()
    started = []
    monkeypatch.setattr(admin_sessions, "draft_recap_in_background", lambda sid, update=False: started.append(sid) or True)
    r = dm.post(f"/c/main/manage/sessions/{story.id}/redraft", headers=HX)
    assert started == [story.id] and "drafting the recap" in r.headers["HX-Trigger"]
    seen = []
    run = told(db, story, seen)
    assert run.source == "recap" and run.status == "done"
    sent = " ".join(b.get("text", "") for b in seen[0]["messages"][0]["content"])
    assert "You row into the fog." in sent and "Captain Oyelaran" in sent and "Write the session's story" in sent
    assert seen[0]["output_config"]["format"]["schema"]["required"] == extraction.STEPS["tell"]
    db.expire_all()
    s = db.get(GameSession, story.id)
    recap = s.recaps[-1]
    assert [c["at"] for c in recap.tale] == [0, 3600, 9000] and recap.tale[2]["kind"] == "fight"
    assert [a["award"] for a in recap.awards] == ["Most Strategic", "Line of the Night", "DM Shining Moment"]  # (one with no one: dropped)
    assert [n["character"] for n in recap.awards[0]["nominees"]] == ["Trah", "Cole"] and recap.awards[0]["pick"] == 0
    assert review.latest_questions(db, s) == ASKED["to_check"]  # the recap's run doesn't clear the first read's questions
    assert review.unused_answer_count(db, s) == 0
    review.answer_question(db, s, "Was the bell rung twice?", "Once.", False)
    db.flush()
    assert review.unused_answer_count(db, s) == 1
    page = dm.get(f"/c/main/manage/sessions/{s.id}").text
    assert "The full tale" in page and "What the Runes Said" in page and "DM Shining Moment" in page
    assert "Update the draft" in page and "Start over" in page


def test_draft_the_recap_without_a_kept_transcript_says_to_send_it_again(db, story, dm, monkeypatch):
    read(db, story)
    session_story.forget(story)
    db.flush()
    r = dm.post(f"/c/main/manage/sessions/{story.id}/redraft", headers=HX)
    assert "Send it again from the Processor" in r.headers["HX-Trigger"]
    monkeypatch.setattr(admin_sessions, "_busy", type("Free", (), {"acquire": lambda *a, **k: True, "release": lambda *a: None, "locked": lambda *a: False})())
    monkeypatch.setattr(admin_sessions.threading, "Thread", lambda target, daemon: type("Now", (), {"start": lambda self: target()})())
    monkeypatch.setattr(admin_sessions.dbmod, "SessionLocal", lambda: _Same(db))
    assert admin_sessions.draft_recap_in_background(story.id)
    run = db.scalar(select(ExtractionRun).where(ExtractionRun.source == "recap"))
    assert run.status == "error" and "Send it again" in run.error


REVISED = {"entities": [{"name": "Captain Oyelaran", "kind": "npc", "summary": "Captain of the drowned crew.", "aliases": ["Captain O'Lauren"],
                          "quest_status": "not_a_quest", "race": "", "class": "sea captain"}],
           "relationships": [], "glossary": []}


def test_answers_go_into_the_waiting_suggestions_once_the_questions_are_settled(db, story, dm, monkeypatch):
    """Brett, Nov 9: a name he answered didn't reach the suggestions, written in the same pass as the questions."""
    misheard = {**ASKED, "entities": [{"name": "Captain O'Lauren", "kind": "npc", "summary": "Leads the crew in the fog.", "aliases": [],
                                       "quest_status": "not_a_quest", "race": "", "class": ""}],
                "glossary": [{"term": "Reach", "description": "The fogbound strait.", "misheard_as": []}]}
    read(db, story, misheard)
    glossary = db.scalar(select(Proposal).where(Proposal.kind == "glossary"))
    glossary.status = "rejected"
    db.flush()
    started = []
    monkeypatch.setattr(admin_sessions, "revise_in_background", lambda sid: started.append(sid) or True)
    r = dm.post(f"/c/main/manage/sessions/{story.id}/questions/answer", data={"q": "Who is the captain?", "answer": "Captain Oyelaran."}, headers=HX)
    assert started == [] and "into the suggestions" not in r.headers["HX-Trigger"]  # (a question is still open)
    assert "1 answer since these were written" in r.text and "Update the suggestions" in r.text
    r = dm.post(f"/c/main/manage/sessions/{story.id}/questions/skip", data={"q": "Was the bell rung twice?"}, headers=HX)
    assert started == [story.id] and "putting your answers into the suggestions" in r.headers["HX-Trigger"]

    seen = []
    run = extraction.revise_suggestions(db, story, fake_client(result=REVISED, seen=seen))
    assert run.status == "done" and run.source == "revise"
    kw = seen[0]
    assert kw["output_config"] == {"effort": "medium", "format": {"type": "json_schema", "schema": extraction.schema("revise")}}
    sent = " ".join(b.get("text", "") for b in kw["messages"][0]["content"])
    assert "Captain O'Lauren" in sent and "Captain Oyelaran." in sent and "Never bring back a suggestion" in sent
    assert "glossary term: Reach" in sent and "You row into the fog." not in sent  # (rejected ones named; no transcript: cents)
    db.expire_all()
    pending = list(db.scalars(select(Proposal).where(Proposal.status == "pending")))
    assert [(p.kind, p.payload["name"], p.payload["new_aliases"]) for p in pending] == [("entity", "Captain Oyelaran", ["Captain O'Lauren"])]
    assert review.latest_questions(db, story) == ASKED["to_check"]  # (the questions stay the first read's)
    for c in db.scalars(select(Correction)):
        c.updated_at = datetime(2026, 11, 7, 9, tzinfo=session_story.TABLE_TIME)  # (answered before it: one test transaction has one clock)
    db.flush()
    assert review.answers_since_suggestions(db, story) == 0


def test_draft_the_recap_again_updates_the_draft_and_keeps_the_picks(db, story, dm, monkeypatch):
    """Brett, Nov 9: drafting again keeps what's good instead of starting over; the transcript is cached for an hour."""
    read(db, story)
    told(db, story)
    db.expire_all()
    s = db.get(GameSession, story.id)
    review.pick_nominee(db, s, 0, 1)  # Cole for Most Strategic
    db.flush()
    calls = []
    monkeypatch.setattr(admin_sessions, "draft_recap_in_background", lambda sid, update=False: calls.append(update) or True)
    r = dm.post(f"/c/main/manage/sessions/{s.id}/redraft", headers=HX)
    assert calls == [True] and "updating the draft" in r.headers["HX-Trigger"]
    dm.post(f"/c/main/manage/sessions/{s.id}/redraft", data={"fresh": "1"}, headers=HX)
    assert calls == [True, False]  # Start over

    review.answer_question(db, s, "Was the bell rung twice?", "Once.", False)
    db.flush()
    seen = []
    extract_session(db, s, Source("transcript", session_story.text(s)), fake_client(result=TOLD, seen=seen), step="tell", update=True)
    blocks = seen[0]["messages"][0]["content"]
    assert "You row into the fog." in blocks[0]["text"] and blocks[0]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert sum("cache_control" in b for b in blocks) == 1
    sent = " ".join(b.get("text", "") for b in blocks)
    assert '<current_draft written_by="Claude">' in sent and "Fog rolled off the Reach." in sent and "## The Crew Comes Aboard (fight, starts 2:30:00)" in sent
    assert "Cole (picked)" in sent and "A: Once. (new)" in sent and blocks[-1]["text"] == extraction.UPDATE_NOTE
    db.expire_all()
    s = db.get(GameSession, story.id)
    assert [n["character"] for n in s.recaps[-1].awards[0]["nominees"]][s.recaps[-1].awards[0]["pick"]] == "Cole"  # (still picked)


def test_every_award_asks_for_three_nominees():
    """Brett, Nov 9: three to pick from, not two."""
    assert "exactly 3 nominees" in extraction.SYSTEM_PROMPT and "2-3 nominees" not in extraction.SYSTEM_PROMPT
    assert extraction.NOMINEES_MOST == 3


def test_an_hours_cache_write_is_priced_at_twice_the_input():
    from types import SimpleNamespace
    usage = SimpleNamespace(input_tokens=1000, output_tokens=0, cache_read_input_tokens=0, cache_creation_input_tokens=90_000,
                            cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=90_000, ephemeral_5m_input_tokens=0))
    assert extraction._cost(usage) == round((1000 * 4 + 90_000 * 8) / 1e6, 4)


class _Same:
    def __init__(self, db):
        self.db = db

    def __enter__(self):
        return self.db

    def __exit__(self, *a):
        return False


def test_only_an_admin_lets_a_transcript_go(db, story, dm, admin):
    read(db, story)
    r = dm.post(f"/c/main/manage/sessions/{story.id}/transcript/forget", headers=HX)
    assert "Only an admin" in r.headers["HX-Trigger"]
    db.expire_all()
    assert db.get(GameSession, story.id).transcript_key
    admin.post(f"/c/main/manage/sessions/{story.id}/transcript/forget", headers=HX)
    db.expire_all()
    assert db.get(GameSession, story.id).transcript_key is None


def publish(db, s):
    read(db, s)
    told(db, s)
    db.expire_all()
    s = db.get(GameSession, s.id)
    review.publish(db, s)
    db.flush()
    return s


def test_the_session_page_has_the_full_tale_awards_and_numbers_for_everyone_at_the_table(db, story, player):
    s = publish(db, story)
    home = player.get("/c/main/").text
    assert "Read the full tale" in home and f"/c/main/sessions/{s.id}" in home
    page = player.get(f"/c/main/sessions/{s.id}").text
    assert page.index("The Reach") < page.index("What the Runes Said") < page.index("The Crew Comes Aboard")
    assert "If it rings for the dead, it rings them home." in page and "The DM" in page and "DM Shining Moment" in page
    assert "Who talked" in page and "Fights and story" in page and "4 h 0 min" in page
    assert "You row into the fog." not in page  # (the transcript is shown on no page)
    assert player.get(f"/sessions/{s.id}", follow_redirects=False).status_code == 404  # (one address: /c/<campaign>/…)


def test_an_unpublished_session_has_no_page(db, story, player):
    read(db, story)
    told(db, story)
    assert player.get(f"/c/main/sessions/{story.id}").status_code == 404


def test_who_talked_matches_names_and_asks_once_for_the_rest(db, story, dm):
    campaign = db.get(Campaign, story.campaign_id)
    talked = session_story.who_talked(db, story, campaign)
    assert [(r["name"], r["share"]) for r in talked["rows"]] == [("The DM", 60), ("Cole", 30), ("Trah", 10)]
    assert talked["unmatched"] == ["Claude AI"]
    read(db, story)
    told(db, story)
    page = dm.get(f"/c/main/manage/sessions/{story.id}").text
    assert "Who is this in the recording?" in page and "Claude AI" in page
    dm.post(f"/c/main/manage/sessions/{story.id}/speakers", data={"name": "Claude AI", "user_id": "0"}, headers=HX)
    db.expire_all()
    campaign = db.get(Campaign, story.campaign_id)
    assert campaign.speakers == {"Claude AI": 0} and session_story.who_talked(db, story, campaign)["unmatched"] == []
    r = dm.post(f"/c/main/manage/sessions/{story.id}/speakers", data={"name": "Someone Else", "user_id": "0"}, headers=HX)
    assert "isn&#39;t in this recording" in r.headers["HX-Trigger"] or "isn't in this recording" in r.headers["HX-Trigger"]


def test_fights_and_story_come_from_when_each_chapter_began(db, story):
    read(db, story)
    told(db, story)
    db.expire_all()
    s = db.get(GameSession, story.id)
    mix = {p["kind"]: p["share"] for p in session_story.mix(s, s.recaps[-1])["parts"]}
    assert mix == {"fight": 38, "story": 38, "exploring": 25, "rest": 0}  # (1 h, 1 h 30, 1 h 30 of 4 h)
    s.recaps[-1].tale = [{**c, "at": None} for c in s.recaps[-1].tale]
    assert session_story.mix(s, s.recaps[-1]) is None  # (notes: no times, no bar)


def roll(db, s, character, kept=None, kind="check", total=10, visibility="table", hour=20, parent=None):
    r = TableRoll(campaign_id=s.campaign_id, character_id=character.id if character else None, label="x", kind=kind, formula="d20",
                  dice=[kept or total], kept=kept, total=total, visibility=visibility, parent_id=parent,
                  created_at=datetime(2026, 11, 6, hour, tzinfo=session_story.TABLE_TIME))
    db.add(r)
    db.flush()
    return r


def test_the_nights_dice_and_their_awards_count_only_what_the_table_saw(db, story):
    cole, trah = char(db, "Cole"), char(db, "Trah")
    roll(db, story, cole, kept=1)
    roll(db, story, cole, kept=20)
    roll(db, story, trah, kept=1)
    roll(db, story, trah, kept=1, visibility="self")  # private: never counted
    hit = roll(db, story, trah, kept=15, kind="attack")
    roll(db, story, trah, kind="damage", total=12, parent=hit.id)
    roll(db, story, cole, kind="damage", total=30, visibility="dm")  # the DM's eyes only
    roll(db, story, cole, kept=1, hour=9)  # that morning: not the night
    got = session_story.dice(db, story)
    assert (got["rolls"], got["twenties"], got["ones"]) == (4, 1, 2)
    assert got["damage_king"]["character"].name == "Trah" and got["damage_king"]["why"] == "12 damage rolled, in 1 roll."
    assert got["hardest_luck"]["character"].name in ("Cole", "Trah")  # (one natural 1 each; the lower average loses)
    assert got["hardest_luck"]["character"].name == "Trah"
    awards = session_story.awards(db, story, None, got)
    assert [(a["award"], a["who"], a["dice"]) for a in awards] == [("Hardest Luck", "Trah", True), ("Damage King", "Trah", True)]


def test_the_reviewer_picks_who_an_award_goes_to_from_its_nominees(db, story, dm, player):
    s = publish(db, story)
    page = dm.get(f"/c/main/manage/sessions/{s.id}").text
    assert 'name="nominee" value="1"' in page and "Kept the boat off the rocks." in page
    assert "Kept the boat off the rocks." not in player.get(f"/c/main/sessions/{s.id}").text  # (Claude's first, until picked)
    r = dm.post(f"/c/main/manage/sessions/{s.id}/awards/0/pick", data={"nominee": "1"}, headers=HX)
    assert "Goes to Cole" in r.headers["HX-Trigger"]
    db.expire_all()
    s = db.get(GameSession, s.id)
    assert s.recaps[-1].awards[0]["pick"] == 1 and review.review_status(s, False) == "edited"
    review.publish(db, s)
    db.flush()
    page = player.get(f"/c/main/sessions/{s.id}").text
    assert "Kept the boat off the rocks." in page and "Read the runes before anyone touched the bell." not in page
    r = dm.post(f"/c/main/manage/sessions/{s.id}/awards/0/pick", data={"nominee": "7"}, headers=HX)
    assert "isn" in r.headers["HX-Trigger"]
    shown = session_story.awards(db, s, s.recaps[-1], {"hardest_luck": None, "damage_king": None})
    assert [a["who"] for a in shown] == ["Cole", "Big C", "The DM"] and shown[2]["dm"]


def test_an_award_drafted_without_nominees_still_shows(db, story):
    recap = Recap(session_id=story.id, version=1, body="R.", author="ai", awards=[{"award": "Unsung Hero", "character": "Cole", "why": "Held the line.", "quote": "", "at": 60}])
    shown = session_story.awards(db, story, recap, {})
    assert (shown[0]["who"], shown[0]["why"], shown[0]["clock"], len(shown[0]["nominees"])) == ("Cole", "Held the line.", "0:01", 1)


def test_editing_the_tale_or_an_award_after_publishing_makes_a_new_version(db, story, dm):
    s = publish(db, story)
    published = review.published_recap(s)
    dm.post(f"/c/main/manage/sessions/{s.id}/tale/1", data={"title": "The Runes", "text": "Trah read them aloud.", "kind": "fight"}, headers=HX)
    dm.post(f"/c/main/manage/sessions/{s.id}/awards/1", data={"character": "Cole", "why": "Said it first.", "quote": "It rings them home."}, headers=HX)
    dm.post(f"/c/main/manage/sessions/{s.id}/awards/0/drop", headers=HX)
    db.expire_all()
    s = db.get(GameSession, s.id)
    latest = s.recaps[-1]
    assert latest.id != published.id and latest.status == Status.DRAFT and review.review_status(s, False) == "edited"
    assert latest.tale[1]["title"] == "The Runes" and latest.tale[1]["text"] == "Trah read them aloud." and latest.tale[1]["at"] == 3600
    assert latest.tale[1]["kind"] == "fight"
    assert [a["award"] for a in latest.awards] == ["Line of the Night", "DM Shining Moment"]
    assert latest.awards[0]["nominees"][0]["character"] == "Cole" and latest.awards[0]["nominees"][0]["quote"] == "It rings them home."
    assert db.get(Recap, published.id).awards[0]["award"] == "Most Strategic"  # the table still reads what was published
    review.save_recap(db, s, "A new recap.", by="Dee")
    assert s.recaps[-1].tale == latest.tale and s.recaps[-1].awards == latest.awards  # a recap edit keeps the tale and awards


def test_listen_reads_the_full_tale_chapter_by_chapter(db, story, player, monkeypatch):
    s = publish(db, story)
    campaign = db.get(Campaign, s.campaign_id)
    campaign.vtt_pieces = ["labs", narration.PIECE]
    db.flush()
    words = narration.words(s, review.published_recap(s), "Main", "full")
    assert words[:3] == ["Main. The Drowned Bell…", "Chapter I. The Reach.", "Nobody spoke for the first mile."]
    heard = []
    monkeypatch.setattr(narration, "FETCH", lambda text: heard.append(text) or b"ID3audio")
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    r = player.post(f"/c/main/sessions/{s.id}/full/narrate").json()
    assert r["audio"].startswith(f"/c/main/sessions/{s.id}/full/narration") and "Chapter III. The Crew Comes Aboard." in heard[0]
    assert player.get(r["audio"]).content == b"ID3audio"
    assert player.get(f"/c/main/sessions/{s.id}/full/tale").json()["intro"] == "Main. The Drowned Bell…"
    db.expire_all()
    assert review.published_recap(db.get(GameSession, s.id)).narration_key is None  # (the recap's own stays unmade)
    assert player.get(f"/c/main/sessions/{s.id}/tale?part=nope").status_code == 404


def test_the_processor_counts_who_talked_without_any_words():
    from transcript_filter.pipeline import talk_times
    from transcript_filter.segments import Segment

    segs = [Segment(0, 0.0, 10.0, "Mary", "You wake."), Segment(1, 10.0, 14.0, "Brett", "I look around."),
            Segment(2, 10.0, 14.0, "Mary", "I look around.", "echo"), Segment(3, 20.0, 30.0, None, "…")]
    assert talk_times(segs) == {"speakers": {"Mary": 10.0, "Brett": 4.0}, "length": 30}


def test_a_drafted_story_keeps_old_sessions_working(db, story):
    """Before Nov 7 a transcript was drafted in one go: its run wrote the recap, so its answers count from it."""
    run = ExtractionRun(session_id=story.id, source="transcript", status="done", to_check=["Old question?"])
    db.add(run)
    db.flush()
    extraction.store_result(db, story, run, {**ASKED, "recap": "Old recap.", "events": []})
    db.add(Correction(campaign_id=story.campaign_id, session_id=story.id, kind="answer", before="Old question?", after="Yes."))
    db.flush()
    db.expire_all()
    s = db.get(GameSession, story.id)
    assert review.last_told(db, s).id == run.id and review.unused_answer_count(db, s) == 1
    assert s.recaps[-1].tale == [] and not session_story.has_more(s.recaps[-1])
    assert db.scalar(select(StoryEvent)) is None
    assert files.get(s.transcript_key).startswith(b"[0:00:01]")
    assert date(2026, 11, 6) == s.played_on


def test_the_review_is_a_wizard_that_opens_on_what_is_left_and_keeps_its_place(db, story, dm):
    """Brett, Nov 7: the review's parts as tabs in order, each ending with Next; a change keeps the tab you're on."""
    read(db, story)
    page = dm.get(f"/c/main/manage/sessions/{story.id}").text
    assert 'data-tab="t-questions"' in page and 'id="t-questions" role="tabpanel">' in page  # questions left: opens there
    assert 'id="t-suggestions" role="tabpanel" hidden' in page and "Next: Suggestions →" in page and 'data-tab="t-awards"' not in page
    for q in ASKED["to_check"]:
        review.skip_question(db, story, q)
    db.flush()
    page = dm.get(f"/c/main/manage/sessions/{story.id}").text
    assert 'id="t-recap" role="tabpanel">' in page  # (no suggestions either: straight to Draft the recap)
    told(db, story)
    r = dm.post(f"/c/main/manage/sessions/{story.id}/awards/0/pick", data={"nominee": "1"},
                headers={**HX, "HX-Current-URL": f"http://testserver/c/main/manage/sessions/{story.id}?tab=awards"})
    assert 'id="t-awards" role="tabpanel">' in r.text and 'id="t-recap" role="tabpanel" hidden' in r.text
    page = dm.get(f"/c/main/manage/sessions/{story.id}?tab=numbers").text
    assert 'id="t-numbers" role="tabpanel">' in page and "That's everything" in page
    assert dm.get(f"/c/main/manage/sessions/{story.id}?tab=nope").status_code == 200


def test_a_redrafts_key_moments_replace_the_published_ones_when_published(db, story):
    s = publish(db, story)
    review.published_recap(s).updated_at = datetime(2026, 11, 7, 9, tzinfo=session_story.TABLE_TIME)  # (published before the redraft)
    db.flush()
    told(db, s)
    db.expire_all()
    s = db.get(GameSession, s.id)
    old = next(ev for ev in s.events if ev.status == Status.PUBLISHED)
    review.toggle_major(db, s, old.id)  # (a published moment starred after the redraft: still replaced)
    db.expire_all()
    s = db.get(GameSession, s.id)
    review.save_event(db, s, None, "event", "Added by hand.")  # (a moment of the DM's, added to the redraft)
    db.flush()
    db.expire_all()
    s = db.get(GameSession, s.id)
    assert len(s.events) == 3  # the published one, the DM's and the redraft's, until publishing
    review.publish(db, s)
    db.flush()
    db.expire_all()
    s = db.get(GameSession, s.id)
    assert sorted(ev.text for ev in s.events) == ["Added by hand.", "Trah read the runes."]
    assert all(ev.status == Status.PUBLISHED for ev in s.events)


def test_editing_a_published_moment_and_publishing_again_keeps_the_rest(db, story):
    s = publish(db, story)
    review.save_event(db, s, None, "event", "Added by hand.")
    db.flush()
    review.publish(db, s)
    db.flush()
    db.expire_all()
    assert len(db.get(GameSession, s.id).events) == 2


def suggested(db, s):
    from app.models import Entity, Proposal

    lil = Entity(campaign_id=s.campaign_id, kind="npc", name="Lillippi Lemon", summary="Tiefling bard.", status=Status.PUBLISHED)
    db.add(lil)
    db.flush()
    read(db, s, {**ASKED, "entities": [
        {"name": "Alith", "kind": "creature", "summary": "Tiny owlin in the library.", "aliases": [], "quest_status": "not_a_quest"},
        {"name": "Lillippi Lemon", "kind": "npc", "summary": "Tiefling bard who sings.", "aliases": [], "quest_status": "not_a_quest"}]})
    by = {p.payload["name"]: p for p in db.scalars(select(Proposal))}
    return by["Alith"], by["Lillippi Lemon"], lil


def test_a_suggestions_name_and_kind_can_be_changed_before_accepting(db, story, dm):
    """Brett, Nov 7: a new person's name is often misheard; Edit takes the name (and a new one's kind)."""
    from app.models import Entity

    new, old, lil = suggested(db, story)
    page = dm.get(f"/c/main/manage/sessions/{story.id}?tab=suggestions").text
    assert f'hx-post="/c/main/manage/proposals/{new.id}/accept"' in page and 'name="name" value="Alith"' in page and 'name="kind"' in page
    dm.post(f"/c/main/manage/proposals/{new.id}/accept", data={"name": "Aleth", "kind": "npc", "summary": "Tiny owlin, barn owl's face."}, headers=HX)
    db.expire_all()
    aleth = db.scalar(select(Entity).where(Entity.name == "Aleth"))
    assert aleth.kind.value == "npc" and [(a.alias, a.misspelling) for a in aleth.aliases] == [("Alith", True)]
    page = dm.get(f"/c/main/manage/sessions/{story.id}?tab=suggestions").text
    assert "New in the World" in page and f"/pictures?for=entity:{aleth.id}" in page  # a picture of it, from here
    dm.post(f"/c/main/manage/proposals/{old.id}/accept", data={"name": "Lillippi", "summary": "Tiefling bard who sings."}, headers=HX)
    db.expire_all()
    lil = db.get(Entity, lil.id)
    assert lil.name == "Lillippi" and "Lillippi Lemon" in [a.alias for a in lil.aliases]  # (renamed; the old name still finds it)
    review.undo_proposal(db, db.get(type(old), old.id))
    db.flush()
    db.expire_all()
    lil = db.get(Entity, lil.id)
    assert lil.name == "Lillippi Lemon" and lil.aliases == [] and lil.summary == "Tiefling bard."


def test_a_persons_race_and_class_come_with_the_suggestion_and_start_their_picture(db, story, dm):
    """Brett, Nov 7: every person's race and class, for their entry and for drawing them."""
    from app import pictures
    from app.extraction import _known_world
    from app.models import Entity, Proposal

    read(db, story, {**ASKED, "entities": [
        {"name": "Devin", "kind": "npc", "summary": "Librarian of the Crow's Keep.", "aliases": [], "quest_status": "not_a_quest",
         "race": "Human", "class": "Wizard (diviner)"},
        {"name": "Perth", "kind": "npc", "summary": "A fleeing lad.", "aliases": [], "quest_status": "not_a_quest", "race": "", "class": ""},
        {"name": "The Reach", "kind": "place", "summary": "Fog.", "aliases": [], "quest_status": "not_a_quest", "race": "Elf", "class": ""}]})
    by = {p.payload["name"]: p for p in db.scalars(select(Proposal))}
    assert by["Devin"].payload["traits"] == {"race": "Human", "class": "Wizard (diviner)"} and by["The Reach"].payload["traits"] == {}
    page = dm.get(f"/c/main/manage/sessions/{story.id}?tab=suggestions").text
    assert "Human · Wizard (diviner)" in page and "Race not known" in page
    dm.post(f"/c/main/manage/proposals/{by['Devin'].id}/accept", headers=HX)
    dm.post(f"/c/main/manage/proposals/{by['Perth'].id}/accept", data={"name": "Perth", "summary": "A fleeing lad.", "race": "Halfling", "class": "Dockhand"}, headers=HX)
    db.expire_all()
    devin, perth = (db.scalar(select(Entity).where(Entity.name == n)) for n in ("Devin", "Perth"))
    assert perth.traits == {"race": "Halfling", "class": "Dockhand"}
    o = pictures.owner(db, f"entity:{devin.id}", {"email": "admin@example.com"})
    assert o.words.startswith("Devin (Human Wizard (diviner)): Librarian")
    assert "- Devin [npc] (Human, Wizard (diviner)): Librarian" in _known_world(db, db.get(Campaign, story.campaign_id))
    entry = dm.get(f"/c/main/campaign?open={devin.id}").text
    assert "<dt>Race</dt><dd>Human</dd>" in entry
    dm.post(f"/campaign/{devin.id}/details", data={"kind": "npc", "published": "1", "race": "Human", "class": "Librarian"}, headers=HX)
    db.expire_all()
    assert db.get(Entity, devin.id).traits == {"race": "Human", "class": "Librarian"}
