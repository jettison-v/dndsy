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
