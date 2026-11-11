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

ITEMS = os.path.join(os.path.dirname(__file__), "..", "fixtures", "ddb", "items.json")
SERVER_ENV = {"DDB_BRIDGE": "1", "DDB_ITEMS_URL": "file://" + os.path.abspath(ITEMS)}  # (the item browser's list: made up)
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
    # D&D Beyond's own servers are never reached: a test that needs them stands in for them (its route wins)
    context.route(re.compile(r"https://(auth-service|character-service)\.dndbeyond\.com/.*"), lambda r: r.fulfill(status=503, body=""))
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
    # which extension this browser has (0.9.9 on), for feedback and support
    assert page.evaluate("document.body.dataset.bridgeVersion") == json.load(open(os.path.join(SOURCE, "manifest.json")))["version"]

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
    held, sent = [], []  # the outside review's W1: a second Enter while the first is on its way mustn't take the damage twice
    page.on("request", lambda r: sent.append(r) if r.url.endswith("/hp/apply") else None)
    page.route("**/hp/apply", lambda route: held.append(route))
    with page.expect_request("**/hp/apply"):
        page.keyboard.press("Enter")
    page.keyboard.press("Enter")
    page.evaluate("1")
    held[0].continue_()
    page.unroute("**/hp/apply")
    page.locator("#cards > .card", has_text="took 5").wait_for(timeout=5000)  # the corner card: the window's close mustn't lose it
    page.wait_for_function("!document.querySelector('.roll-win input[name=amount]')", timeout=5000)
    page.wait_for_timeout(500)  # (HTMX would have sent a queued second press the moment the first answered)
    assert len(sent) == 1


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
    # Undo's own words, not "a second card": the first card can follow its change in place or leave on its own before
    # Undo's arrives on a slow machine (Nov 7: this flaked twice on GitHub)
    page.locator("#cards > .card", has_text="Heroic Inspiration given").wait_for(timeout=8000)


def test_cast_and_roll_is_one_step_and_the_roll_stays_the_players(chrome, server):
    """Brett, 2026-10-31 (docs/mockups/usability/): the slot is spent and the roll opens, at the table by default; and
    Nov 10 ("Cast and roll" didn't roll): healing rolls at once at the level cast, with no second Cast at."""
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)
    page.click(".spellbook-btn")
    page.wait_for_selector(".sb-actions .item-go")
    page.evaluate("""() => [...document.querySelectorAll('.sb-actions .item-go')]
        .find(b => /Healing Word/.test((b.closest('li, tr, .sb-row, [data-name]') || b).textContent)).click()""")
    page.locator(".roll-win [data-then-roll]").click()
    page.locator(".roll-card .rcard-heal").wait_for(timeout=15000)  # (rolled at once: its healing)
    assert page.locator(".roll-card [data-card-slot]").count() == 0  # (cast: its level is fixed, nothing to choose)
    page.locator("#cards > .card", has_text="Cast").wait_for(timeout=5000)
    rolls = page.evaluate("fetch('/rolls?since=-1').then(r => r.text())")
    assert "Healing Word" in rolls and "level 1" in rolls  # (at the table, at the level cast)
    # (Brett's Roll Audit comment, Nov 10: one way to cast without a slot, No slot in Cast at; no second link)
    page.keyboard.press("Escape")
    page.evaluate("""() => [...document.querySelectorAll('.sb-actions .item-go')]
        .find(b => /Healing Word/.test((b.closest('li, tr, .sb-row, [data-name]') || b).textContent)).click()""")
    page.locator(".roll-win [data-then-roll]").wait_for()
    assert not page.locator(".roll-win").get_by_text("Roll without spending a slot").count()
    page.locator(".roll-win select[name=way]").select_option(label="No slot")
    page.locator(".roll-win [data-then-roll]").click()
    page.locator(".roll-card .rcard-heal").wait_for(timeout=15000)  # (cast without a slot, rolled at once)


def test_use_and_roll_spends_the_item_and_rolls_its_plan_at_once(chrome, server):
    """Brett, Nov 10 (a Roll engine): an item whose plan rolls (a Soul Coin) has Use and roll, like Cast and roll: the
    coin is spent and the card rolls the plan its button carries at once; a potion's Drink rolls its plan's healing."""
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.evaluate("try { localStorage.setItem('askdnd.rollsAnim', 'off') } catch (e) {}")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)
    page.bring_to_front()
    page.keyboard.press("ControlOrMeta+k")  # (Ctrl+K on Linux, where GitHub runs it)
    page.locator("#search-q").fill("soul coin")
    page.wait_for_timeout(500)
    page.locator("#search-q").press("Enter")
    page.locator(".roll-win [data-then-roll]").click()
    page.locator(".roll-card [data-done]").wait_for(timeout=15000)  # (rolled at once)
    page.locator("#cards > .card", has_text="Used Soul Coin").wait_for(timeout=5000)
    rolls = page.evaluate("fetch('/rolls?since=-1').then(r => r.text())")
    assert "Soul Coin" in rolls and "1d10" in rolls  # (its plan's dice, in Table rolls)
    page.keyboard.press("Escape")
    sheet.close()


def test_a_prayer_bead_casts_its_spell_at_the_beads_level(chrome, server, browser_db):
    """A Necklace of Prayer Beads (Nov 10): Which bead; the Bead of Curing's Use and roll rolls Cure Wounds at level 2
    (4d8 + the spellcasting modifier) at once; a bead whose spell rolls nothing says just Use."""
    from tests.browser.test_every_roll import _as

    _as(browser_db, server, "big_c")
    try:
        page = chrome.pages[0]
        page.goto(f"{server['base']}/characters/{server['cole']}/battle")
        page.evaluate("try { localStorage.setItem('askdnd.rollsAnim', 'off') } catch (e) {}")
        page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
        sheet = chrome.new_page()
        sheet.goto(SHEET)
        page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)
        page.bring_to_front()
        page.keyboard.press("ControlOrMeta+k")
        page.locator("#search-q").fill("necklace of prayer")
        page.wait_for_timeout(500)
        page.locator("#search-q").press("Enter")
        go = page.locator(".roll-win [data-use-go]")
        go.first.wait_for()
        assert go.first.inner_text().strip() == "Use"  # (Bead of Blessing: Bless rolls nothing)
        page.locator(".roll-win [data-use-bead]").select_option("1")  # (Bead of Curing)
        assert go.first.inner_text().strip() == "Use and roll"
        go.first.click()
        page.locator(".roll-card .rcard-heal").wait_for(timeout=15000)  # (rolled at once)
        rolls = page.evaluate("fetch('/rolls?since=-1').then(r => r.text())")
        assert "Cure Wounds" in rolls and "4d8" in rolls and "level 2" in rolls
        page.keyboard.press("Escape")
        sheet.close()
    finally:  # (Cole's own sheet back for the tests after this one, even when it fails)
        _as(browser_db, server, "cole")


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


def test_the_item_browser_shows_an_item_and_fills_in_what_you_pay(people, server):
    """The item browser (app/item_browser.py): a name shows what the item is (in place of the list on a phone), + puts
    it in Adding, and what's paid starts at the book's price until the player types their own. Held together at every
    width, as every main page (tests/browser/test_layout.py)."""
    from tests.browser.test_layout import WIDTHS, problems

    player = people("player")
    page, found = player.page, []
    for width in reversed(WIDTHS):  # (ending on a phone)
        page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        player.open(f"/characters/{server['cole']}")
        page.click("[data-tab=t-items]")
        page.click("button[data-modal-url*='/items/browse']")
        page.locator(".peek.open [data-ib] [data-ls-row]").first.wait_for()
        found += problems(page, f"item browser at {width}px")
    page.fill("[data-ib] [data-ls-search]", "rope")
    rope = page.locator("[data-ib] [data-ls-row]:visible")
    assert rope.count() == 1  # (D&D Beyond's 2014 Rope isn't listed)
    rope.locator("[data-ib-add]").click()
    rope.locator("[data-ib-add]").click()
    assert page.locator("[data-ib-pay]").input_value() == "2 gp" and "Rope" in page.locator("[data-ib-basket]").inner_text()
    rope.locator("[data-ib-show]").click()
    page.locator("[data-ib-card] h3", has_text="Rope").wait_for()
    assert page.locator(".ib-main").is_hidden()  # (a phone: the item in place of the list)
    found += problems(page, "item browser, an item shown")
    page.click("[data-ib-hide]")
    page.fill("[data-ib] [data-ls-search]", "healing")
    page.locator("[data-ib] [data-ls-row]:visible [data-ib-add]").click()
    assert page.locator("[data-ib-pay]").input_value() == "2 gp"  # (a magic item has no price)
    assert "the DM's to say" in page.locator("[data-ib-price-note]").inner_text()
    page.fill("[data-ib-pay]", "45 gp")
    page.locator("[data-ib-basket] [aria-label='One more Rope']").click()
    assert page.locator("[data-ib-pay]").input_value() == "45 gp"  # (once typed, it's the player's)
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
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"data": {**COLE, "campaign": {**(COLE.get("campaign") or {}), "id": 1}}}))
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


def test_a_save_on_the_sheet_reaches_askdnd_from_the_sheets_own_read(chrome, server, browser_db):
    """Brett, Nov 3: a Soul Coin's use given back on D&D Beyond stayed spent in askdnd, as D&D Beyond's public copy
    trailed the save. The sheet now reads itself, signed in, once its saves stop, and askdnd keeps that read (here the
    public copy can't be reached at all, so only that read can tell askdnd)."""
    page, sheet, held, _ = cole_at_the_table(chrome, server, browser_db)
    panel = f"async () => (await (await fetch('/characters/{server['cole']}/detail?ref=item:992695540')).text()).replace(/\\s+/g, ' ')"
    used = 1 if "2 of 3" not in page.evaluate(panel) else 2  # (a number askdnd doesn't show yet)
    # the sheet's own save, as D&D Beyond's page sends it: a use of the Soul Coin
    sheet.evaluate("""u => fetch('https://character-service.dndbeyond.com/character/v5/inventory/item/charge',
        {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({characterId: 75423618, id: 992695540, uses: u, charges: u})})""", used)
    want = f"{3 - used} of 3"
    for _ in range(40):  # (askdnd reads it once the sheet's saves stop, a second and a half)
        if want in page.evaluate(panel):
            break
        page.wait_for_timeout(500)
    got = page.evaluate(panel)
    assert want in got, got[got.find("Charges") - 20:got.find("Charges") + 160]


def stand_in_ddb(context, held, rules):
    """D&D Beyond's own servers, standing in: the sheet (`held`) as the signed-in read gets it, and the writes the bridge
    and the sheet send kept in it, stamped as D&D Beyond stamps a save (`rules["keeps"]` False drops each one while
    answering OK, as D&D Beyond sometimes does)."""
    from datetime import UTC, datetime

    def character_service(route):
        if route.request.method == "GET":
            return route.fulfill(status=200, content_type="application/json", body=json.dumps({"data": held}))
        body, url = json.loads(route.request.post_data or "{}"), route.request.url
        if rules["keeps"]:
            if url.endswith("/life/hp/damage-taken"):
                held.update({k: body[k] for k in ("removedHitPoints", "temporaryHitPoints") if k in body})
            elif url.endswith("/inventory/item/charge"):
                next(i for i in held["inventory"] if i["id"] == body["id"])["limitedUse"]["numberUsed"] = body["uses"]
            held["dateModified"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        route.fulfill(status=200, content_type="application/json", body="{}")

    context.route(re.compile(r"https://auth-service\.dndbeyond\.com/.*"), lambda r: r.fulfill(status=200, content_type="application/json", body='{"token": "t", "ttl": 300}'))
    context.route(re.compile(r"https://character-service\.dndbeyond\.com/.*"), character_service)


def cole_at_the_table(chrome, server, browser_db):
    """Cole's Battle and his sheet open in the player's browser, with a stand-in D&D Beyond holding a copy of his sheet,
    and nothing left waiting from the tests before."""
    import copy
    from datetime import UTC, datetime

    from tests.table_setup import COLE

    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        conn.execute(text("UPDATE bridge_intents SET state = 'live' WHERE character_id = :c"), {"c": server["cole"]})
        conn.execute(text("UPDATE bridge_batches SET state = 'done' WHERE character_id = :c"), {"c": server["cole"]})
        conn.commit()
    engine.dispose()
    held, rules = copy.deepcopy(COLE), {"keeps": True}
    held["dateModified"] = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    stand_in_ddb(chrome, held, rules)
    page = chrome.pages[0]
    page.goto(f"{server['base']}/characters/{server['cole']}/battle")
    page.wait_for_function("window.askdndLive && window.askdndLive.up", timeout=8000)
    sheet = chrome.new_page()
    sheet.goto(SHEET)
    page.bring_to_front()
    page.wait_for_function(f"document.querySelector('{PILL}').textContent.includes('Connected')", timeout=45000)
    return page, sheet, held, rules


def take_damage(page, n):
    page.click(".hp-btn[aria-label=Damage]")
    page.locator(".roll-win input[name=amount]").wait_for(timeout=5000)
    page.keyboard.type(str(n))
    page.locator(".roll-win .hp-go button[type=submit]:not([disabled])").wait_for(timeout=5000)
    page.keyboard.press("Enter")


def test_the_corner_card_follows_its_change_to_d_and_d_beyond(chrome, server, browser_db):
    """Bridge Review, Nov 3: "✓ Cole took 3" came the moment Enter was pressed, before D&D Beyond had it. The card now
    says it's on its way, and ✓ On D&D Beyond once askdnd has read it there."""
    page, sheet, held, _ = cole_at_the_table(chrome, server, browser_db)
    before = held["removedHitPoints"]
    take_damage(page, 3)
    card = page.locator("#cards > .card", has_text="took 3")
    card.wait_for(timeout=5000)
    card.locator(".card-sub", has_text="On D&D Beyond").wait_for(timeout=20000)
    assert held["removedHitPoints"] == before + 3


def test_try_again_in_the_panel_beside_the_sheet(chrome, server, browser_db):
    """Bridge Review, Nov 3 (Brett: should retries be part of the extension's window?): a change that didn't go through
    has Try again and Undo in the panel beside the sheet, not only in askdnd."""
    page, sheet, held, rules = cole_at_the_table(chrome, server, browser_db)
    before = held["removedHitPoints"]
    rules["keeps"] = False  # D&D Beyond drops it
    take_damage(page, 3)
    page.locator("#cards > .card", has_text="took 3").wait_for(timeout=5000)
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:  # (it gives up after 3 tries, half a minute: given up here at once)
        page.wait_for_timeout(1500)
        conn.execute(text("UPDATE bridge_intents SET state = 'not_yet', error = 'D&D Beyond didn''t keep it (3 tries).' WHERE character_id = :c AND state <> 'live'"), {"c": server["cole"]})
        conn.execute(text("UPDATE bridge_batches SET state = 'stopped' WHERE character_id = :c AND state IN ('sending', 'ready')"), {"c": server["cole"]})
        conn.commit()
    engine.dispose()
    rules["keeps"] = True
    sheet.reload()  # (the panel is drawn again)
    sheet.wait_for_function("() => !!document.getElementById('askdnd-bridge')?.shadowRoot?.querySelector('[data-act=retry]')", timeout=15000)
    assert "didn't go through" in sheet.evaluate("() => document.getElementById('askdnd-bridge').shadowRoot.textContent")
    sheet.evaluate("() => document.getElementById('askdnd-bridge').shadowRoot.querySelector('[data-act=retry]').click()")
    for _ in range(40):
        if held["removedHitPoints"] == before + 3:
            break
        sheet.wait_for_timeout(500)
    assert held["removedHitPoints"] == before + 3


def test_a_vtt_opened_before_askdnd_is_heard_once_askdnd_connects(chromium, server, tmp_path, browser_db):
    """Extension 0.12.1 (found by the live test, Nov 4): after Chrome restarts, the extension can't reach askdnd until an
    askdnd page connects it. A VTT page opened first asked then whether askdnd follows its game, was told no, and its
    fight was never heard until the page was reloaded. It asks again when askdnd connects, and tells the fight it heard."""
    from tests.browser.test_vtt_listener import sync

    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        conn.execute(text("UPDATE campaigns SET ddb_campaign_id = '1', fight = NULL WHERE id = :c"), {"c": server["campaign"]})
        conn.commit()
    dm = with_extension(chromium.browser_type, server, tmp_path, "dm")
    try:
        askdnd = dm.pages[0]
        askdnd.wait_for_timeout(1500)
        worker = dm.service_workers[0] if dm.service_workers else dm.wait_for_event("serviceworker")
        askdnd.goto("about:blank")
        worker.evaluate("chrome.storage.session.clear()")  # (as after Chrome restarts: no askdnd connected yet)
        vtt = dm.new_page()
        vtt.goto("https://www.dndbeyond.com/games/1")
        vtt.evaluate("""m => {
            const ws = new WebSocket('wss://games.dndbeyond.com.invalid/test');
            ws.addEventListener('error', () => {});
            ws.dispatchEvent(new MessageEvent('message', {data: m}));
        }""", json.dumps(sync()))
        vtt.wait_for_timeout(1500)
        assert not vtt.evaluate("!!document.getElementById('askdnd-vtt')")  # (not followed: askdnd can't be reached)
        askdnd.goto(f"{server['base']}/characters/{server['cole']}/battle")  # (askdnd connects the extension)
        vtt.wait_for_function("!!document.getElementById('askdnd-vtt')", timeout=15000)
        fight = None
        for _ in range(30):
            with engine.connect() as conn:
                fight = conn.execute(text("SELECT fight FROM campaigns WHERE id = :c"), {"c": server["campaign"]}).scalar()
            if fight:
                break
            vtt.wait_for_timeout(500)
        assert fight and fight["round"] == 4 and [x["name"] for x in fight["order"]] == ["Vi", "Ogre"]
    finally:
        dm.close()
        with engine.connect() as conn:
            conn.execute(text("UPDATE campaigns SET ddb_campaign_id = NULL, fight = NULL WHERE id = :c"), {"c": server["campaign"]})
            conn.commit()
        engine.dispose()
