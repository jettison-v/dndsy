"""Session Story (Brett, Nov 7; docs/mockups/session-story/): the cleaned transcript kept for drafting, the recap drafted
after the questions and suggestions are settled, the full tale on the session's own page, awards, who talked, fights and
story, and the night's dice."""

from datetime import date, datetime

import pytest
from sqlalchemy import select

from app import admin_sessions, extraction, files, narration, review, session_story
from app.extraction import Source, extract_session
from app.importer import import_bundle
from app.models import Campaign, Correction, ExtractionRun, GameSession, Recap, Status, StoryEvent, TableRoll
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
        {"award": "Most Strategic", "character": "Trah", "why": "Read the runes before anyone touched the bell.", "quote": "", "at": "1:05:00"},
        {"award": "Line of the Night", "character": "Big C", "why": "To the drowned crew.", "quote": "If it rings for the dead, it rings them home.", "at": ""},
        {"award": "DM Shining Moment", "character": "The DM", "why": "The captain's voice from under the water.", "quote": "", "at": "2:31:00"},
        {"award": "Most Strategic", "character": "", "why": "No one: dropped.", "quote": "", "at": ""},
    ],
}


@pytest.fixture
def story(db):
    """Main with Cole (player@'s), Trah (other@'s) and Big C; dm@ its DM; a transcript session played Nov 6."""
    import_bundle(db, {**BUNDLE, "sessions": [{"played_on": "2026-11-06", "source": "transcript"}]})
    owned_by(db, char(db, "Cole"), "player@example.com", name="Brett Cupta")
    owned_by(db, char(db, "Trah"), "other@example.com", name="Mark Cupta")
    campaign = db.scalar(select(Campaign))
    set_role(db, "player@example.com", "player", "Brett Cupta", campaign)
    set_role(db, "other@example.com", "player", "Mark Cupta", campaign)
    set_role(db, "dm@example.com", "dm", "Mary Stewart", campaign)
    s = db.scalar(select(GameSession))
    session_story.keep(db, s, "[0:00:01] Mary Stewart: You row into the fog.",
                       {"speakers": {"Mary Stewart": 3000.0, "Brett Cupta": 1500.0, "Mark Cupta": 500.0, "Claude AI": 120.0}, "length": 4 * 3600})
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
    assert page.index("Suggested updates") < page.index("Draft the recap")  # (questions, then suggestions, then the recap)
    assert "has Claude&#39;s questions and suggestions" in dm.get("/c/main/manage").text  # Needs you


def test_draft_the_recap_reads_the_kept_transcript_with_the_answers_and_keeps_the_questions(db, story, dm, monkeypatch):
    read(db, story)
    review.answer_question(db, story, "Who is the captain?", "Captain Oyelaran, of the drowned crew.", False)
    db.flush()
    for c in db.scalars(select(Correction)):
        c.updated_at = datetime(2026, 11, 7, 9, tzinfo=session_story.TABLE_TIME)  # (answered before drafting: one test transaction has one clock)
    db.flush()
    started = []
    monkeypatch.setattr(admin_sessions, "draft_recap_in_background", lambda sid: started.append(sid) or True)
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
    assert review.latest_questions(db, s) == ASKED["to_check"]  # the recap's run doesn't clear the first read's questions
    assert review.unused_answer_count(db, s) == 0
    review.answer_question(db, s, "Was the bell rung twice?", "Once.", False)
    db.flush()
    assert review.unused_answer_count(db, s) == 1
    page = dm.get(f"/c/main/manage/sessions/{s.id}").text
    assert "The full tale" in page and "What the Runes Said" in page and "DM Shining Moment" in page and "Redraft" in page


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
    assert [a["award"] for a in latest.awards] == ["Line of the Night", "DM Shining Moment"] and latest.awards[0]["character"] == "Cole"
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
