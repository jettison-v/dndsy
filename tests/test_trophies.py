"""Trophy Case (app/trophies.py; Brett's notes on docs/mockups/player-page/, Nov 7): Party's Trophies tab, a row each and
the DM's, each opening that person's view; by default only what happened during published sessions."""

from datetime import datetime

from sqlalchemy import select

from app import review, session_story, trophies
from app.models import Campaign, CharacterDown
from tests.table_setup import char
from tests.test_session_story import publish, roll, story


def campaign(db):
    return db.scalar(select(Campaign))


def test_trophies_count_only_what_happened_during_sessions_unless_asked(db, story):
    s = publish(db, story)
    s.talk = {**(s.talk or {}), "start": "19:00", "length": 3 * 3600}
    cole, trah = char(db, "Cole"), char(db, "Trah")
    roll(db, s, cole, kept=20, hour=20)  # (during: 7 pm to 10 pm)
    roll(db, s, cole, kind="damage", total=9, hour=21)
    roll(db, s, trah, kept=1, hour=15)  # (that afternoon: not the session)
    roll(db, s, None, kept=18, hour=20)  # (the DM's: no character)
    roll(db, s, cole, kept=5, hour=20, visibility="self")  # (private: never)
    db.add(CharacterDown(character_id=cole.id, kind="down", at=datetime(2026, 11, 6, 20, 30, tzinfo=session_story.TABLE_TIME)))
    db.add(CharacterDown(character_id=trah.id, kind="down", at=datetime(2026, 11, 6, 12, 0, tzinfo=session_story.TABLE_TIME)))
    db.flush()
    rows = {r["key"]: r for r in trophies.gather(db, campaign(db))["rows"]}
    assert (rows[f"c{cole.id}"]["twenties"], rows[f"c{cole.id}"]["damage"], rows[f"c{cole.id}"]["downs"]) == (1, 9, 1)
    assert (rows[f"c{trah.id}"]["ones"], rows[f"c{trah.id}"]["downs"]) == (0, 0)
    assert rows["dm"]["rolls"] == 1 and rows["dm"]["downs"] == 1  # (the monsters' rolls; the party's drops to 0)
    assert [r["key"] for r in trophies.gather(db, campaign(db))["rows"]][-1] == "dm"  # (by name, the DM last)
    trophies.set_mode(campaign(db), "all")
    rows = {r["key"]: r for r in trophies.gather(db, campaign(db))["rows"]}
    assert (rows[f"c{trah.id}"]["ones"], rows[f"c{trah.id}"]["downs"]) == (1, 1)


def test_awards_go_on_each_persons_shelf(db, story):
    s = publish(db, story)
    rows = {r["key"]: r for r in trophies.gather(db, campaign(db))["rows"]}
    shown = session_story.awards(db, s, review.published_recap(s))
    cole = char(db, "Cole")
    mine = [a["award"] for a in shown if a.get("entity_id") == (cole.entity.id if cole.entity else None)]
    assert sorted(a["award"] for a in rows[f"c{cole.id}"]["awards"]) == sorted(mine)
    assert [a["award"] for a in rows["dm"]["awards"]] == [a["award"] for a in shown if a["dm"]]
    assert all(x["n"] >= 1 for x in rows[f"c{cole.id}"]["shelf"])


def test_the_tab_and_a_persons_view_for_everyone_at_the_table(db, story, player, dm):
    publish(db, story)
    cole = char(db, "Cole")
    assert 'data-tab="t-trophies"' in player.get("/party").text
    page = player.get("/party/trophies").text
    assert f'data-modal-url="/party/trophies/c{cole.id}"' in page and 'data-modal-url="/party/trophies/dm"' in page
    assert "Change what counts" not in page and "Change what counts" in dm.get("/party/trophies").text
    view = player.get(f"/party/trophies/c{cole.id}").text
    assert "The shelf" in view and "Every d20" in view and "Across the campaign" in view
    assert player.get("/party/trophies/c999999").status_code == 404


def test_only_the_dm_or_an_admin_sets_what_trophy_case_counts(db, story, player, dm):
    assert player.post("/c/main/manage/settings/trophies", data={"counts": "all"}).status_code == 404
    assert trophies.mode(campaign(db)) == "sessions"
    dm.post("/c/main/manage/settings/trophies", data={"counts": "all"})
    db.expire_all()
    assert trophies.mode(campaign(db)) == "all"
    assert "Trophy Case" in dm.get("/c/main/manage/settings").text
