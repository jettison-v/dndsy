"""The real extension in a real browser (Brett, 2026-10-30: "could you or another tool simulate these tests?"): askdnd as
it runs on beta, extension/askdnd-bridge as Chrome loads it, and a stand-in page at D&D Beyond's own address, so nothing
ever reaches D&D Beyond. What D&D Beyond itself does isn't covered: its saves, its game log and its VTT stay for the real
accounts in docs/testing-setup.md."""

import json
import os
import re
import shutil

import pytest
from sqlalchemy import create_engine, text

SERVER_ENV = {"DDB_BRIDGE": "1"}
SHEET = "https://www.dndbeyond.com/characters/75423618"
SOURCE = os.path.join(os.path.dirname(__file__), "..", "..", "extension", "askdnd-bridge")
PILL = "#live-pill .live-ago"


def extension_for(base: str, folder) -> str:
    """The extension, allowed to talk to this test's askdnd (it only knows askdnd's own addresses)."""
    out = str(folder / "extension")
    shutil.copytree(SOURCE, out)
    path = os.path.join(out, "manifest.json")
    manifest = json.load(open(path))
    manifest["host_permissions"].append(base + "/*")
    for script in manifest["content_scripts"]:
        if any("localhost" in m for m in script["matches"]):
            script["matches"].append(base + "/*")
    json.dump(manifest, open(path, "w"))
    path = os.path.join(out, "background.js")
    code = open(path).read()
    assert "'http://localhost:8000'" in code
    open(path, "w").write(code.replace("'http://localhost:8000'", f"'http://localhost:8000', '{base}'"))
    return out


@pytest.fixture(autouse=True)
def bridge_on(server, browser_db):
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        conn.execute(text("UPDATE campaigns SET is_test = true WHERE id = :c"), {"c": server["campaign"]})
        conn.commit()
    engine.dispose()


@pytest.fixture
def chrome(server, tmp_path):
    """A browser with the extension in it, signed in as Cole's player, and D&D Beyond's address answered here."""
    from playwright.sync_api import sync_playwright

    from tests.browser.conftest import PEOPLE

    folder = extension_for(server["base"], tmp_path)
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(str(tmp_path / "profile"), channel="chromium", headless=True,
                                                       args=[f"--disable-extensions-except={folder}", f"--load-extension={folder}"])
        context.route(re.compile(r"https://www\.dndbeyond\.com/.*"), lambda r: r.fulfill(status=200, content_type="text/html", body="<!doctype html><title>Sheet</title><main>Stand-in sheet</main>"))
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(f"{server['base']}/dev/login?as={PEOPLE['player']}")
        yield context
        context.close()


def test_opening_and_closing_a_sheet_shows_on_askdnds_open_pages(chrome, server):
    """Brett, 2026-10-30: he closed the sheet and askdnd kept saying Connected."""
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    page.wait_for_function("!document.body.classList.contains('no-bridge')")
    assert "Open your sheet to connect" in page.locator(PILL).inner_text()

    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected to D&D Beyond')", timeout=45000)

    sheet.close()
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Open your sheet to connect')", timeout=8000)
    page.click('[data-roll=save][data-label="Dex save"]:visible >> nth=0')
    assert page.locator(".roll-win").count() == 1


def test_a_sheet_closed_right_after_it_saved_stays_closed(chrome, server):
    """A real fight on the Mac Mini, 2026-10-30: the extension's read a moment after a save came after the tab had closed,
    told askdnd the sheet was open, and the pill and the roll window said Connected to a closed sheet."""
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected to D&D Beyond')", timeout=45000)
    sheet.evaluate("window.postMessage({ askdndBridge: 'from-page', type: 'saved', characterId: '75423618', path: '/x' }, location.origin)")
    sheet.wait_for_timeout(300)
    sheet.close()
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Open your sheet to connect')", timeout=8000)
    page.wait_for_timeout(8000)  # (past the two reads after a save)
    assert "Open your sheet to connect" in page.locator(PILL).inner_text()


def test_cast_spends_through_the_window_and_undo_takes_it_back(chrome, server):
    """Live state (app/casting.py): the real extension, the window, the corner card."""
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected to D&D Beyond')", timeout=45000)
    page.click('.res-row .res-go >> nth=0')
    page.locator(".roll-win [data-use-go]").first.click(timeout=5000)
    card = page.locator("#cards > .card", has_text="left")
    card.wait_for(timeout=5000)
    card.locator(".card-act").click()
    page.locator("#cards > .card", has_text="left").nth(1).wait_for(timeout=5000)


def test_cast_and_roll_is_one_step_and_the_roll_stays_the_players(chrome, server):
    """Brett, 2026-10-31 (docs/mockups/usability/): the slot is spent and the roll opens, at the table by default."""
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected to D&D Beyond')", timeout=45000)
    page.click(".spellbook-btn")
    page.wait_for_selector(".sb-actions .item-go")
    count = page.evaluate("document.querySelectorAll('.sb-actions .item-go').length")
    for i in range(count):
        page.evaluate("i => document.querySelectorAll('.sb-actions .item-go')[i].click()", i)
        page.wait_for_selector(".roll-win .rw-title")
        if page.locator(".roll-win [data-then-roll]").count():
            break
    page.locator(".roll-win [data-then-roll]").click()
    page.locator('.roll-win [data-to="table"]').wait_for(timeout=5000)  # (only the character's own player gets the choice)
    page.locator("#cards > .card", has_text="Cast").wait_for(timeout=5000)


def test_without_the_extension_the_pill_says_to_add_it_and_the_window_has_the_link(people, server):
    """Brett, 2026-10-30: the DM didn't have it by accident, and nothing said so."""
    dm = people("dm")
    page = dm.open("/c/main/")
    page.locator("#live-pill .live-noext").wait_for(timeout=4000)
    assert page.locator("#live-pill .live-ago").is_hidden()
    page.click("#live-pill")
    link = page.locator(".live-noext-box a.primary")
    link.wait_for()
    assert "chromewebstore.google.com" in link.get_attribute("href")
    assert page.locator(".bridge-steps li").count() >= 2 and page.locator(".bridge-other").is_hidden()
    assert link.evaluate("a => getComputedStyle(a).alignItems") == "center"  # (a link in a menu stays a button: Brett, 2026-10-30)
