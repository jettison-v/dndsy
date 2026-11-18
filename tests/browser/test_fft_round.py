"""A round of checks in a real browser (Found, Fixed, Tried: app/fft/testing_page.py, `_fft_card.html`; screens 2–4
of docs/mockups/found-fixed-tried/): ▶ Start round goes to the first check's page with the card on the left; P passes
and moves on, with Undo in the corner card; Something's wrong… is the note window as What's wrong?, and the card then
says the try failed with Next check →; End round ends it."""

import json

import pytest
from sqlalchemy import create_engine, text

from tests.table_setup import plain_id


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


def _long_check(url):
    """One check with many long steps, first in a round (place -1; Brett's round, Nov 18, issue 15: a check this long ran off the top of the screen)."""
    engine = create_engine(url)
    with engine.begin() as conn:
        cid = conn.execute(text("INSERT INTO fft_checks (title, version, devices, minutes, place, preflight, workspace_id) "
                                "VALUES ('A check with a long walkthrough', 1, CAST(:d AS jsonb), 5, -1, 'passed', 1) RETURNING id"),
                           {"d": json.dumps(["laptop"])}).scalar()
        steps = [f"Step {n}: open the page, look along the row of buttons beside the heading and press the one that "
                 f"says what this step is about, then read what comes up." for n in range(1, 15)]
        conn.execute(text("INSERT INTO fft_check_versions (check_id, version, path, steps, expect, why, workspace_id) "
                          "VALUES (:c, 1, '/party', CAST(:s AS jsonb), :e, '', 1)"),
                     {"c": cid, "s": json.dumps(steps), "e": "Every step shows what it says, in order, and nothing else moves. " * 3})
    engine.dispose()
    return cid


@pytest.mark.parametrize("size,corner", [((1440, 800), "bl"), ((1440, 800), "tr"), ((1280, 720), "br"), ((375, 700), "bl"), ((375, 700), "tl")],
                         ids=plain_id)
def test_a_long_check_stays_on_screen_with_its_buttons_in_sight(people, server, browser_db, size, corner):
    """Issue 15 (Brett's round, Nov 18): a check with a long walkthrough grew taller than the screen and its top was cut
    off. The card is never taller than the space between the menu bar and the foot of the screen (the bottom menu on a
    phone): its steps scroll inside it, and its buttons stay in sight at its foot."""
    cid = _long_check(browser_db[0])
    try:
        _long_check_on_screen(people, server, cid, size, corner)
    finally:  # (the file shares one database: leave no check or round for the next case)
        engine = create_engine(browser_db[0])
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM fft_checks WHERE id = :c"), {"c": cid})
            conn.execute(text("UPDATE fft_rounds SET ended_at = now() WHERE ended_at IS NULL"))
        engine.dispose()


def _long_check_on_screen(people, server, cid, size, corner):
    admin = people("admin")
    page = admin.page
    page.set_viewport_size({"width": size[0], "height": size[1]})
    admin.context.add_cookies([{"name": "askdnd-cc", "value": f"open.{corner}", "url": server["base"]}])
    admin.open("/manage/testing")
    page.locator('[data-do="start-round"]').click()
    page.wait_for_url("**/party")
    card = page.locator(f'[data-check-card="{cid}"]')
    card.wait_for()
    got = page.evaluate("""() => {
      const card = document.querySelector('[data-check-card]'), r = card.getBoundingClientRect();
      const bar = document.querySelector('.topbar').getBoundingClientRect();
      const nav = document.querySelector('.bottom-nav'), navTop = nav && nav.checkVisibility() ? nav.getBoundingClientRect().top : innerHeight;
      const pass = card.querySelector('[data-do="passed"]').getBoundingClientRect();
      const hit = document.elementFromPoint(pass.left + pass.width / 2, pass.top + pass.height / 2);
      const body = card.querySelector('.cc-body');
      return {top: r.top, bottom: r.bottom, barBottom: bar.bottom, navTop, passBottom: pass.bottom,
              hitPass: !!(hit && hit.closest('[data-do="passed"]')), scrolls: body.scrollHeight > body.clientHeight + 1};
    }""")
    assert got["top"] >= got["barBottom"], got  # (never under the menu bar)
    assert got["bottom"] <= got["navTop"] and got["bottom"] <= size[1], got  # (never under the bottom menu or off the foot)
    assert got["hitPass"], got  # (✓ Passed is in sight, nothing on top of it)
    assert got["scrolls"], got  # (the steps scroll inside the card)
    last = card.locator(".walk li").last
    last.scroll_into_view_if_needed()
    assert last.is_visible() and page.evaluate("""() => { const p = document.querySelector('[data-check-card] [data-do="passed"]').getBoundingClientRect();
      const hit = document.elementFromPoint(p.left + p.width / 2, p.top + p.height / 2); return !!(hit && hit.closest('[data-do="passed"]')); }""")
    card.locator(".cc-top [data-cc-fold]").click()  # — folds it to its pill, which clears the bottom menu too
    pill = card.locator(".cc-pill")
    pill.wait_for()
    box = pill.bounding_box()
    nav_top = page.evaluate("() => { const n = document.querySelector('.bottom-nav'); return n && n.checkVisibility() ? n.getBoundingClientRect().top : innerHeight; }")
    assert box["y"] + box["height"] <= nav_top, (box, nav_top)
    pill.click()  # (open again: the same, its buttons in sight)
    card.locator('[data-do="passed"]').wait_for()
    assert card.evaluate("c => c.getBoundingClientRect().top") >= page.evaluate("() => document.querySelector('.topbar').getBoundingClientRect().bottom")
    assert not admin.errors, admin.errors


@pytest.mark.parametrize("size,corner", [((1440, 800), "bl"), ((1440, 800), "br"), ((375, 700), "bl"), ((375, 700), "br")], ids=plain_id)
def test_after_the_last_check_the_round_waits_for_end_round(people, server, browser_db, size, corner):
    """Issue 28 (Brett's round, Nov 18): the round ended by itself after the last check, so End round was nowhere to be
    found. Now the last check takes you to Testing with a corner card saying so, the round's card says it's still open
    with End round on it, and the round ends only when you press it."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:  # (the file shares one database: only this case's two checks are in its round)
        conn.execute(text("UPDATE fft_checks SET retired = true"))
    engine.dispose()
    first, second = _checks(browser_db[0], "/party", "/help")
    try:
        admin = people("admin")
        page = admin.page
        page.set_viewport_size({"width": size[0], "height": size[1]})
        admin.context.add_cookies([{"name": "askdnd-cc", "value": f"open.{corner}", "url": server["base"]}])
        admin.open("/manage/testing")
        page.locator('[data-do="start-round"]').click()
        page.wait_for_url("**/party")
        page.locator(f'[data-check-card="{first}"]').wait_for()
        page.keyboard.press("p")
        page.wait_for_url("**/help")
        page.locator(f'[data-check-card="{second}"]').wait_for()
        page.keyboard.press("p")
        page.wait_for_url("**/manage/testing**")
        done = page.locator("[data-round-done]")
        done.wait_for()
        page.locator("#cards > .card").first.wait_for()  # (Passed, with Undo)
        page.wait_for_function("() => document.getAnimations().every(a => a.playState !== 'running')")
        apart = page.evaluate("""() => { const c = document.querySelector('#cards > .card').getBoundingClientRect(),
          r = document.querySelector('[data-round-done]').getBoundingClientRect();
          return c.bottom <= r.top || c.right <= r.left || c.left >= r.right; }""")
        assert apart, page.evaluate("() => [getComputedStyle(document.documentElement).getPropertyValue('--cc-h'), getComputedStyle(document.querySelector('#cards')).bottom, document.querySelector('#check-card').getBoundingClientRect().toJSON(), document.querySelector('#cards > .card').getBoundingClientRect().toJSON(), document.querySelector('[data-round-done]').dataset.corner]")  # (corner cards stack above the round's card, never over it; on a phone too)
        assert _one(browser_db[0], "SELECT count(*) FROM fft_rounds WHERE ended_at IS NULL") == [(1,)]
        end = done.locator('[data-do="end-round"]')
        assert end.is_visible()
        done.locator(".cc-top [data-cc-fold]").click()  # (it folds like the round's card: the review of #417)
        done.locator(".cc-pill").wait_for()
        done.locator(".cc-pill").click()
        end.wait_for()
        end.click()
        page.wait_for_url("**/manage/testing**")
        page.wait_for_function("() => !document.querySelector('[data-round-done]')")
        page.locator("#cards > .card").first.wait_for()  # (a corner card says it ended: Claude may merge again)
        assert page.locator('[data-do="end-round"]').count() == 0
        assert _one(browser_db[0], "SELECT count(*) FROM fft_rounds WHERE ended_at IS NULL") == [(0,)]
        assert not admin.errors, admin.errors
    finally:
        engine = create_engine(browser_db[0])
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM fft_checks WHERE id IN (:a, :b)"), {"a": first, "b": second})
            conn.execute(text("UPDATE fft_rounds SET ended_at = now() WHERE ended_at IS NULL"))
        engine.dispose()
