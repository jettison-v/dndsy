"""A round of checks in a real browser (Found, Fixed, Tried: app/fft/testing_page.py, `_fft_card.html`; screens 2–4
of docs/mockups/found-fixed-tried/): ▶ Start round goes to the first check's page with the card on the left; P passes
and moves on, with Undo in the corner card; Something's wrong… is the note window as What's wrong?, and the card then
says the try failed with Next check →; End round ends it."""

import json
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.table_setup import plain_id

CHECK = (Path(__file__).parent / "layout_check.js").read_text()


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
    page = admin.open("/manage/for-you")
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
    page.wait_for_url("**/manage/for-you**")
    assert page.locator("[data-check-card]").count() == 0
    assert _one(browser_db[0], "SELECT count(*) FROM fft_rounds WHERE ended_at IS NULL") == [(0,)]
    assert not admin.errors, admin.errors


def test_testing_holds_together_at_every_width(people, server, browser_db):
    from tests.browser.test_layout import POLISH_FROM, problems

    _checks(browser_db[0], "/party")
    admin = people("admin")
    page, found = admin.page, []
    for width in (375, 768, 1280):
        page.set_viewport_size({"width": width, "height": 812 if width < 640 else 900})
        for path, said in (("/manage/for-you", "For you"), ("/manage/work", "Work")):
            admin.open(path)
            found += problems(page, f"{said} at {width}px", hard_only=width < POLISH_FROM)  # (admin pages: polish is the weekly sweep's)
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
    admin.open("/manage/for-you")
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
        admin.open("/manage/for-you")
        page.locator('[data-do="start-round"]').click()
        page.wait_for_url("**/party")
        page.locator(f'[data-check-card="{first}"]').wait_for()
        page.keyboard.press("p")
        page.wait_for_url("**/help")
        page.locator(f'[data-check-card="{second}"]').wait_for()
        page.keyboard.press("p")
        page.wait_for_url("**/manage/for-you**")
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
        page.wait_for_url("**/manage/for-you**")
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


def test_counts_never_blink_between_manage_pages(people, server, browser_db):
    """Issue 46 (Brett, Nov 19: Manage's list redrew its counts on every click, so they blinked out and back): the
    counts this tab last heard show at once on the next page, before their fresh answer comes."""
    import time

    _checks(browser_db[0], "/party")
    admin = people("admin")
    page = admin.open("/manage/feedback")
    side = '.manage-side [data-manage-count="for-you"]'
    page.wait_for_function(f"() => !document.querySelector('{side}').hidden")
    page.wait_for_function("() => !document.querySelector('[data-for-you-count]').hidden")

    def slow(route):
        time.sleep(1.5)
        route.continue_()

    page.route("**/manage/counts", slow)
    page.route("**/manage/for-you/count", slow)
    page.goto(server["base"] + "/manage/documents", wait_until="domcontentloaded")
    assert page.evaluate(f"() => !document.querySelector('{side}').hidden && !document.querySelector('[data-for-you-count]').hidden")
    page.unroute("**/manage/counts")
    page.unroute("**/manage/for-you/count")
    assert not admin.errors, admin.errors


def test_the_status_bar_and_a_build_batchs_menu_hold_together(people, server, browser_db):
    """Issue 38 (Brett, Nov 19): a grey part of the status bar moves to the next line whole, never split; and a build
    batch's ⋯ stays at its row's right end, never on a line of its own under its Features."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        item = conn.execute(text("INSERT INTO fft_items (title, place, section, standing, next_whose, next_step, workspace_id) "
                                 "VALUES ('Items that bring a creature', 5, 'next', false, '', '', 1) RETURNING id")).scalar()
        area = conn.execute(text("INSERT INTO fft_areas (item_id, key, title, place, workspace_id) VALUES (:i, '', 'Item Builder', 1, 1) RETURNING id"),
                            {"i": item}).scalar()
        conn.execute(text("INSERT INTO fft_issues (title, state, area_id, feature, from_player, reopened, workspace_id) "
                          "VALUES ('A long name wraps', 'to_fix', :a, 'homebrew', false, 0, 1)"), {"a": area})
        conn.execute(text("INSERT INTO fft_listeners (name, heard_at, workspace_id) VALUES ('main', now(), 1) ON CONFLICT DO NOTHING"))
        conn.execute(text("INSERT INTO tool_settings (key, value) VALUES ('fft_available', :v) ON CONFLICT (key) DO UPDATE SET value = :v"),
                     {"v": json.dumps({"by": "Dev", "actor": "user:0", "since": "2099-01-01T00:00:00+00:00", "until": "2099-01-01T02:00:00+00:00"})})
    engine.dispose()
    admin = people("admin")
    page = admin.page
    for width in (1000, 1280):
        page.set_viewport_size({"width": width, "height": 900})
        admin.open("/manage/work?tab=queue")
        row = page.locator(f'tr[data-area="{area}"]')
        menu, lane = row.locator(".act-more:not(.fft-lane) summary"), row.locator(".fft-lane > summary")
        m, o = menu.bounding_box(), lane.bounding_box()
        assert abs((m["y"] + m["height"] / 2) - (o["y"] + o["height"] / 2)) < 6 and m["x"] > o["x"], f"⋯ off its row at {width}px"
        bar = [x for x in page.evaluate(CHECK, {}) if "fft-status" in x["where"]]  # (Nov 19: squeezed, off baseline)
        assert not bar, f"the status bar at {width}px: {bar}"
        _deploys_on_one_row(page, width)
        for grey in page.locator(".fft-status .note:visible").all():
            tops = grey.evaluate("e => [...e.getClientRects()].map(r => Math.round(r.top))")
            assert max(tops) - min(tops) < 4, f"a grey part split over lines at {width}px: {tops}"
    assert not admin.errors, admin.errors


def _deploys_on_one_row(page, width):
    """Brett's pick A on issue 42: the bar's top row never wraps, Deploys is one pill at its right end that never
    shortens (the grey note beside Claude is listening does first), and its menu opens on the page with three choices."""
    top, pill = page.locator(".fft-status-top").bounding_box(), page.locator(".fft-deploys > summary").bounding_box()
    listen = page.locator(".fft-listening").bounding_box()
    assert abs((listen["y"] + listen["height"] / 2) - (pill["y"] + pill["height"] / 2)) < 6 and pill["height"] < 40, f"the top row wrapped at {width}px"
    bar = page.locator(".fft-status").bounding_box()
    assert bar["x"] + bar["width"] - (pill["x"] + pill["width"]) < 30, f"Deploys isn't at the bar's right end at {width}px"
    assert page.locator(".fft-deploys-pill").evaluate("e => e.scrollWidth <= e.clientWidth + 1"), f"Deploys shortened at {width}px"
    page.locator(".fft-deploys > summary").click()
    menu = page.locator(".fft-deploys-menu")
    m = menu.bounding_box()
    assert menu.is_visible() and m["x"] >= 0 and m["x"] + m["width"] <= width, f"Deploys' menu off the page at {width}px"
    assert menu.locator("[data-mode-pick]").count() == 3 and menu.locator("[data-mode-pick] small").count() == 3  # (each says what it does)
    page.locator(".fft-deploys > summary").click()
    assert top["height"] < 64


def test_an_open_round_has_its_own_row_under_the_bar(people, server, browser_db):
    """Brett's pick on issue 41 (Nov 19): the bar wrapped by how long its left words were, so it moved when a round
    opened. Now its top row (Claude listening; Deploys) stays where it was, and an open round is a row of its own under
    it with End round."""
    admin = people("admin")
    page = admin.page
    for width in (1000, 1280):
        page.set_viewport_size({"width": width, "height": 900})
        admin.open("/manage/work?tab=queue")
        def where():  # (the pill against its bar's right end, where it sits: a scrollbar the round's row brings narrows
            # the bar, so from its left the pill seemed to move 13 px; Nov 20, main's run after PR 449)
            p, b = page.locator(".fft-deploys > summary").bounding_box(), page.locator(".fft-status").bounding_box()
            return {"x": (b["x"] + b["width"]) - (p["x"] + p["width"]), "y": p["y"] - b["y"], "height": p["height"], "top": p["y"]}
        before = where()
        engine = create_engine(browser_db[0])
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO fft_rounds (workspace_id) VALUES (1)"))
        engine.dispose()
        admin.open("/manage/work")
        after, row = where(), page.locator(".fft-status-round").bounding_box()
        assert abs(after["y"] - before["y"]) < 2 and abs(after["x"] - before["x"]) < 2, f"the top row moved at {width}px"
        assert row["y"] >= after["top"] + after["height"] and page.locator('.fft-status-round [data-do="end-round"]').is_visible()
        bar = [x for x in page.evaluate(CHECK, {}) if "fft-status" in x["where"]]
        assert not bar, f"the status bar at {width}px: {bar}"
        engine = create_engine(browser_db[0])
        with engine.begin() as conn:
            conn.execute(text("UPDATE fft_rounds SET ended_at = now() WHERE ended_at IS NULL"))
        engine.dispose()


def test_a_long_pause_reason_has_its_own_line_whole(people, server, browser_db):
    """Brett's comment on the Status Bar Redesign (issue 42): "The paused reason can have its full own line." The top
    row stays one row; the reason, however long, is whole under it."""
    reason = "a demo for the table tomorrow evening, keep everything exactly as it is until we're done, thank you all"
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO tool_settings (key, value) VALUES ('fft_freeze', :v) ON CONFLICT (key) DO UPDATE SET value = :v"),
                     {"v": json.dumps({"by": "Dev", "since": "2026-11-19T20:00:00+00:00", "why": reason})})
    admin = people("admin")
    page = admin.page
    try:
        for width in (1000, 1280):
            page.set_viewport_size({"width": width, "height": 900})
            admin.open("/manage/for-you")
            _deploys_on_one_row(page, width)
            line = page.locator('.fft-status-line[data-stat="paused"]')
            assert line.is_visible() and line.locator("span").first.evaluate("e => e.scrollWidth <= e.clientWidth + 1")
            assert not [x for x in page.evaluate(CHECK, {}) if "fft-status" in x["where"]]
    finally:
        engine = create_engine(browser_db[0])
        with engine.begin() as conn:
            conn.execute(text("UPDATE tool_settings SET value = '' WHERE key = 'fft_freeze'"))
        engine.dispose()


def test_on_a_phone_the_bar_wraps_deploys_under_listening(people, server, browser_db):
    """At 375px the top row can't hold both: Claude listening keeps its line and Deploys goes whole under it, never over
    it (seen in the before-and-after pictures, Nov 19)."""
    admin = people("admin")
    page = admin.page
    page.set_viewport_size({"width": 375, "height": 812})
    admin.open("/manage/work")
    said, pill = page.locator(".fft-listening-said").bounding_box(), page.locator(".fft-deploys > summary").bounding_box()
    assert pill["y"] >= said["y"] + said["height"] - 1, "Deploys sits over Claude listening on a phone"
    assert pill["x"] + pill["width"] <= 375 and page.locator(".fft-deploys-pill").evaluate("e => e.scrollWidth <= e.clientWidth + 1")  # (on the screen, whole: its words may wrap)


def test_for_you_opens_a_check_in_the_item_window_and_passed_moves_on(people, server, browser_db):
    """The Work Pages (Brett, Nov 20): For you is a table; a row opens its check in the item window, ✓ Passed looks like
    its neighbours until pressed (issue 45), and after it the window moves on to the next check, the row gone."""
    first, _second = _checks(browser_db[0], "/party", "/help")
    admin = people("admin")
    page = admin.open("/manage/for-you")
    page.locator(f'tr[data-row="c{first}"] td.dt-title').click()
    win = page.locator(f'#peek [data-item-panel="c{first}"]')
    win.wait_for()
    passed = page.locator('#peek [data-do="passed"]')
    wrong = page.locator('#peek [data-do="wrong"]')
    look = "el => getComputedStyle(el).backgroundColor"
    assert passed.evaluate(look) == wrong.evaluate(look)  # (issue 45: no green before it's pressed)
    nxt = page.locator("#peek [data-next-url]").get_attribute("data-next-url")  # (the next row: a check another test left may come first)
    key = nxt.split("/manage/item/")[1].split("?")[0]
    assert key != f"c{first}" and f'data-row="{key}"' in page.content()
    passed.click()
    page.locator(f'#peek [data-item-panel="{key}"]').wait_for()  # (on to the next)
    page.wait_for_function(f"() => !document.querySelector('tr[data-row=\"c{first}\"]')")
    assert _one(browser_db[0], "SELECT result FROM fft_tries WHERE check_id = :c ORDER BY id DESC LIMIT 1", c=first) == [("passed",)]
    assert not admin.errors, admin.errors


def test_try_it_in_the_item_window_takes_you_to_the_checks_page(people, server, browser_db):
    """▶ Try it, pressed in the item window, goes to the check's own page with its card, as from the list."""
    first, = _checks(browser_db[0], "/help")
    admin = people("admin")
    page = admin.open(f"/manage/for-you?open=c{first}")
    page.locator(f'#peek [data-item-panel="c{first}"]').wait_for()
    page.locator('#peek [data-do="try-it"]').click()
    page.wait_for_url("**/help**")
    assert not admin.errors, admin.errors
