"""Search, like Spotlight, in real pages (app/search.py, app.js "Search, like Spotlight"; Brett chose A and A, Nov 9):
⌘F or Ctrl+F opens the box from any page, results come as you type with the best one highlighted, Enter does the thing
(a check rolls in the roll window, a rule shows its words, a page opens), and ⌘F again gives the browser's own find."""

import time

from tests.browser.test_roll_card import _pieces

SERVER_ENV = {"DDB_BRIDGE": "1"}  # (Cast is offered where the bridge runs: on beta and askdnd.ai)


def test_ctrl_f_finds_and_enter_does_it(people, server):
    player = people("player")
    page = player.open("/")
    page.wait_for_load_state("networkidle")
    box = page.locator("#search-box")
    page.keyboard.press("ControlOrMeta+f")
    box.wait_for(state="visible")
    page.keyboard.type("stealth")
    page.locator(".search-res.on", has_text="Stealth check").wait_for()
    page.keyboard.press("Enter")
    page.locator(".roll-win").wait_for()
    assert "Stealth check" in page.locator(".roll-win").inner_text() and box.is_hidden()
    page.keyboard.press("Escape")
    page.locator(".roll-win").wait_for(state="hidden")

    page.locator("[data-search-open]").click()  # (the button in the menu bar does the same)
    box.wait_for(state="visible")
    page.keyboard.type("prone")
    page.keyboard.press("Enter")
    assert "Disadvantage" in page.locator("#search-read").inner_text() and box.is_visible()  # (a rule's words, in the box)
    page.keyboard.press("ControlOrMeta+f")  # (again: the browser's own find, this time)
    box.wait_for(state="hidden")
    page.keyboard.press("ControlOrMeta+f")
    assert box.is_hidden()

    page.keyboard.press("ControlOrMeta+k")  # (⌘K always opens it)
    box.wait_for(state="visible")
    page.keyboard.type("party")
    with page.expect_navigation():
        page.keyboard.press("Enter")
    assert page.url.endswith("/party") and player.errors == []


def test_clicking_a_result_does_it_too(people, server):
    """Brett, Nov 9: a click did nothing where Enter worked. What a click opens must not hear that same click as one
    outside it (and close): a check's roll window stays open, a page opens."""
    player = people("player")
    page = player.open("/")
    page.wait_for_load_state("networkidle")
    page.locator("[data-search-open]").click()
    page.locator("#search-box").wait_for(state="visible")
    page.fill("#search-q", "stealth")
    page.locator(".search-res", has_text="Stealth check").click()
    page.locator(".roll-win", has_text="Stealth check").wait_for()
    page.wait_for_timeout(300)  # (a moment later, still open)
    assert page.locator(".roll-win", has_text="Stealth check").is_visible()
    page.keyboard.press("Escape")
    page.locator("[data-search-open]").click()
    page.fill("#search-q", "party")
    with page.expect_navigation():
        page.locator(".search-res", has_text="Party").first.click()
    assert page.url.endswith("/party") and player.errors == []


def test_cast_opens_where_it_can_be_seen(people, server, browser_db):
    """Brett, Nov 9: on Story a Cast result seemed to do nothing. Its window's words arrive after Search's button for the
    moment is gone, so it was drawn at the foot of the page, out of sight on a long one; it opens under the box."""
    was = _pieces(browser_db, server, ["sync"])  # (Cast is offered where askdnd plays the sheet)
    try:
        player = people("player")
        for _ in range(20):  # (the server keeps a campaign's switches for a few seconds)
            page = player.open("/")
            page.wait_for_load_state("networkidle")
            spell = page.evaluate("fetch('/search/index').then(r => r.json()).then(d => (d.rows.find(r => r.a === 'Cast') || {}).n)")
            if spell:
                break
            time.sleep(0.5)
        assert spell
        page.locator("[data-search-open]").click()
        page.fill("#search-q", spell)
        page.locator(".search-res", has_text=spell).first.click()
        win = page.locator(".roll-win", has_text=spell)
        win.wait_for()
        page.wait_for_timeout(300)
        at = win.bounding_box()
        assert at and 0 <= at["y"] < 200, at  # (just under where the box was, whatever the page's length)
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)
