"""The table's core flows in real browsers (tests/browser/conftest.py): pages load cleanly, the roll window's keys,
and rolls reaching everyone at the table live, with a DM-only roll's number kept from the other players."""

import time

LOG = "#roll-log > li"


def save(ability: str) -> str:
    """A save's roll button (Battle's header tiles and Sheet's rows share the roll attributes)."""
    return f'[data-roll=save][data-label="{ability} save"]:visible >> nth=0'


def battle(person, server):
    page = person.open(f"/characters/{server['cole']}/battle")
    page.wait_for_selector(save("Dex"))
    return page


def newest(page) -> str:
    return " ".join(page.locator(LOG).first.inner_text().split())


def test_the_main_pages_load_without_errors(people, server):
    admin = people("admin")
    for path in ("/c/main/", "/c/main/?tab=sessions", "/c/main/campaign", "/c/main/campaign?tab=quests",
                 f"/characters/{server['cole']}/battle", f"/characters/{server['cole']}",
                 f"/characters/{server['cole']}/plan", "/c/main/party", "/c/main/manage", "/c/main/manage/settings",
                 "/manage/campaigns", "/manage/dice", "/manage/design", "/help"):
        admin.open(path)
        admin.page.wait_for_load_state("networkidle")
        assert admin.page.locator("main").count(), path
    assert admin.errors == []


def test_enter_rolls_and_esc_closes_whatever_was_clicked_last(people, server):
    player = people("player")
    page = battle(player, server)
    win = page.locator(".roll-win")
    # Advantage, then Enter: rolls (it used to press Advantage again)
    page.click(save("Dex"))
    win.locator("[data-mode=adv]").click()
    page.keyboard.press("Enter")
    win.locator(".rw-result").wait_for()
    page.wait_for_function(f"document.querySelector('{LOG}') && document.querySelector('{LOG}').textContent.includes('Adv')")
    page.keyboard.press("Escape")
    assert win.count() == 0
    # A d4, then Enter: one d4 added, not two
    page.click(save("Dex"))
    win.locator("summary").click()
    win.locator("[data-add-die='4']").click()
    page.keyboard.press("Enter")
    win.locator(".rw-result").wait_for()
    page.wait_for_function(f"document.querySelector('{LOG}').textContent.includes('+1d4')")
    page.keyboard.press("Escape")
    # Clicking the window's text leaves nothing focused: Enter still rolls
    page.click(save("Wis"))
    win.locator(".rw-title").click()
    page.keyboard.press("Enter")
    win.locator(".rw-result").wait_for()
    page.keyboard.press("Escape")
    # Over a side panel, Esc closes the roll window only
    page.locator('[data-panel-url$="/all/action?add=1"]').first.click()
    panel = page.locator(".peek.open")
    panel.locator("[data-roll]").first.click()
    win.wait_for()
    page.keyboard.press("Escape")
    assert win.count() == 0 and panel.count() == 1
    page.keyboard.press("Escape")
    panel.wait_for(state="detached")
    assert player.errors == []


def test_a_roll_reaches_the_dms_screen_within_a_second(people, server):
    player, dm = people("player", "dm")
    dm.open("/c/main/")
    dm.live()
    dm.page.wait_for_selector(LOG, state="attached")  # the log is collapsed on Story
    before = dm.page.locator(LOG).count()
    page = battle(player, server)
    start = time.monotonic()
    page.click(save("Con"), modifiers=["Shift"])  # Shift: roll straight away
    dm.page.wait_for_function(f"document.querySelectorAll('{LOG}').length > {before}", timeout=5000)
    took = time.monotonic() - start
    assert "Con save" in newest(dm.page)
    assert took < 1.5, f"took {took:.1f} s: the live connection should beat the 30-second fallback poll"
    assert player.errors == [] and dm.errors == []


def test_a_dm_only_roll_reaches_everyone_but_only_the_dm_sees_it(people, server):
    player, other, dm = people("player", "other", "dm")
    for p in (other, dm):
        p.open("/c/main/")
        p.live()
        p.page.wait_for_selector(LOG, state="attached")  # the log is collapsed on Story
    counts = {p: p.page.locator(LOG).count() for p in (other, dm)}
    page = battle(player, server)
    page.click(save("Cha"))
    page.locator(".roll-win [data-to=dm]").click()
    page.keyboard.press("Enter")
    for p in (other, dm):
        p.page.wait_for_function(f"document.querySelectorAll('{LOG}').length > {counts[p]}", timeout=5000)
    assert "Cha save" in newest(dm.page)
    hidden = newest(other.page)
    assert "Rolled for the DM" in hidden and "Cha save" not in hidden
    assert player.errors == [] and other.errors == [] and dm.errors == []


def test_a_pages_javascript_error_is_sent_home(people, server):
    """app.js "page errors": an error in askdnd's own page goes to /errors/page (app/errors.py), once."""
    player = people("player")
    page = player.open("/c/main/")
    # Playwright can't read a beacon's body, so keep a copy of what the page hands the browser
    page.evaluate("""window.__sent = []; const send = navigator.sendBeacon.bind(navigator);
        navigator.sendBeacon = (url, data) => { data.text().then(t => window.__sent.push(JSON.parse(t))); return send(url, data); }; 0""")  # (0: so Playwright doesn't call the function as the result)
    # A live-update message with nothing in it makes app.js's own listener fail: a real error in askdnd's script
    with page.expect_response(lambda r: r.url.endswith("/errors/page")) as answered:
        page.evaluate("setTimeout(() => document.dispatchEvent(new CustomEvent('askdnd:live')))")
    assert answered.value.status == 204
    page.wait_for_function("window.__sent.length")
    got = page.evaluate("window.__sent")
    assert got and all("/static/app.js" in g["source"] and g["page"] == "/c/main/" and g["message"] for g in got)
    assert len({(g["message"], g["line"]) for g in got}) == len(got)  # each distinct error once
    assert player.errors  # (the error itself, expected here)


def test_the_menu_bars_menus_fit_their_text(people, server):
    """Each menu from the menu bar wraps its text inside its box (a "keep the bar on one line" rule once leaked
    into the Live popover, 2026-10-26)."""
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.click("#live-pill")
    page.wait_for_selector("#live-menu .live-pop")
    for menu in ("live-menu", "manage-menu", "help-menu", "account-menu"):
        spill = page.evaluate(f"""() => {{ const m = document.getElementById('{menu}'), was = m.hidden; m.hidden = false;
          const s = m.scrollWidth - m.clientWidth; m.hidden = was; return s; }}""")
        assert spill <= 1, f"{menu} is {spill}px wider than its box"
    assert admin.errors == []


def test_party_filters_work_like_the_rest(people, server):
    """Party's spells use the shared list (DESIGN.md › Lists and filters): a chip shows only its group, Who has it narrows
    to that character's, search looks at names, and nothing matching says so."""
    page = people("player").open("/party")
    page.click('[data-tab="t-spells"]')
    pool = page.locator("#t-spells")
    rows = pool.locator("[data-ls-row]")
    total = rows.count()
    assert total > 1
    pool.locator('[data-ls-group="does"]').first.click()
    some = pool.locator("[data-ls-row]:visible").count()
    assert 0 < some < total
    assert pool.locator("[data-ls-active]").is_visible()  # Showing only: … ×
    pool.locator("[data-ls-clear]").click()
    assert pool.locator("[data-ls-row]:visible").count() == total
    pool.locator('[data-ls-group="who"][data-ls-value="Cole"]').click()
    assert 0 < pool.locator("[data-ls-row]:visible").count() <= total
    pool.locator("[data-ls-clear]").click()
    pool.locator("[data-ls-search]").fill("zzzz")
    assert pool.locator("[data-ls-empty]").is_visible()
    pool.locator("[data-ls-search]").fill("")
    assert pool.locator("[data-ls-row]:visible").count() == total


def test_the_rolls_sidebar_stays_as_you_left_it(people, server):
    """Open or closed (to the edge tab), one choice for every page, and nothing changes it on its own (Brett,
    2026-10-26: the sidebar's three desktop states came and went as he moved around). Narrower windows start
    closed and open it over the page; phones keep their sheet, whose closed bar stays in view."""
    player = people("player")
    page = player.page
    state = "document.body.classList.contains('rolls-open') ? 'open' : document.body.classList.contains('rolls-closed') ? 'closed' : ''"
    pad = "getComputedStyle(document.body).paddingLeft"
    page.set_viewport_size({"width": 1300, "height": 900})
    for path in ("/c/main/", f"/characters/{server['cole']}/battle", "/party"):
        player.open(path)
        assert page.evaluate(state) == "open", path  # open everywhere until you close it
    assert page.locator("#table-rolls").is_visible() and not page.locator(".rs-edge").is_visible()
    page.click(".rs-toggle")
    page.wait_for_function("getComputedStyle(document.getElementById('table-rolls')).visibility === 'hidden'")
    assert page.locator(".rs-edge").is_visible() and page.evaluate(pad) == "0px"
    for path in (f"/characters/{server['cole']}/battle", "/c/main/campaign"):
        player.open(path)
        assert page.evaluate(state) == "closed", path  # Battle too
    page.click(".rs-edge")
    assert page.evaluate(state) == "open" and page.evaluate(pad) == "340px"
    player.open("/c/main/")
    assert page.evaluate(state) == "open"
    # A narrower window: closed at first; the tab opens it over the page, and a click elsewhere closes it
    page.set_viewport_size({"width": 1000, "height": 900})
    player.open("/c/main/")
    assert page.evaluate(state) == "closed"
    page.click(".rs-edge")
    assert page.evaluate(state) == "open" and page.evaluate(pad) == "0px"
    page.mouse.click(700, 500)
    assert page.evaluate(state) == "closed"
    page.set_viewport_size({"width": 1300, "height": 900})
    player.open("/c/main/")
    assert page.evaluate(state) == "open"  # what you chose at full width still holds
    # Phones: closed (the sheet's bar, still in view, no edge tab) until opened, since it covers a third of the screen
    page.evaluate("localStorage.removeItem('askdnd.rollsSide')")
    page.set_viewport_size({"width": 390, "height": 812})
    player.open("/c/main/")
    assert page.evaluate(state) == "closed"
    assert page.locator("#table-rolls").is_visible() and not page.locator(".rs-edge").is_visible()
    assert player.errors == []
