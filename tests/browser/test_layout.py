"""Every page holds together at phone, tablet, in-between and wide widths (docs/DESIGN.md › Narrow screens): nothing
scrolls sideways, spills out of its box, breaks a one-line control onto two lines, or overlaps in the menu bar
(tests/browser/layout_check.js). With long names on purpose, since real names are what break layouts. Each page's
tabs, the menu bar's menus and Battle's side panel are checked too."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

CHECK = (Path(__file__).parent / "layout_check.js").read_text()

WIDTHS = (375, 768, 1000, 1280)
PAGES = {
    "player": ("/c/main/", "/c/main/?tab=sessions", "/c/main/campaign", "/characters/{cole}/battle", "/characters/{cole}",
               "/characters/{cole}/plan", "/party", "/help", "/your-suggestions"),
    "admin": tuple(f"/c/main/manage{p}" for p in ("", "/inbox", "/sessions", "/table", "/house-rules", "/history", "/settings",
                                                  "/dm-guide"))
             + tuple(f"/manage/{p}" for p in ("campaigns", "accounts", "tool-corrections", "usage", "backups", "history",
                                               "design", "dice")),
}


@pytest.fixture(scope="module")
def long_names(browser_db):
    """A campaign and a character with the long names a real table might pick."""
    url, ids = browser_db
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE campaigns SET name = 'The Adventure Begins Beneath the Sunless Citadel' WHERE id = :c"), {"c": ids["campaign"]})
        conn.execute(text("UPDATE characters SET name = 'Coleridge Thistlewood' WHERE id = :c"), {"c": ids["cole"]})
    engine.dispose()


def problems(page, where: str) -> list[str]:
    return [f"{where} · {p['kind']}: {p['where']} ({p['detail']})" for p in page.evaluate(CHECK)]


def check(person, server, paths) -> list[str]:
    page, found = person.page, []
    for width in WIDTHS:
        page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        for path in paths:
            path = path.format(cole=server["cole"])
            person.open(path)
            page.wait_for_load_state("load")
            found += problems(page, f"{path} at {width}px")
            tabs = page.locator("main [role=tab]:visible")
            for k in range(tabs.count()):
                tabs.nth(k).click()
                found += problems(page, f"{path} › {tabs.nth(k).inner_text().split(chr(10))[0]} at {width}px")
        for opener in page.locator(".topbar [data-menu]:visible").all():  # the menu bar's menus
            opener.click()
            page.wait_for_timeout(300)
            found += problems(page, f"menu {opener.get_attribute('data-menu')} at {width}px")
            page.keyboard.press("Escape")
            page.mouse.click(2, 400)
    return found


def test_a_players_pages_hold_together_at_every_width(people, server, long_names):
    player = people("player")
    found = check(player, server, PAGES["player"])
    player.open(f"/characters/{server['cole']}/battle")  # Battle's side panel (+ Add)
    for width in WIDTHS:
        player.page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        player.page.locator(".head-add:visible").first.click()
        player.page.wait_for_selector(".peek.open")
        player.page.wait_for_timeout(300)
        found += problems(player.page, f"+ Add panel at {width}px")
        player.page.keyboard.press("Escape")
    assert not found, "\n".join(found)
    assert player.errors == []


def test_manage_pages_hold_together_at_every_width(people, server, long_names):
    admin = people("admin")
    found = check(admin, server, PAGES["admin"])
    assert not found, "\n".join(found)
    assert admin.errors == []
