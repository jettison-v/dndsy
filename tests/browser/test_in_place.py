"""A press redraws in place (the Live UI Audit, Brett, Nov 19: "only what changed redraws, and nothing needs a refresh";
issue 40, the page flashing on the freeze and lanes). A plain form in a page's main is sent in the background and the
page's new copy goes in through swapMain (app.js "A press redraws in place"): no reload, the scroll where it was, the
corner card says what happened. An answer that is another page still loads it."""

from sqlalchemy import create_engine, text

from tests.browser.pages import press


def _one(url, sql):
    engine = create_engine(url)
    with engine.connect() as conn:
        got = conn.execute(text(sql)).scalar()
    engine.dispose()
    return got


def test_deploys_choice_redraws_in_place(people, server, browser_db):
    admin = people("admin")
    page = admin.open("/manage/for-you")
    page.evaluate("window.__stayed = true; window.scrollTo(0, 40)")
    page.locator(".fft-deploys > summary").click()
    page.locator('[data-mode-pick="frozen"]').click()
    page.locator('#fft-pause-why input[name="why"]').fill("a demo tomorrow")
    page.locator('#fft-pause-why [data-do="pause"]').click()
    page.locator('.fft-status[data-mode="frozen"]').wait_for()
    page.locator("#cards > .card").first.wait_for()  # (the corner card says it)
    assert page.evaluate("window.__stayed === true")  # (no reload: the page is the same document)
    assert "a demo tomorrow" in _one(browser_db[0], "SELECT value FROM tool_settings WHERE key = 'fft_freeze'")

    page.locator(".fft-deploys > summary").click()
    page.locator('[data-mode-pick="independent"]').click()
    page.locator('.fft-status[data-mode="independent"]').wait_for()
    assert page.evaluate("window.__stayed === true") and page.url.endswith("/manage/for-you")


def test_work_redraws_in_place(people, server, browser_db):
    """Work (issue 40's page, Where it stands then): the answer is a redirect to the same page, drawn in place, the
    address kept."""
    admin = people("admin")
    page = admin.open("/manage/work")
    page.evaluate("window.__stayed = true")
    page.locator(".fft-deploys > summary").click()
    page.locator('[data-mode-pick="frozen"]').click()
    page.locator('#fft-pause-why [data-do="pause"]').click()
    page.locator('.fft-status[data-mode="frozen"]').wait_for()
    assert page.evaluate("window.__stayed === true") and page.url.endswith("/manage/work")
    page.locator(".fft-deploys > summary").click()
    page.locator('[data-mode-pick="independent"]').click()
    page.locator('.fft-status[data-mode="independent"]').wait_for()


def test_a_buttons_own_address_wins(people, server, browser_db):
    """A button may send its form elsewhere (formaction: Suggestions' Dismiss and Ask Claude, Backups' Cancel): the press
    goes to the button's address, not the form's."""
    admin = people("admin")
    page = admin.open("/manage/for-you")
    page.evaluate("""() => { const f = document.createElement('form'); f.method = 'post'; f.action = '/nowhere';
      f.innerHTML = '<button type="submit" id="elsewhere" name="mode" value="frozen" formaction="/manage/for-you/mode">Go</button>';
      document.querySelector('main').append(f); window.__stayed = true; }""")
    page.locator("#elsewhere").click()
    page.locator('.fft-status[data-mode="frozen"]').wait_for()
    assert page.evaluate("window.__stayed === true")
    assert _one(browser_db[0], "SELECT value FROM tool_settings WHERE key = 'fft_freeze'")
    page.locator(".fft-deploys > summary").click()
    page.locator('[data-mode-pick="independent"]').click()
    page.locator('.fft-status[data-mode="independent"]').wait_for()


def test_a_refused_press_says_why_and_redraws_nothing(people, server, browser_db):
    admin = people("admin")
    page = admin.open("/manage/for-you")
    page.evaluate("""() => { const f = document.createElement('form'); f.method = 'post'; f.action = '/manage/for-you/mode';
      f.innerHTML = '<input type="hidden" name="mode" value="sideways"><button type="submit" id="bad">Go</button>';
      document.querySelector('main').append(f); window.__stayed = true; }""")
    admin.allow("400")
    page.locator("#bad").click()
    page.locator("#cards > .card.k-warn").first.wait_for()
    assert page.evaluate("window.__stayed === true") and page.locator("#bad").is_enabled()  # (the button is back for another try)


def test_a_press_in_a_side_panel_redraws_in_place(people, server, browser_db):
    """Batch 3: a side panel's press (Feedback's Close it: why?) goes the same way: the page under it redraws in place
    and the panel closes, as the old reload closed it; nothing reloads."""
    from tests.browser.test_fft_feedback import _waiting_note
    nid = _waiting_note(browser_db[0], "The rest button does nothing.")
    admin = people("admin")
    page = admin.open(f"/manage/feedback?tab=approve&open=n{nid}")
    page.locator(f'#peek [data-fft-note="{nid}"] [data-do="fix"]').click()
    page.locator("#cards > .card").first.wait_for()
    iid = _one(browser_db[0], f"SELECT issue_id FROM fft_notes WHERE id = {int(nid)}")  # noqa: S608 (a number of our own)
    page = admin.open(f"/manage/feedback?tab=open&open=i{iid}")
    page.locator('#peek [data-fft-issue] [data-do="close"]').wait_for()
    page.evaluate("window.__stayed = true")
    page.locator('#peek [data-fft-issue] [data-do="close"]').click()
    win = page.locator("#peek-top")  # (its window opens over the item window: issue 108)
    win.locator('[data-reason="withdrawn"] input').check()
    win.locator('[data-do="close"]').click()
    page.wait_for_function("() => !document.querySelector('#peek.open')")  # (the panel closed)
    page.locator("#cards > .card").first.wait_for()
    assert page.evaluate("window.__stayed === true")
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        state = conn.execute(text("SELECT i.state FROM fft_issues i JOIN fft_notes n ON n.issue_id = i.id WHERE n.id = :i"), {"i": nid}).scalar()
    engine.dispose()
    assert state == "closed"


def test_a_count_never_blinks_through_a_press(people, server, browser_db):
    """Issue 40 (Brett, Nov 19: "the For you badge still flashes on changing the lane from Ship to Look and back"): a
    press redraws Manage's side list, whose counts the server draws empty; the last ones go back in the same moment, so
    no frame shows the count missing."""
    import json
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        item = conn.execute(text("INSERT INTO fft_items (title, place, section, standing, next_whose, next_step, workspace_id) VALUES ('Fixes', 1, 'now', false, '', '', 1) RETURNING id")).scalar()
        area = conn.execute(text("INSERT INTO fft_areas (item_id, key, title, place, workspace_id) VALUES (:i, '', 'Feedback and Testing', 1, 1) RETURNING id"), {"i": item}).scalar()
        cid = conn.execute(text("INSERT INTO fft_checks (title, version, devices, minutes, place, preflight, area_id, workspace_id) VALUES ('A check', 1, CAST(:d AS jsonb), 2, 1, 'passed', :a, 1) RETURNING id"), {"d": json.dumps(["laptop"]), "a": area}).scalar()
        conn.execute(text("INSERT INTO fft_check_versions (check_id, version, path, steps, expect, why, workspace_id) VALUES (:c, 1, '/party', CAST(:s AS jsonb), 'It shows.', '', 1)"), {"c": cid, "s": json.dumps(["Look."])})
    engine.dispose()
    admin = people("admin")
    page = admin.open("/manage/work?tab=queue")
    page.wait_for_function("() => { const c = document.querySelector('.manage-side [data-manage-count=\"for-you\"]'); return c && !c.hidden && c.textContent.trim(); }")
    page.evaluate("""() => { window.__blinks = 0; const look = () => { const c = document.querySelector('.manage-side [data-manage-count="for-you"]');
      if (!c || c.hidden || !c.textContent.trim()) window.__blinks++; window.__frames = requestAnimationFrame(look); }; look(); }""")
    for lane in ("look", "ship"):
        page.locator(f'[data-area="{area}"] details.fft-lane > summary').click()
        press(page.locator(f'[data-area="{area}"] [data-lane-pick="{lane}"]'))
    page.wait_for_timeout(300)
    assert page.evaluate("cancelAnimationFrame(window.__frames), window.__blinks") == 0, "the For you count went missing in a frame"


def test_a_pop_up_menu_you_opened_holds_off_a_redraw(people, server, browser_db):
    """Issue 76: the live test opened Dismiss… on a familiar and its button went before it could be pressed: the familiar
    coming back on D&D Beyond redrew Battle under the open menu. A pop-up menu (a <details> whose contents float over the
    page) that's open holds a change from elsewhere until it's closed; a fold that opens in place doesn't."""
    from tests.browser.test_table import battle

    player = people("player")
    page = battle(player, server)
    live = f"document.dispatchEvent(new CustomEvent('askdnd:live', {{ detail: {{ type: 'character', id: {server['cole']} }} }}))"
    # (a menu as Dismiss… is drawn: its contents float under it)
    page.evaluate("""() => { const d = document.createElement('details'); d.id = 'test-pop'; d.style.position = 'relative';
      d.innerHTML = '<summary>Dismiss…</summary><div style="position:absolute"><button type="button" id="test-go">Dismiss</button></div>';
      document.querySelector('main').prepend(d); d.open = true; }""")
    page.evaluate(live)
    page.wait_for_timeout(1500)  # (past the live connection's gathering of changes, 400 ms, and the redraw it would ask for)
    assert page.locator("#test-pop[open] #test-go").is_visible()  # (still there: nothing redrew under it)
    page.locator("#test-pop > summary").click()  # (closed: the change it held comes in)
    page.wait_for_function("!document.getElementById('test-pop')", timeout=8000)
    # A fold that opens in place holds nothing
    page.evaluate("""() => { const d = document.createElement('details'); d.id = 'test-fold';
      d.innerHTML = '<summary>More</summary><div>In place</div>'; document.querySelector('main').prepend(d); d.open = true; }""")
    page.evaluate(live)
    page.wait_for_function("!document.getElementById('test-fold')", timeout=8000)
    assert player.errors == []
