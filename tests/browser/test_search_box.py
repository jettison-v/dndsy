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
