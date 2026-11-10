"""Search, like Spotlight, in real pages (app/search.py, app.js "Search, like Spotlight"; Brett chose A and A, Nov 9):
⌘F or Ctrl+F opens the box from any page, results come as you type with the best one highlighted, Enter does the thing
(a check rolls in the roll window, a rule shows its words, a page opens), and ⌘F again gives the browser's own find."""


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
