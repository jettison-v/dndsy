"""Development's table (Work: app/fft/work_page.py): a row's menus open over the page, never behind the next row
(issue 47, Brett's round 14, Nov 20: the lane menu and ⋯ opened under the row below and couldn't be pressed)."""

from sqlalchemy import create_engine, text


def _plans(url, n=3):
    engine = create_engine(url)
    with engine.begin() as conn:
        item = conn.execute(text("INSERT INTO fft_items (title, place, section, standing, next_whose, next_step, workspace_id) VALUES ('A build', 1, 'now', false, '', '', 1) RETURNING id")).scalar()
        areas = []
        for i in range(n):
            a = conn.execute(text("INSERT INTO fft_areas (item_id, key, title, place, workspace_id) VALUES (:i, '', :t, :p, 1) RETURNING id"), {"i": item, "t": f"Plan {i + 1}", "p": i + 1}).scalar()
            conn.execute(text("INSERT INTO fft_issues (area_id, title, state, workspace_id) VALUES (:a, :t, 'to_fix', 1)"), {"a": a, "t": f"Something in plan {i + 1}"})
            areas.append(a)
    engine.dispose()
    return areas

def _on_top(page, locator):
    """The element at the middle of `locator` is it (or inside it): nothing covers it."""
    return locator.evaluate("el => { const r = el.getBoundingClientRect(); const at = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return !!at && (at === el || el.contains(at)); }")

def test_a_rows_lane_menu_and_more_menu_open_over_the_next_row(people, server, browser_db):
    first, _, _ = _plans(browser_db[0])
    admin = people("admin")
    page = admin.open("/manage/work")
    row = page.locator(f'tr.wk-plan[data-area="{first}"]')
    row.locator(".fft-lane > summary").click()
    page.locator(".act-menu.floats").wait_for()  # (placed over the page)
    pick = row.locator('[data-lane-pick="look"]')
    assert _on_top(page, pick), "the lane menu is under the next row"
    pick.click()
    page.locator(f'tr.wk-plan[data-area="{first}"] [data-lane-tag="look"]').wait_for()  # (the press went through)
    row = page.locator(f'tr.wk-plan[data-area="{first}"]')
    row.locator(".act-more:not(.fft-lane) > summary").click()
    page.locator(".act-menu.floats").wait_for()
    hold = row.locator('[data-do="hold"]')
    assert _on_top(page, hold), "⋯ is under the next row"
    box, screen = hold.bounding_box(), page.viewport_size
    assert box["x"] >= 0 and box["x"] + box["width"] <= screen["width"], "⋯ runs off the window"
    page.keyboard.press("Escape")
    assert not admin.errors, admin.errors


def test_a_scopes_two_answers_are_one_height(people, server, browser_db):
    """Issue 57 (Brett's round 15, Nov 20: "Buttons have strange heights"): Scope looks right took a panel's lone-button
    size beside Needs changes…; side by side, buttons are one height, and a line's Comment no taller than its words."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        item = conn.execute(text("INSERT INTO fft_items (title, place, section, standing, next_whose, next_step, workspace_id) VALUES ('An idea', 1, 'now', false, '', '', 1) RETURNING id")).scalar()
        conn.execute(text("INSERT INTO fft_scopes (item_id, version, what, inside, workspace_id) VALUES (:i, 1, 'What it is.', '[\"One line\", \"Another\"]', 1)"), {"i": item})
    engine.dispose()
    admin = people("admin")
    for width in (1280, 375):
        admin.page.set_viewport_size({"width": width, "height": 900})
        page = admin.open(f"/manage/roadmap/{item}")
        ok, changes = page.locator('[data-do="agree"]').bounding_box(), page.locator('[data-do="changes"]').bounding_box()
        assert abs(ok["height"] - changes["height"]) < 1, f"Scope looks right {ok['height']} px, Needs changes… {changes['height']} px at {width}"
        line = page.locator('[data-line="in:0"]').bounding_box()
        words = page.locator('[data-line="in:0"] .rm-line-text').bounding_box()
        if width >= 1000:  # (on a phone the Comment link keeps a tap target's height, as every small link does)
            assert line["height"] - words["height"] <= 12, f"a scope line is {line['height']} px for {words['height']} px of words at {width}"
    assert not admin.errors, admin.errors


def test_whats_in_claudes_hands_is_a_quiet_line_that_opens(people, server, browser_db):
    """Issue 21 (Brett's pick 1A on docs/mockups/fft-round-2/): "Claude missed" read as a problem. What's in Claude's
    hands is a quiet line under the status bar's top row, opening to the list; nothing is amber while it's fresh."""
    _plans(browser_db[0], n=2)  # (issues with no Feature yet: in Claude's hands)
    admin = people("admin")
    page = admin.open("/manage/work")
    line = page.locator('[data-stat="hands"]')
    assert line.locator("summary").bounding_box()["height"] < 30, "the line wraps"
    assert page.locator("[data-missed]").count() == 0  # (fresh: not late)
    line.locator("summary").click()
    assert line.locator('li[data-gap="no_feature"]').count() >= 2  # (this file's other tests may have left theirs)
    for li in line.locator("li").all():
        box = li.bounding_box()
        assert box["x"] + box["width"] <= page.viewport_size["width"], "a row spills past the window"
    if __import__("os").environ.get("SHOT"):
        page.screenshot(path="private/visual/hands-line.png")
    assert not admin.errors, admin.errors


def test_a_roadmap_items_more_menu_opens_toward_the_page(people, server, browser_db):
    """Issue 59 (Brett, Nov 20: "This menu is off the page"): a page's own ⋯ at its right end opens toward the page."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        item = conn.execute(text("INSERT INTO fft_items (title, place, section, standing, next_whose, next_step, workspace_id) VALUES ('An idea', 1, 'next', false, '', '', 1) RETURNING id")).scalar()
    engine.dispose()
    admin = people("admin")
    for width in (1280, 1728):
        admin.page.set_viewport_size({"width": width, "height": 900})
        page = admin.open(f"/manage/roadmap/{item}")
        page.locator(".title-row .act-more > summary").click()
        box = page.locator(".title-row .act-menu").bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= width, f"⋯ runs off the window at {width}"
    assert not admin.errors, admin.errors


def test_scope_it_on_a_roadmap_item_and_its_tabs(people, server, browser_db):
    """Issue 60 (Brett's picks Nov 21): an item with no scope offers Scope it; the press shows Claude scopes it next with
    Not now, and the tab bar shows each tab in place, keeping the open one in the address."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        item = conn.execute(text("INSERT INTO fft_items (title, place, section, standing, next_whose, next_step, workspace_id) VALUES ('Another idea', 2, 'next', false, '', '', 1) RETURNING id")).scalar()
    engine.dispose()
    admin = people("admin")
    admin.page.set_viewport_size({"width": 1280, "height": 800})
    page = admin.open(f"/manage/roadmap/{item}")
    page.locator('[data-do="scope-it"]').click()
    page.locator("[data-scope-asked]").wait_for()
    assert page.locator('[data-stage-word="asked"]').count() == 1
    page.locator('[role=tab][data-tab="t-updates"]').click()
    assert page.locator("#t-updates").is_visible() and not page.locator("#t-scope").is_visible()
    assert "tab=updates" in page.url
    page.locator('[role=tab][data-tab="t-scope"]').click()
    page.locator('[data-do="not-now"]').click()
    page.locator("[data-scope-none]").wait_for()
    assert not admin.errors, admin.errors


def test_a_jobs_runs_link_goes_to_github_and_its_window_is_compact(people, server, browser_db):
    """Issue 69 (Brett, round 17: "Clicking on its runs opens the right sidebar, but it looks like a link"): a link that
    opens a new tab, inside a row that opens a window, goes where it says. Issue 68 ("The spacing between the sections is
    very large for no clear reason"): the job window's sections are the item window's boxes, their labels tight."""
    admin = people("admin")
    page = admin.open("/manage/work?tab=scheduled")
    page.context.route("https://github.com/**", lambda r: r.fulfill(body="GitHub's runs", content_type="text/plain"))
    with page.context.expect_page() as opened:
        page.locator('tr[data-job="dependabot"] a[data-job-link]').click()
    gh = opened.value
    gh.wait_for_load_state()
    assert gh.url.startswith("https://github.com/jettison-v/dndsy/"), gh.url
    gh.close()
    assert page.locator(".peek [data-job-panel]").count() == 0, "the row's window opened too"
    page.locator('tr[data-job="nightly"] td').first.click()  # (the rest of the row still opens it)
    win = page.locator('.peek [data-job-panel="nightly"]')
    win.wait_for()
    sections = page.locator(".peek section.rd-sec")
    assert sections.count() == 4
    for s in sections.all():
        head = s.locator(".rd-sec-h")
        assert head.evaluate("h => getComputedStyle(h.querySelector('h3')).marginTop") == "0px"
        assert head.bounding_box()["height"] < 40, "a section's label carries a page heading's margin"
        first = s.locator(".rd-sec-in > *").first
        assert first.evaluate("el => getComputedStyle(el).marginTop") == "0px"
    assert not admin.errors, admin.errors
