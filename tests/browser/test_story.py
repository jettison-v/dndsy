"""Story's search in a real browser (app.js "Story search"): it finds sessions by their words, marks them, and
clearing it puts the page back as it was (Brett, 2026-10-29: Story search covers Story only)."""

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import GameSession, Recap, Status


def test_story_search_finds_the_sessions_that_mention_every_word(people, server, browser_db):
    engine = create_engine(browser_db[0])
    with Session(engine) as db:
        for n, body in ((1, "The party crossed the Saltmarsh and met Enemy 1."), (2, "Cole bargained with NPC 1 at the docks.")):
            s = GameSession(campaign_id=server["campaign"], number=n, source="notes", title=f"Session {n}")
            db.add(s)
            db.flush()
            db.add(Recap(session_id=s.id, version=1, body=body, author="brett", status=Status.PUBLISHED))
        db.commit()
    engine.dispose()

    player = people("player")
    page = player.open("/c/main/campaign?tab=sessions")  # (the box is at the top of Campaign › Sessions since Nov 13)
    box = page.locator("[data-story-search]")
    sessions = page.locator("#t-sessions details.tale-roll")

    box.fill("saltmarsh enemy")
    page.wait_for_selector("#t-sessions:not([hidden])")
    page.wait_for_function("document.querySelectorAll('mark.story-hit').length >= 2")
    assert [s.is_visible() for s in sessions.all()] == [False, True]  # newest first: only Session 1 says both
    assert "1 session mentions" in page.locator("[data-story-found]").inner_text()

    box.fill("dragon")
    page.wait_for_function("document.querySelector('[data-story-found]').textContent.includes('No session mentions')")
    assert not any(s.is_visible() for s in sessions.all())

    box.fill("")
    page.wait_for_selector("[data-story-found]", state="hidden")
    assert all(s.is_visible() for s in sessions.all())
    assert player.errors == []


def test_the_nights_awards_start_face_down_and_stay_revealed_on_that_device(people, server, browser_db):
    """A session's own page, The Night (Brett chose C, Nov 9, docs/mockups/full-tale/): each award face down until
    Reveal turns it over, remembered on that device; someone else's screen still has them face down."""
    engine = create_engine(browser_db[0])
    with Session(engine) as db:
        s = GameSession(campaign_id=server["campaign"], number=7, source="transcript", title="The Bell")
        db.add(s)
        db.flush()
        awards = [{"award": a, "character": "Cole", "why": f"Why {a}.", "quote": "", "at": 60} for a in ("Most Strategic", "Unsung Hero")]
        db.add(Recap(session_id=s.id, version=1, body="Fog.", author="ai", status=Status.PUBLISHED, awards=awards,
                     tale=[{"title": "The Reach", "kind": "story", "at": 0, "text": "The fog closed in."}]))
        db.commit()
        sid = s.id
    engine.dispose()

    player, dm = people("player", "dm")
    page = player.open(f"/c/main/sessions/{sid}")
    assert page.locator("[data-award].face-down").count() == 2 and not page.get_by_text("Why Most Strategic.").is_visible()
    page.get_by_role("button", name="Reveal who won Most Strategic").click()
    page.get_by_text("Why Most Strategic.").wait_for()  # (once it has turned over)
    assert not page.get_by_text("Why Unsung Hero.").is_visible()
    page.reload()
    page.wait_for_selector("[data-award='0']:not(.face-down)")  # (remembered on this device)
    assert page.locator("[data-award].face-down").count() == 1
    page.get_by_role("button", name="Reveal all").click()
    assert page.locator("[data-award].face-down").count() == 0 and page.get_by_role("button", name="Reveal all").is_hidden()

    other = dm.open(f"/c/main/sessions/{sid}")
    assert other.locator("[data-award].face-down").count() == 2  # (another screen reveals for itself)
    other.get_by_role("tab", name="The Tale").click()
    other.wait_for_function("location.search === '?tab=tale'")
    other.get_by_text("The fog closed in.").wait_for()
    assert player.errors == [] and dm.errors == []


def test_an_open_session_carries_its_title_in_its_scroll_and_rolls_up(people, server, browser_db):
    """All sessions (Brett, Nov 10; docs/mockups/story-page/ Sessions board): an open session's row hides and its
    scroll carries its date and title, as on Previously on…; Roll up ▴ rolls it back into its row, which takes the focus."""
    engine = create_engine(browser_db[0])
    with Session(engine) as db:
        for n in (1, 2):
            s = GameSession(campaign_id=server["campaign"], number=n, source="notes", title=f"Night {n} at the Bell")
            db.add(s)
            db.flush()
            db.add(Recap(session_id=s.id, version=1, body=f"Recap of night {n}.", author="brett", status=Status.PUBLISHED))
        db.commit()
    engine.dispose()

    player = people("player")
    page = player.open("/c/main/campaign?tab=sessions")
    sessions = page.locator("details.tale-roll")
    first = sessions.first  # (the newest opens with its title in its scroll; other tests' sessions may be newer than these)
    assert first.get_attribute("open") is not None and not first.locator(":scope > summary").is_visible()
    assert first.locator(".scroll .tale-head h2").is_visible()
    first.get_by_role("button", name="Roll up").click()
    first.locator(":scope > summary").wait_for()
    assert first.get_attribute("open") is None and page.evaluate("document.activeElement.tagName") == "SUMMARY"

    two, one = sessions.filter(has_text="Night 2 at the Bell"), sessions.filter(has_text="Night 1 at the Bell")
    for night, title in ((two, "Night 2 at the Bell"), (one, "Night 1 at the Bell")):
        if night.get_attribute("open") is None:
            night.locator(":scope > summary").click()
        night.locator(".scroll .tale-head h2").wait_for()
        assert night.locator(".scroll .tale-head h2").inner_text() == title and not night.locator(":scope > summary").is_visible()
    two.get_by_role("button", name="Roll up Night 2 at the Bell").click()
    two.locator(":scope > summary").wait_for()
    assert one.get_attribute("open") is not None  # (rolling one up leaves the others as they are)
    assert player.errors == []
