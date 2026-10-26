"""The new-player tour in a real browser (app/tour.py, app.js "the tour"): started from the ? menu, it walks every
stop across pages, lighting a target that's really there on each one, and Esc ends it. A page change that loses a
stop's target fails here, so the tour can't quietly break."""


def card_title(page) -> str:
    return page.locator(".tour-card h3").inner_text()


def lit(page) -> bool:
    """The spotlight is showing and sits over something on the page (not the card alone in the middle)."""
    return page.evaluate("""() => { const s = document.querySelector('.tour-spot'), c = document.querySelector('.tour-card');
      return !!s && !s.hidden && !c.classList.contains('alone') && s.getBoundingClientRect().width > 12; }""")


def pinned(page) -> list[str]:
    return page.locator('[data-econ-col="action"] .move:not(.static) > b').all_inner_texts()


def test_a_player_walks_every_stop_and_each_lights_something(people, server):
    """Including Battle's hands-on stops: + Add opens the side panel, a row opens its marks and note, and the examples
    on Battle are only on the page: afterwards nothing new is pinned."""
    player = people("player")
    before = pinned(player.open(f"/characters/{server['cole']}/battle"))
    page = player.open("/c/main/")
    stops = page.evaluate("fetch('/tour').then(r => r.json()).then(d => d.stops)")
    assert len(stops) > 10
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
        page.keyboard.press("ArrowRight")
        if i + 1 < len(stops) and stops[i + 1]["url"] and stops[i + 1]["url"] != stop["url"]:
            page.wait_for_url(f"**{stops[i + 1]['url']}")
    page.wait_for_selector(".tour-card", state="detached")
    assert page.evaluate("sessionStorage.getItem('askdnd-tour')") is None
    assert pinned(player.open(f"/characters/{server['cole']}/battle")) == before
    assert player.errors == []


def test_show_me_starts_at_its_group_and_esc_ends_it(people, server):
    player = people("player")
    page = player.open("/help?tab=adds")
    page.click('[data-tour-start="plan"]')
    page.wait_for_url(f"**/characters/{server['cole']}/plan")
    page.wait_for_selector(".tour-card")
    assert card_title(page) == "Battle combos" and lit(page)
    assert page.locator('[data-tab="t-combo"]').get_attribute("aria-selected") == "true"
    page.keyboard.press("ArrowRight")
    assert card_title(page) == "Leveling strategy"
    assert page.locator('[data-tab="t-leveling"]').get_attribute("aria-selected") == "true"
    page.keyboard.press("Escape")
    assert page.locator(".tour-card").count() == 0
    page.reload()  # ended means ended: it doesn't come back with the page
    page.wait_for_load_state("networkidle")
    assert page.locator(".tour-card").count() == 0
    assert player.errors == []
