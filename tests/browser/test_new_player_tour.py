"""The new-player tour in a real browser (app/tour.py, app.js "the tour"): started from the ? menu, it walks every
stop across pages, lighting a target that's really there on each one, and Esc asks before ending it. A page change that loses a
stop's target fails here, so the tour can't quietly break."""

import pytest


def card_title(page) -> str:
    return page.locator(".tour-card h3").inner_text()


def lit(page) -> bool:
    """The spotlight is showing and sits over something on the page (not the card alone in the middle)."""
    return page.evaluate("""() => { const s = document.querySelector('.tour-spot'), c = document.querySelector('.tour-card');
      return !!s && !s.hidden && !c.classList.contains('alone') && s.getBoundingClientRect().width > 12; }""")


def pinned(page) -> list[str]:
    return page.locator('[data-econ-col="action"] .move:not(.static) > b').all_inner_texts()


def test_a_player_walks_every_stop_and_each_lights_something(people, server):
    """Including Battle's hands-on stops (+ Add opens the side panel, a row opens its marks and note, examples only on
    the page), the Spell Book's, and Wild Shape's preview: afterwards nothing new is pinned and Cole is in no form."""
    player = people("player")
    before = pinned(player.open(f"/characters/{server['cole']}/battle"))
    page = player.open("/c/main/")
    stops = page.evaluate("fetch('/tour').then(r => r.json()).then(d => d.stops)")
    assert len(stops) > 10 and {"spellbook", "wildshape"} <= {s["group"] for s in stops}  # Cole casts and shifts
    page.click("[data-tour=help] .help-btn")
    page.click("#help-menu [data-tour-start]")
    for i, stop in enumerate(stops):
        page.wait_for_function("t => document.querySelector('.tour-card h3')?.textContent === t", arg=stop["title"], timeout=10000)
        if stop["url"]:
            assert page.evaluate("location.pathname") == stop["url"], stop["title"]
        page.wait_for_function("() => { const s = document.querySelector('.tour-spot'); return s && !s.hidden; }", timeout=5000)
        assert lit(page), f"stop {i + 1}, {stop['title']}: nothing to light up ({stop['at']})"
        if stop["example"]:
            assert page.locator(".tour-example").count() == 1, stop["title"]
        if stop["panel"]:
            assert page.locator(".peek.open").count() == 1, stop["title"]
        assert page.locator(".tour-foot .count").inner_text() == f"{i + 1} of {len(stops)}"  # every stop, not groups
        if stop["at"] == '[data-tour="live"]':  # in the menu bar, over everything: lit where it is
            page.wait_for_function("""() => { const s = document.querySelector('.tour-spot').getBoundingClientRect(),
                p = document.querySelector('[data-tour="live"]').getBoundingClientRect();
              return s.top <= p.top && s.bottom >= p.bottom && s.height < 80; }""", timeout=3000)
        page.keyboard.press("ArrowRight")
        if i + 1 < len(stops) and stops[i + 1]["url"] and stops[i + 1]["url"] != stop["url"]:
            page.wait_for_url(f"**{stops[i + 1]['url']}")
    page.wait_for_selector(".tour-card", state="detached")
    assert page.evaluate("sessionStorage.getItem('askdnd-tour')") is None
    assert pinned(player.open(f"/characters/{server['cole']}/battle")) == before
    assert player.page.locator("#battle-body .ws-form").count() == 0  # the Wild Shape stops were a preview
    assert player.errors == []


def test_show_me_starts_at_its_group_and_ending_asks_first(people, server):
    player = people("player")
    page = player.open("/help?tab=adds")
    page.click('[data-tour-start="plan"]')
    page.wait_for_url(f"**/characters/{server['cole']}/plan")
    page.wait_for_selector(".tour-card")
    assert card_title(page) == "Battle combos" and lit(page)
    assert page.locator('[data-tab="t-combo"]').get_attribute("aria-selected") == "true"
    page.keyboard.press("ArrowRight")  # then a combo's window (or a new one's), unsaved
    page.wait_for_function("() => document.querySelector('.tour-card h3')?.textContent === 'A combo, turn by turn'")
    page.wait_for_selector(".peek.open")
    page.keyboard.press("ArrowRight")
    page.wait_for_function("() => document.querySelector('.tour-card h3')?.textContent === 'Leveling strategy'")
    assert page.locator('[data-tab="t-leveling"]').get_attribute("aria-selected") == "true"
    assert page.locator(".peek.open").count() == 0
    page.keyboard.press("Escape")  # asks; Esc again is Keep going
    assert card_title(page) == "End the tour?"
    page.keyboard.press("Escape")
    page.wait_for_function("() => document.querySelector('.tour-card h3')?.textContent === 'Leveling strategy'")
    page.click(".tour-card [data-tour-end]")
    page.click(".tour-card [data-tour-end-now]")
    assert page.locator(".tour-card").count() == 0
    page.reload()  # ended means ended: it doesn't come back with the page
    page.wait_for_load_state("networkidle")
    assert page.locator(".tour-card").count() == 0
    assert player.errors == []


def test_leaving_mid_wild_shape_puts_battle_back(people, server):
    """Esc while the tour shows Battle in a form: Battle is drawn as it really is again, and nothing was saved."""
    player = people("player")
    page = player.open("/help?tab=adds")
    page.click('[data-tour-start="wildshape"]')
    page.wait_for_url(f"**/characters/{server['cole']}/battle")
    page.wait_for_selector("#battle-body .ws-form")
    page.keyboard.press("Escape")
    page.keyboard.press("Enter")  # End tour
    page.wait_for_selector("#battle-body .ws-form", state="detached")
    player.open(f"/characters/{server['cole']}/battle")
    assert page.locator("#battle-body .ws-form").count() == 0
    assert player.errors == []


@pytest.mark.parametrize("size", [(1000, 540), (1300, 950)])  # short, where Battle's columns are tall; a laptop, where they fit
def test_a_large_section_is_lit_below_the_bars_stuck_over_it(people, server, size):
    """Battle's numbers stick across the top of the screen (over half of a short one); the columns' tops (their
    headings) are shown and lit below them, not behind, whether the columns fit on screen or not (Brett, 2026-10-26)."""
    player = people("player")
    player.page.set_viewport_size({"width": size[0], "height": size[1]})
    page = player.open("/help?tab=adds")
    page.click('[data-tour-start="battle"]')
    page.wait_for_url(f"**/characters/{server['cole']}/battle")
    page.wait_for_function("() => document.querySelector('.tour-card h3')?.textContent.startsWith('Battle:')", timeout=10000)
    page.wait_for_timeout(600)  # the page settling, and the light following
    got = page.evaluate("""() => { const bar = document.querySelector('.battlebar').getBoundingClientRect(),
        head = document.querySelector('[data-tour="battle"] .econ-head').getBoundingClientRect(),
        spot = document.querySelector('.tour-spot').getBoundingClientRect();
      return { bar: bar.bottom, head: head.top, spot: spot.top }; }""")
    assert got["head"] >= got["bar"] and got["spot"] >= got["bar"] - 8, got
    # Seconds later Battle is redrawn (Game Mode's fresh sheet) and its numbers grow: the headings are kept clear
    page.wait_for_timeout(2500)
    for _ in range(5):  # a finger resting on a laptop's trackpad: tiny scroll events, not a scroll
        page.mouse.wheel(0, 1)
    page.evaluate("""() => { const b = document.getElementById('battle-body'); b.replaceWith(b.cloneNode(true));
      const d = document.createElement('div'); d.style.height = '70px'; document.querySelector('.battlebar').prepend(d); }""")
    page.wait_for_timeout(600)
    got = page.evaluate("""() => { const bar = document.querySelector('.battlebar').getBoundingClientRect(),
        head = document.querySelector('[data-tour="battle"] .econ-head').getBoundingClientRect(),
        spot = document.querySelector('.tour-spot').getBoundingClientRect();
      return { bar: bar.bottom, head: head.top, spot: spot.top }; }""")
    assert got["head"] >= got["bar"] and got["spot"] >= got["bar"] - 8, got
    assert player.errors == []
