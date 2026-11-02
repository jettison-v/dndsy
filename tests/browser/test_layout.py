"""Every page holds together at phone, tablet, in-between and wide widths (docs/DESIGN.md › Narrow screens): nothing
scrolls sideways, spills out of its box, breaks a one-line control onto two lines, or overlaps in the menu bar
(tests/browser/layout_check.js). With long names on purpose, since real names are what break layouts. Each page's
tabs, the menu bar's menus and Battle's side panel are checked too."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.browser.conftest import Person

CHECK = (Path(__file__).parent / "layout_check.js").read_text()

WIDTHS = (375, 768, 1000, 1280)
PAGES = {
    "player": ("/c/main/", "/c/main/?tab=sessions", "/c/main/campaign", "/characters/{cole}/battle", "/characters/{cole}",
               "/characters/{cole}/plan", "/party", "/help", "/your-suggestions"),
    "admin": tuple(f"/c/main/manage{p}" for p in ("", "/inbox", "/sessions", "/table", "/house-rules", "/history", "/settings",
                                                  "/dm-guide"))
             + tuple(f"/manage/{p}" for p in ("askdnd", "campaigns", "accounts", "tool-corrections", "usage", "backups", "history",
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


def check(person, server, paths, widths=WIDTHS) -> list[str]:
    page, found = person.page, []
    for width in widths:
        if page.viewport_size["width"] != width:
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


# Safari's engine as Brett's iPhone and an iPad draw them (Playwright's own settings for each: size, touch, Safari's
# user agent). Every browser on an iPhone is WebKit underneath, so a page that holds together in Chromium can still
# break there (fonts, form controls, flex and grid details).
SAFARI = {375: "iPhone 13 Mini", 768: "iPad Mini"}


@pytest.mark.parametrize("who", ["player", "admin"])
def test_pages_hold_together_in_safari_on_a_phone_and_a_tablet(webkit, playwright, server, long_names, who):
    found = []
    for width, device in SAFARI.items():
        person = Person(webkit, server, who, **{k: v for k, v in playwright.devices[device].items() if k != "default_browser_type"})
        try:
            found += [f"Safari · {f}" for f in check(person, server, PAGES[who], widths=(width,))]
            assert person.errors == [], person.errors
        finally:
            person.context.close()
    assert not found, "\n".join(found)


def test_a_long_group_of_resources_fits_a_phone(people, server):
    """Oct 31: Eldritch Cannon's rows on one line made Party 647px wide on a 375px phone."""
    player = people("player")
    player.page.set_viewport_size({"width": 375, "height": 812})
    player.open("/party")
    player.page.evaluate("""() => {
      const card = document.querySelector('.pt-card');
      const res = card.querySelector('.pt-res') || card.appendChild(Object.assign(document.createElement('div'), {className: 'pt-res'}));
      res.insertAdjacentHTML('beforeend', '<span class="pt-group">Eldritch Cannon: ' + '<span>Flamethrower</span>'.repeat(6) + '</span>');
    }""")
    found = problems(player.page, "Party's resources at 375px")
    assert not found, "\n".join(found)


def test_resources_shorten_only_when_they_would_wrap(people, server):
    """Brett, 2026-11-01: whole names while they fit on one line; once they don't, the short ones, and back again."""
    player = people("player")
    page = player.page
    page.set_viewport_size({"width": 1280, "height": 800})
    player.open(f"/characters/{server['cole']}/battle")
    row = ".battlebar > .res-row:not(.slots)"
    short = f"document.querySelector('{row}').classList.contains('short')"
    page.wait_for_selector(row)
    page.evaluate(f"document.querySelectorAll('{row} > .res:not(.res-insp), {row} > .res-group').forEach(e => e.remove())")
    page.set_viewport_size({"width": 1270, "height": 800})
    page.wait_for_function(f"!({short})", timeout=3000)
    page.evaluate(f"""() => {{ const first = document.querySelector('{row} .res-insp');
      for (let i = 0; i < 12; i++) first.insertAdjacentHTML('beforebegin', '<span class="res extra"><span class="rn-full">A resource with a long name</span><span class="rn-short">R</span></span>'); }}""")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.wait_for_function(short, timeout=3000)
    page.evaluate("document.querySelectorAll('.res.extra').forEach(e => e.remove())")
    page.set_viewport_size({"width": 1270, "height": 800})
    page.wait_for_function(f"!({short})", timeout=3000)


def test_tap_targets_on_a_phone(people, server):
    """A standing rule: DESIGN.md › Principles 8, Works on a phone. A control is at least 36px tall there (Oct 31: Battle's Cast and +7 were 21px)."""
    player = people("player")
    player.page.set_viewport_size({"width": 375, "height": 812})
    small = []
    for path in (f"/characters/{server['cole']}/battle", f"/characters/{server['cole']}", "/party", "/help"):
        player.open(path)
        small += player.page.evaluate("""(path) => [...document.querySelectorAll('.btn, .roll-chip, .roll-hit, .res-go, .rs-toggle, .hp-btn, .live-pill, .help-btn, .chip, .ls-chip, .ws-chip, .spell-chip')]
          .map(e => [path, e.className, e.offsetHeight]).filter(([, , h]) => h && h < 36)""", path)
    assert not small, small


def test_manage_pages_hold_together_at_every_width(people, server, long_names):
    admin = people("admin")
    found = check(admin, server, PAGES["admin"])
    assert not found, "\n".join(found)
    assert admin.errors == []



SHIFTS = """new PerformanceObserver(l => { window.__shifts = (window.__shifts || []).concat(
  l.getEntries().filter(e => !e.hadRecentInput).map(e => ({ value: e.value, nodes: (e.sources || []).map(s => s.node && (s.node.id || s.node.className || s.node.nodeName)) }))); })
  .observe({ type: 'layout-shift', buffered: true });"""


def test_pages_dont_shift_as_they_load(people, server):
    """The Table rolls sidebar takes its place before the page is drawn (base.html's first script),
    so nothing moves sideways while the page loads and the log arrives (Brett, 2026-10-26: every page jumped)."""
    player = people("player")
    player.context.add_init_script(SHIFTS)
    found = []
    for width in (1400, 1000):
        player.page.set_viewport_size({"width": width, "height": 900})
        for path in ("/c/main/", "/c/main/campaign", f"/characters/{server['cole']}/battle", f"/characters/{server['cole']}", "/party"):
            player.open(path)
            player.page.wait_for_load_state("networkidle")
            player.page.wait_for_timeout(800)  # the log's first load, and anything it moves
            shifts = player.page.evaluate("window.__shifts || []")
            total = sum(s["value"] for s in shifts)
            if total > 0.005:  # (none at all, today)
                found.append(f"{path} at {width}px moved {total:.3f}: {shifts[:3]}")
    assert not found, "\n".join(found)
    assert player.errors == []

