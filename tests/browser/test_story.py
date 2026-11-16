"""Story's search in a real browser (app.js "Story search"): it finds sessions by their words, marks them, and
clearing it puts the page back as it was (Brett, 2026-10-29: Story search covers Story only)."""

from datetime import date

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.models import GameSession, GlossaryTerm, Recap, Status


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
    other.locator('[data-tab="t-tale"]').click()
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


def test_add_what_the_party_learned_is_one_fold_that_opens_in_place(people, server, browser_db):
    """Key Moments Everywhere, pick 3 (Brett, Nov 16; docs/mockups/key-moments/): "+ Add what the party learned" rests
    closed under a recap; opened, the box is ready to type; Escape and Cancel close only the fold and keep what's
    typed; Send gives a corner card and empties and closes it. It fits a phone's column open."""
    engine = create_engine(browser_db[0])
    with Session(engine) as db:
        s = GameSession(campaign_id=server["campaign"], number=99, played_on=date(2099, 1, 1), source="notes", title="The Ford")  # (the newest: Previously on's)
        db.add(s)
        db.flush()
        db.add(Recap(session_id=s.id, version=1, body="Cole and Trah crossed at the old ford.", author="brett", status=Status.PUBLISHED))
        db.commit()
        sid = s.id
    engine.dispose()

    player = people("player")
    page = player.open("/c/main/campaign")
    fold = page.locator(f'#t-previously details.add-fold:has(form[hx-post="/sessions/{sid}/suggest"])')
    assert not fold.evaluate("d => d.open")
    fold.locator("summary").click()
    page.wait_for_function("document.activeElement && document.activeElement.matches('details.add-fold textarea')")
    page.keyboard.type("It was the new ford.")
    page.keyboard.press("Escape")
    assert not fold.evaluate("d => d.open") and fold.locator("textarea").input_value() == "It was the new ford."
    fold.locator("summary").click()
    fold.locator("[data-fold-cancel]").click()
    assert not fold.evaluate("d => d.open")
    fold.locator("summary").click()
    fold.locator("label.chip", has=page.locator("input[value=correction]")).click()
    assert fold.locator("input[value=correction]").is_checked()
    fold.locator("button[type=submit]").click()
    page.locator("#cards > .card").first.wait_for()
    page.wait_for_function("d => !d.open", arg=fold.element_handle())
    assert fold.locator("textarea").input_value() == ""
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        row = conn.execute(text("SELECT kind, text FROM suggestions WHERE target_type = 'session' AND target_id = :s"), {"s": sid}).first()
    engine.dispose()
    assert tuple(row) == ("correction", "It was the new ford.")
    page.set_viewport_size({"width": 375, "height": 800})  # open on a phone, it stays in its column
    fold.locator("summary").click()
    assert fold.evaluate("d => d.querySelector('form').scrollWidth <= d.querySelector('form').clientWidth")
    assert player.errors == []


def test_a_glossary_term_opens_in_glossarys_reader(people, server, browser_db):
    """The UI review's pick 5 (Brett, Nov 16): Campaign › Glossary is a Reader as World is: a term picked from the list
    opens on the page at its own address, ↑ ↓ step through the list, and a name elsewhere still opens World's entry."""
    engine = create_engine(browser_db[0])
    with Session(engine) as db:
        ids = []
        for term in ("Aardwolf Ford", "Zzyzx Gate"):  # (first and last in the list, whatever the test table holds)
            g = GlossaryTerm(campaign_id=server["campaign"], term=term, description=f"About {term}.", misheard_as=[])
            db.add(g)
            db.flush()
            ids.append(g.id)
        db.commit()
    engine.dispose()
    first, last = ids
    player = people("player")
    page = player.open("/c/main/campaign?tab=glossary")
    art = page.locator("#glossary-article")
    assert art.get_attribute("data-reader-id") == str(first)  # (nothing asked for: the first term)
    page.locator(f'#glossary-reader [data-rd-id="{last}"]').click()
    page.wait_for_function(f"document.getElementById('glossary-article').dataset.readerId === '{last}'")
    assert f"term={last}" in page.url and page.locator(f'#glossary-reader [data-rd-id="{last}"].sel').count() == 1
    page.keyboard.press("ArrowUp")
    page.wait_for_function(f"document.getElementById('glossary-article').dataset.readerId !== '{last}'")
    assert page.locator("#glossary-reader .rd-item.sel").count() == 1
    assert player.errors == []
