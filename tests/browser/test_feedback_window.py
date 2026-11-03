"""Feedback for Claude in a real page (app/feedback.py, app.js "feedback for Claude"; Brett, 2026-11-03,
docs/mockups/feedback-queue/): \\ opens the window with the page's picture already taken, Point at it marks a thing on
the page, and Send puts the note in the queue with where, when and how the page was."""

from sqlalchemy import create_engine, text


def test_backslash_point_and_send(people, server, browser_db):
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.wait_for_load_state("networkidle")
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    win.wait_for(state="visible", timeout=5000)
    page.locator("[data-fb-shot]").wait_for(state="visible", timeout=15000)  # the page's picture, taken as it opened
    page.fill("#fb-win textarea[name=text]", "Speed should show the swim speed too.")
    page.click("[data-fb-point]")
    page.locator("#fb-win").wait_for(state="hidden", timeout=5000)
    page.click("h1")  # (pointing: the next click marks it)
    win.wait_for(state="visible", timeout=5000)
    assert "Pointed at" in page.locator("[data-fb-pointed]").inner_text()
    page.click("[data-fb-send]")
    page.locator("#cards > .card", has_text="In the queue").wait_for(timeout=10000)
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        row = conn.execute(text("SELECT text, context, shot_key, length(html) FROM feedback ORDER BY id DESC LIMIT 1")).one()
    engine.dispose()
    words, ctx, shot, html = row
    assert words == "Speed should show the swim speed too." and shot and html > 1000
    assert ctx["window"] and ctx["browser"] and ctx["pointed"]["label"] and ctx["signed_in_as"].endswith("(admin)")
    page.keyboard.press("\\")  # (again, in a field: typing a backslash there never opens it)
    win.wait_for(state="visible", timeout=5000)
    page.fill("#fb-win textarea[name=text]", "a \\ b")
    assert page.locator("#fb-win textarea[name=text]").input_value() == "a \\ b"
    assert not admin.errors, admin.errors
