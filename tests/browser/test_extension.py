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
        conn.execute(text("""UPDATE campaigns SET vtt_pieces = '["sync"]' WHERE id = :c"""), {"c": server["campaign"]})
        conn.commit()
    engine.dispose()


def with_extension(chromium_type, server, tmp_path, who):
    """A browser with the extension in it, signed in as `who`, and D&D Beyond's address answered here."""
    from tests.browser.conftest import PEOPLE

    folder = extension_for(server["base"], tmp_path)
    context = chromium_type.launch_persistent_context(str(tmp_path / "profile"), channel="chromium", headless=True,
                                                      args=[f"--disable-extensions-except={folder}", f"--load-extension={folder}"])
    context.route(re.compile(r"https://www\.dndbeyond\.com/.*"), lambda r: r.fulfill(status=200, content_type="text/html", body="<!doctype html><title>Sheet</title><main>Stand-in sheet</main>"))
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(f"{server['base']}/dev/login?as={PEOPLE[who]}")
    return context


@pytest.fixture
def chrome(playwright, server, tmp_path):
    """Cole's player's browser, with the extension."""
    context = with_extension(playwright.chromium, server, tmp_path, "player")
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
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)

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
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)
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
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)
    page.click('.res-row .res-go >> nth=0')
    page.locator(".roll-win [data-use-go]").first.click(timeout=5000)
    card = page.locator("#cards > .card", has_text="left")
    card.wait_for(timeout=5000)
    card.locator(".card-act").click()
    page.locator("#cards > .card", has_text="left").nth(1).wait_for(timeout=5000)


def test_minus_on_hit_points_is_click_type_enter(chrome, server):
    """Brett, 2026-11-01 (docs/mockups/hp-flow/ Option B): − opens the window ready to type in, and Enter takes it."""
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)
    page.bring_to_front()
    page.click(".hp-btn[aria-label=Damage]")
    field = page.locator(".roll-win input[name=amount]")
    field.wait_for(timeout=5000)
    assert page.evaluate("document.activeElement.name") == "amount"  # ready to type
    page.keyboard.type("5")
    page.locator(".roll-win .hp-go button[type=submit]:not([disabled])").wait_for(timeout=5000)
    page.keyboard.press("Enter")
    page.locator("#cards > .card", has_text="took 5").wait_for(timeout=5000)  # the corner card: the window's close mustn't lose it
    page.wait_for_function("!document.querySelector('.roll-win input[name=amount]')", timeout=5000)


def test_inspiration_asks_first_and_undo_takes_it_back(chrome, server):
    """Brett, 2026-11-01: the star opens a question, and nothing changes until it's answered."""
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)
    page.bring_to_front()
    page.click(".res-row .res-insp")
    page.locator(".roll-win [data-use-close]").click(timeout=5000)
    assert page.locator("#cards > .card", has_text="Heroic Inspiration").count() == 0
    page.click(".res-row .res-insp")
    page.locator(".roll-win [data-use-go]").click(timeout=5000)
    card = page.locator("#cards > .card", has_text="Heroic Inspiration")
    card.wait_for(timeout=5000)
    card.locator(".card-act").click()
    page.locator("#cards > .card", has_text="Heroic Inspiration").nth(1).wait_for(timeout=5000)


def test_cast_and_roll_is_one_step_and_the_roll_stays_the_players(chrome, server):
    """Brett, 2026-10-31 (docs/mockups/usability/): the slot is spent and the roll opens, at the table by default."""
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)
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


def test_prepare_spells_holds_together_at_every_width(people, server):
    """Prepare spells (app/preparing.py) is a live-state modal, so it's checked here, where the bridge is on (and the
    campaign is a test one), with the same check as every main page (tests/browser/test_layout.py)."""
    from tests.browser.test_layout import WIDTHS, problems

    player = people("player")
    page, found = player.page, []
    for width in WIDTHS:
        page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        player.open(f"/characters/{server['cole']}")
        page.click("[data-tab=t-spells]")
        page.click("button[data-modal-url*='/spells/prepare']")
        page.locator(".peek.open [data-prep]").wait_for()
        found += problems(page, f"prepare spells at {width}px")
    page.locator("[data-prep-tick]").first.click()  # a change: the side's list and the foot's label grow
    found += problems(page, "prepare spells, one change ticked")
    assert page.locator("[data-prep-note]").inner_text() in ("Drop 1", "Prepare 1")  # (the sheet isn't open here: no Make)
    assert not found, "\n".join(found)


@pytest.mark.parametrize("where", ["https://www.dndbeyond.com/games/1", SHEET], ids=["vtt", "dms-copy-of-the-sheet"])
def test_the_dms_browser_makes_a_closed_sheets_change_from_any_dnd_beyond_page(where, people, chromium, server, tmp_path, browser_db):
    """DM Backup Option A (Brett, 2026-11-02): Cole's sheet is closed and the DM's browser has D&D Beyond's VTT open (a
    stand-in), so Cole's player's pill turns yellow, and the change they make is made by the DM's browser, for Cole.
    The same with the DM's own copy of Cole's sheet open: it isn't his player's sheet, so it never turns his pill green
    and the DM's browser makes the change there (review, 2026-11-02)."""
    from tests.table_setup import COLE

    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        conn.execute(text("UPDATE characters SET ddb_campaign_id = '1', sheet_heard_at = NULL WHERE id = :c"), {"c": server["cole"]})
        conn.execute(text("UPDATE campaigns SET ddb_campaign_id = '1' WHERE id IN (SELECT campaign_id FROM campaign_characters WHERE character_id = :c)"), {"c": server["cole"]})
        # (what the tests before left waiting: nothing reaches a stand-in D&D Beyond, so it stays to make by hand)
        conn.execute(text("UPDATE bridge_intents SET state = 'live' WHERE character_id = :c"), {"c": server["cole"]})
        conn.execute(text("UPDATE bridge_batches SET state = 'done' WHERE character_id = :c"), {"c": server["cole"]})
        conn.commit()
    engine.dispose()
    writes = []

    def character_service(route):
        if route.request.method == "GET":
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"data": COLE}))
        writes.append(json.loads(route.request.post_data or "{}"))
        route.fulfill(status=200, content_type="application/json", body="{}")

    player = people("player")  # Cole's player, on a computer without the extension
    page = player.open(f"/characters/{server['cole']}/battle")
    player.live()
    dm = with_extension(chromium.browser_type, server, tmp_path, "dm")
    try:
        dm.route(re.compile(r"https://auth-service\.dndbeyond\.com/.*"), lambda r: r.fulfill(status=200, content_type="application/json", body='{"token": "t", "ttl": 300}'))
        dm.route(re.compile(r"https://character-service\.dndbeyond\.com/.*"), character_service)
        dm.pages[0].wait_for_timeout(1500)  # (the DM's askdnd page hands the extension its key)
        vtt = dm.new_page()
        vtt.goto(where)
        page.wait_for_function("document.getElementById('live-pill').classList.contains('via')", timeout=20000)
        page.click(".hp-btn[aria-label=Damage]")
        page.locator(".roll-win input[name=amount]").wait_for(timeout=5000)
        page.keyboard.type("3")
        page.locator(".roll-win .hp-go button[type=submit]:not([disabled])").wait_for(timeout=5000)
        page.keyboard.press("Enter")
        for _ in range(40):  # the DM's browser asks every few seconds
            if writes:
                break
            vtt.wait_for_timeout(500)
    finally:
        dm.close()
    assert writes and writes[0]["characterId"] == 75423618 and writes[0]["removedHitPoints"] == COLE["removedHitPoints"] + 3
