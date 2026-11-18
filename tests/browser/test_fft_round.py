"""A round of checks in a real browser (Found, Fixed, Tried: app/fft/testing_page.py, `_fft_card.html`; screens 2–4
of docs/mockups/found-fixed-tried/): ▶ Start round goes to the first check's page with the card on the left; P passes
and moves on, with Undo in the corner card; Something's wrong… is the note window as What's wrong?, and the card then
says the try failed with Next check →; End round ends it."""

import json

from sqlalchemy import create_engine, text


def _checks(url, *pages):
    engine = create_engine(url)
    ids = []
    with engine.begin() as conn:
        for n, path in enumerate(pages):
            cid = conn.execute(text("INSERT INTO fft_checks (title, version, devices, minutes, place, preflight, workspace_id) "
                                    "VALUES (:t, 1, CAST(:d AS jsonb), 2, :p, 'passed', 1) RETURNING id"),
                               {"t": f"Check on {path}", "d": json.dumps(["laptop"]), "p": n}).scalar()
            conn.execute(text("INSERT INTO fft_check_versions (check_id, version, path, steps, expect, why, workspace_id) "
                              "VALUES (:c, 1, :path, CAST(:s AS jsonb), 'It shows.', '', 1)"),
                         {"c": cid, "path": path, "s": json.dumps(["Look at the page.", "Press [Rest]."])})
            ids.append(cid)
    engine.dispose()
    return ids


def _one(url, sql, **params):
    engine = create_engine(url)
    with engine.connect() as conn:
        got = conn.execute(text(sql), params).all()
    engine.dispose()
    return got


def test_a_round_page_to_page_with_its_card(people, server, browser_db):
    first, second = _checks(browser_db[0], "/party", "/help")
    admin = people("admin")
    page = admin.open("/manage/testing")
    page.locator('[data-do="start-round"]').click()
    page.wait_for_url("**/party")
    card = page.locator(f'[data-check-card="{first}"]')
    card.wait_for()
    assert card.get_attribute("data-corner") == "bl" and card.locator(".walk li").count() == 2  # (left by default)

    page.keyboard.press("p")  # P: passed, and on to the next check's page
    page.wait_for_url("**/help")
    page.locator(f'[data-check-card="{second}"]').wait_for()
    undo = page.locator("#cards > .card", has=page.locator(".card-act"))
    undo.wait_for()
    undo.locator(".card-act").click()  # Undo: back to the first
    page.wait_for_url("**/party")
    page.locator(f'[data-check-card="{first}"]').wait_for()
    assert _one(browser_db[0], "SELECT result FROM fft_tries WHERE check_id = :c AND NOT replaced ORDER BY id DESC LIMIT 1", c=first) == [("untried",)]

    page.keyboard.press("f")  # F: Something's wrong… as What's wrong?
    win = page.locator("#fb-win")
    win.wait_for(state="visible")
    assert win.locator("[data-fb-wrong]").first.is_visible() and win.locator("[data-fb-kind-row]").is_hidden()
    page.fill("#fb-win textarea[name=text]", "The heading wraps.")
    page.click("[data-fb-send]")  # (whether it stops the check: picked each time)
    win.locator("[data-fb-said]").wait_for(state="visible")
    page.click('[data-fb-block="yes"]')
    page.click("[data-fb-send]")
    page.locator(f'[data-check-card="{first}"] [data-cc-failed]').wait_for()
    assert _one(browser_db[0], "SELECT result FROM fft_tries WHERE check_id = :c AND NOT replaced ORDER BY id DESC LIMIT 1", c=first) == [("failed",)]
    (words,), = _one(browser_db[0], "SELECT n.text FROM fft_notes n JOIN fft_tries t ON t.id = n.try_id WHERE t.check_id = :c", c=first)
    assert words == "The heading wraps."

    page.locator('[data-check-card] [data-do="next"]').click()
    page.wait_for_url("**/help")
    page.locator('[data-check-card] [data-do="end-round"]').click()
    page.wait_for_url("**/manage/testing**")
    assert page.locator("[data-check-card]").count() == 0
    assert _one(browser_db[0], "SELECT count(*) FROM fft_rounds WHERE ended_at IS NULL") == [(0,)]
    assert not admin.errors, admin.errors


def test_testing_holds_together_at_every_width(people, server, browser_db):
    from tests.browser.test_layout import problems

    _checks(browser_db[0], "/party")
    admin = people("admin")
    page, found = admin.page, []
    for width in (375, 768, 1280):
        page.set_viewport_size({"width": width, "height": 812 if width < 640 else 900})
        admin.open("/manage/testing")
        found += problems(page, f"Testing at {width}px")
    assert not found, "\n".join(found)
    assert not admin.errors, admin.errors
