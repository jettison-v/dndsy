"""The table's core flows in real browsers (tests/browser/conftest.py): pages load cleanly, the roll window's keys,
and rolls reaching everyone at the table live, with a DM-only roll's number kept from the other players."""

import json
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
    for path in ("/c/main/campaign", "/c/main/campaign?tab=sessions", "/c/main/campaign?tab=world", "/c/main/campaign?tab=quests",
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
    win = page.locator(".roll-card")
    done = win.locator(".rcard-result:not(.rolling)")
    # Advantage, then Enter: rolls (it used to press Advantage again)
    page.click(save("Dex"))
    win.locator("[data-mode=adv]").click()
    page.keyboard.press("Enter")
    done.wait_for()
    page.wait_for_function(f"document.querySelector('{LOG}') && document.querySelector('{LOG}').textContent.includes('Adv')")
    page.keyboard.press("Escape")
    assert win.count() == 0
    # A d4, then Enter: one d4 added, not two
    page.click(save("Dex"))
    win.locator("[data-adding]").click()
    win.locator("[data-add='+1d4']").click()
    page.keyboard.press("Enter")
    done.wait_for()
    page.wait_for_function(f"document.querySelector('{LOG}').textContent.includes('1d4')")
    assert page.evaluate(f"(document.querySelector('{LOG}').textContent.match(/1d4/g) || []).length") == 1
    page.keyboard.press("Escape")
    # Clicking the card's words leaves nothing focused: Enter still rolls
    page.click(save("Wis"))
    win.locator(".rcard-head b").click()
    page.keyboard.press("Enter")
    done.wait_for()
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
    # (by the newest row, not how many: the first roll replaces "No rolls yet", so an empty log's count stays 1, and a
    # full log stays full; this test passed only when an earlier one had left rolls, Nov 13)
    newest_id = f"document.querySelector('{LOG}')?.dataset.id"
    top = dm.page.evaluate(newest_id)
    page = battle(player, server)
    start = time.monotonic()
    page.click(save("Con"), modifiers=["Shift"])  # Shift: roll straight away
    dm.page.wait_for_function(f"([id]) => {newest_id} && {newest_id} !== id", arg=[top], timeout=5000)
    took = time.monotonic() - start
    assert "Con save" in newest(dm.page)
    assert took < 1.5, f"took {took:.1f} s: the live connection should beat the 30-second fallback poll"
    assert player.errors == [] and dm.errors == []


def test_a_dm_only_roll_reaches_everyone_but_only_the_dm_sees_it(people, server):
    """A standing rule, in real pages: a DM-only roll arrives live on every screen, but only the DM's shows its
    numbers."""
    player, other, dm = people("player", "other", "dm")
    for p in (other, dm):
        p.open("/c/main/")
        p.live()
        p.page.wait_for_selector(LOG, state="attached")  # the log is collapsed on Story
    # (by the newest row, not how many: the log's first roll replaces "No rolls yet", and a full log stays full)
    newest_id = f"document.querySelector('{LOG}')?.dataset.id"
    tops = {p: p.page.evaluate(newest_id) for p in (other, dm)}
    page = battle(player, server)
    page.click(save("Cha"))
    page.locator(".roll-card [data-vis-open]").click()
    page.locator(".roll-card [data-to=dm]").click()
    page.keyboard.press("Enter")
    for p in (other, dm):
        p.page.wait_for_function(f"([id]) => {newest_id} && {newest_id} !== id", arg=[tops[p]], timeout=5000)
    assert "Cha save" in newest(dm.page)
    hidden = newest(other.page)
    assert "Rolled for the DM" in hidden and "Cha save" not in hidden
    assert player.errors == [] and other.errors == [] and dm.errors == []


def test_a_pages_javascript_error_is_sent_home(people, server):
    """app.js "page errors": an error in askdnd's own page goes to /errors/page (app/errors.py), once."""
    player = people("player")
    player.allow("reading 'type'")  # (the error this test throws on purpose)
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
    assert got and all("/static/app.js" in g["source"] and g["page"] == "/c/main/campaign" and g["message"] for g in got)
    assert len({(g["message"], g["line"]) for g in got}) == len(got)  # each distinct error once
    assert player.errors  # (the error itself, expected here)


def test_the_menu_bars_menus_fit_their_text(people, server):
    """Each menu from the menu bar wraps its text inside its box (a "keep the bar on one line" rule once leaked
    into the Live popover, 2026-10-26)."""
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.click("#live-pill")
    page.wait_for_selector("#live-menu .live-pop")
    for menu in ["live-menu"] + page.eval_on_selector_all(".topbar [data-door]", "ms => ms.map(m => m.id)"):  # every door's menu
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
    # Over the page, it's in front of a page's sticky tab bar (feedback 45, Nov 7: the Campaign page's covered it)
    for path in ("/c/main/campaign", f"/characters/{server['cole']}"):
        player.open(path)
        page.click(".rs-edge")
        page.wait_for_function("document.getElementById('table-rolls').getBoundingClientRect().left === 0")  # (slid in)
        bar = page.locator(".tabbar").first.bounding_box()
        top = "(x, y) => !!document.elementFromPoint(x, y).closest('#table-rolls')"
        assert page.evaluate(f"({top})({bar['x'] + 40}, {bar['y'] + bar['height'] / 2})"), path
        page.mouse.click(700, 500)
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


def test_add_on_the_spell_bar_opens_the_book_and_pinning_there_updates_the_bar(people, server):
    player = people("player")
    page = battle(player, server)
    bar = page.locator("#spell-bar")
    bar.locator(".sb-add").click()
    book = page.locator(".peek.open [data-spellbook]")
    pin = book.locator('[data-ref="spell:Moonbeam"] .pick.star')
    pin.click()
    page.wait_for_function("document.querySelector('#spell-bar') && document.querySelector('#spell-bar').textContent.includes('Moonbeam')")
    assert bar.locator(".sb-add").count() == 0
    book.locator('[data-ref="spell:Moonbeam"] .pick.star.on').click()  # unpin: + Add comes back
    bar.locator(".sb-add").wait_for()
    assert player.errors == []


def test_a_character_changed_on_d_and_d_beyond_updates_the_pages_showing_it(people, server, browser_db):
    """With Game Mode off too, and never by reloading (it flashed): Battle swaps its body in, Sheet swaps its page in on
    the tab, the place and the search you had, and not while a side panel is open (app.js "live connection"; the
    bridge hearing a sheet save sends the same message)."""
    from sqlalchemy import create_engine, text

    engine = create_engine(browser_db[0])

    def changed():
        msg = '{"type": "character", "id": %d}' % server["cole"]
        with engine.connect() as conn:
            conn.execute(text("SELECT pg_notify('askdnd_table', :p)"), {"p": '{"c": %d, "m": %s}' % (server["campaign"], json.dumps(msg))})
            conn.commit()

    player = people("player")
    page = battle(player, server)
    player.live()
    page.evaluate("document.getElementById('battle-body').dataset.old = '1'; window.stayed = true")
    changed()
    page.wait_for_function("!document.getElementById('battle-body').dataset.old")
    assert page.evaluate("window.stayed")  # swapped in, not reloaded

    page = player.open(f"/characters/{server['cole']}")
    page.click('[data-tab="t-items"]')
    assert page.locator('#t-items [data-ls-view]').first.inner_text().startswith("All")  # Inventory starts on All
    assert page.locator('#t-items [data-ls-view="all"]').get_attribute("aria-pressed") == "true"
    player.live()
    items = page.locator("#t-items [data-ls-row]")
    first = items.first.get_attribute("data-name")
    page.locator("#t-items [data-ls-search]").fill(first)
    page.locator("#t-items [data-ls-search]").blur()
    shown = page.locator("#t-items [data-ls-row]:visible").count()
    page.locator("#t-items [data-ls-row]:visible").first.click()
    page.wait_for_selector(".peek.open")
    page.evaluate("window.scrollTo(0, 300); window.stayed = true; document.getElementById('t-items').dataset.old = '1'; window.y = scrollY")
    changed()
    time.sleep(2.5)
    assert page.evaluate("document.getElementById('t-items').dataset.old")  # busy with the side panel: it waits
    page.locator(".peek.open .peek-close").click()
    page.wait_for_function("!document.getElementById('t-items').dataset.old")
    assert page.evaluate("window.stayed")  # swapped in place, not reloaded
    assert page.locator('[role=tab][data-tab="t-items"]').get_attribute("aria-selected") == "true"
    assert page.evaluate("scrollY === window.y")
    assert page.locator("#t-items [data-ls-search]").input_value() == first
    assert page.locator("#t-items [data-ls-row]:visible").count() == shown
    engine.dispose()
    assert player.errors == []


def test_a_condition_reaches_everyone_watching_that_character_without_a_reload(people, server):
    """What the table sees of a character announces itself however it's made (realtime.TABLE_SEES): the player adds
    Poisoned, and the DM's Battle page for that character shows it in place."""
    player, dm = people("player", "dm")
    battle(player, server)
    page = battle(dm, server)
    dm.live()
    page.evaluate("window.stayed = true")
    assert not page.locator(".cond-pill:not(.cond-add)", has_text="Poisoned").count()
    player.page.evaluate("id => fetch('/characters/' + id + '/conditions', {method: 'POST', headers: {'HX-Request': 'true'}, body: new URLSearchParams({name: 'Poisoned'})})", server["cole"])
    page.locator(".cond-pill:not(.cond-add)", has_text="Poisoned").wait_for(timeout=5000)
    assert page.evaluate("window.stayed")  # swapped in, not reloaded
    # Brett, 2026-10-28: its badge pops in by the name and the halo flashes once, as it starts; opening the page doesn't
    assert page.locator('.char-head .cond-badge.new[data-name="Poisoned"]').count() == 1 and page.locator(".cond-halo.starting").count() == 1
    page.reload()
    page.locator('.cond-badge[data-name="Poisoned"]').wait_for()
    assert page.locator(".cond-badge.new, .cond-halo.starting").count() == 0
    player.page.evaluate("id => fetch('/characters/' + id + '/conditions/end', {method: 'POST', headers: {'HX-Request': 'true'}, body: new URLSearchParams({name: 'Poisoned'})})", server["cole"])
    page.locator(".cond-pill:not(.cond-add)", has_text="Poisoned").wait_for(state="detached", timeout=5000)  # and ends the same way
    assert dm.errors == [] and player.errors == []


def test_a_number_that_changed_marks_itself_with_the_change(people, server, browser_db):
    """The change mark (Brett, 2026-10-28): when a page shows its new copy, a number that changed glows for a moment with
    the change, whatever brought it (here: a read of D&D Beyond)."""
    from sqlalchemy import create_engine, text

    engine = create_engine(browser_db[0])

    def hp(change: int):
        with engine.connect() as conn:
            conn.execute(text("UPDATE character_snapshots SET summary = jsonb_set(summary, '{hit_points,current}', "
                              "to_jsonb((summary->'hit_points'->>'current')::int + :d)) WHERE character_id = :c"),
                         {"d": change, "c": server["cole"]})
            conn.execute(text("SELECT pg_notify('askdnd_table', :p)"),
                         {"p": json.dumps({"c": server["campaign"], "m": json.dumps({"type": "character", "id": server["cole"]})})})
            conn.commit()

    player = people("player")
    page = battle(player, server)
    player.live()
    tile = page.locator(f'[data-mark="{server["cole"]}:hp"]').first
    before = int(tile.locator("b").inner_text())
    hp(-7)
    page.wait_for_function(f'document.querySelector(\'[data-mark="{server["cole"]}:hp"] .mark-delta\')')
    assert tile.locator(".mark-delta").inner_text() == "−7" and "marked" in tile.get_attribute("class")
    assert int(tile.locator("b").inner_text()) == before - 7
    hp(7)  # (put back for the other tests)
    page.wait_for_function(f'document.querySelector(\'[data-mark="{server["cole"]}:hp"] b\').textContent.trim() === "{before}"')
    engine.dispose()
    assert player.errors == []


def test_the_dms_table_tools_work_after_a_map_is_added(people, server, browser_db, tmp_path):
    """askdnd's table as its DM runs it (Brett's first look on staging, Nov 6): a new place, a picture for its map, then
    + Creatures opens its window without a reload (the windows follow the page), and the Map ▾ and ⋯ menus open and
    stay open (a click used to hide every menu on the page, theirs too); a token's drag shows the ruler; the keys."""
    from io import BytesIO

    from PIL import Image
    from sqlalchemy import create_engine, text

    engine = create_engine(browser_db[0])

    def labs(on):
        with engine.connect() as conn:
            conn.execute(text("UPDATE campaigns SET vtt_pieces = CAST(:p AS JSONB), fight = NULL, shown_place_id = NULL WHERE id = :c"),
                         {"p": json.dumps(["labs", "vtt"] if on else []), "c": server["campaign"]})
            if not on:
                conn.execute(text("DELETE FROM places WHERE campaign_id = :c"), {"c": server["campaign"]})
            conn.commit()

    pic = tmp_path / "chapel.png"
    buf = BytesIO()
    Image.new("RGB", (700, 490), (90, 80, 60)).save(buf, "PNG")
    pic.write_bytes(buf.getvalue())
    admin = people("admin")
    page = admin.page
    try:
        labs(True)
        admin.open("/c/main/table")
        page.get_by_role("button", name="+ Place").first.click()
        page.locator("#tbl-new-place input[name=name]").fill("The ruined chapel")
        page.locator("#tbl-new-place button[type=submit]").click()
        page.wait_for_selector("text=No map here yet")
        page.locator("main .btn.primary[data-open-dialog=tbl-map]").click()
        page.locator("#tbl-map input[type=file]").set_input_files(str(pic))
        page.locator("#tbl-map button[type=submit]").click()
        page.wait_for_selector("#tmap")
        page.get_by_role("button", name="+ Creatures").click()
        page.locator("#tbl-creatures").wait_for(state="visible")
        page.locator("#tbl-creatures [data-close-dialog]").click()
        page.locator("summary", has_text="Map ▾").click()
        page.get_by_role("button", name="Rename").wait_for(state="visible")
        page.keyboard.press("Escape")  # Esc closes it
        page.get_by_role("button", name="Rename").wait_for(state="hidden")
        page.get_by_role("button", name="Place the party").click()
        page.locator("#tmap .tok-m").first.wait_for()
        # Dragging a token: the ruler says its feet while it moves
        page.wait_for_load_state("networkidle")  # (the page's new copy, with the party on it)
        tok = page.locator("#tmap .tok-m[data-moves]").first
        tok.wait_for(state="visible")
        box = tok.bounding_box()
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.down()
        page.mouse.move(box["x"] + box["width"] * 3, box["y"] + box["height"] / 2, steps=8)
        assert " ft" in page.locator(".tmap-tip").inner_text()
        page.mouse.up()
        page.locator(".tmap-tip").wait_for(state="detached")
        # Keys: ? lists them, A opens a spell's area, placed with a click
        page.keyboard.press("?")
        page.locator("#tbl-keys").wait_for(state="visible")
        page.keyboard.press("Escape")
        page.keyboard.press("a")
        page.locator("#tbl-area input[name=label]").fill("Fireball")
        page.locator("#tbl-area button[type=submit]").click()
        page.locator("#tbl-area").wait_for(state="hidden")  # (the window closes, then the map takes the click)
        # (the map's middle, through the locator: a fresh copy of the map can replace it at any moment, Nov 13; force:
        # a token there may sit on top, and the map takes the click as before)
        page.locator("#tmap").click(force=True)
        page.locator(".tmap-area", has_text="Fireball").wait_for()
        page.get_by_role("button", name="Start a fight").click()
        page.get_by_role("button", name="Begin Round 1").wait_for()
        page.locator("summary[aria-label=\"The fight's menu\"]").click()
        page.get_by_role("button", name="Undo the last change").wait_for(state="visible")
        page.locator("main h1, .tbl-top").first.click(position={"x": 2, "y": 2})  # a click elsewhere closes it
        page.get_by_role("button", name="Undo the last change").wait_for(state="hidden")
    finally:
        labs(False)
        engine.dispose()
    assert admin.errors == []


def test_your_scratch_pad_jots_from_battle_and_rolls_from_the_bar(people, server, browser_db):
    """Prepare your turn (Brett chose A and B, Nov 13): on askdnd's table, + Add in your turn's bar jots a row from your
    Battle onto your scratch pad, and the line's own Roll opens the roll card, as from Battle; ✕ takes it off."""
    from sqlalchemy import create_engine, text

    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        conn.execute(text("UPDATE campaigns SET vtt_pieces = CAST(:p AS JSONB) WHERE id = :c"), {"p": json.dumps(["labs", "vtt"]), "c": server["campaign"]})
    try:
        player = people("player")
        page = player.open("/c/main/table")
        bar = page.locator("#turn-bar")
        bar.locator(".tbar-add > summary").click()
        first = bar.locator(".tbar-add-it").first
        name = first.inner_text().replace("pinned", "").strip()
        first.click()
        line = bar.locator(".tbar-pad-line").first
        line.wait_for()
        assert name in line.inner_text()
        roll = line.locator("[data-plan], .roll-chip").first
        if roll.count():
            roll.click()
            page.locator(".roll-win, #peek.open").first.wait_for(timeout=10000)
            page.keyboard.press("Escape")
        line.locator(".tbar-pad-x").click()
        page.wait_for_function("!document.querySelector('.tbar-pad-line')")
        assert player.errors == []
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE campaigns SET vtt_pieces = CAST('[]' AS JSONB) WHERE id = :c"), {"c": server["campaign"]})
            conn.execute(text("UPDATE characters SET turn = NULL"))
        engine.dispose()
