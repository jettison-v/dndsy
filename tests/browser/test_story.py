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
    page = player.open("/c/main/")
    box = page.locator("[data-story-search]")
    sessions = page.locator("#t-sessions details.section")

    box.fill("saltmarsh enemy")
    page.wait_for_selector("#t-sessions:not([hidden])")  # it opens All sessions
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
