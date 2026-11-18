"""Send a note in a real page (Found, Fixed, Tried: app/fft/sending.py, app.js "send a note"; screen 9 of
docs/mockups/found-fixed-tried/): \\ opens the window at once and the page's picture follows, marked with Box, Arrow,
Draw and Text; Hide while I take a screenshot puts it away and brings it back; Send keeps where, when and how the page
was, and the safe copy of the picture with the sender's private parts covered."""

from sqlalchemy import create_engine, text


def _rows(browser_db, sql, **params):
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        rows = conn.execute(text(sql), params).all()
    engine.dispose()
    return rows


def test_backslash_pick_what_it_is_and_send(people, server, browser_db):
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.wait_for_load_state("networkidle")
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    win.wait_for(state="visible", timeout=5000)
    win.locator("[data-fb-wrap]").wait_for(state="visible", timeout=15000)  # the page's picture, taken as it opened
    assert win.locator("[data-fb-pic]").count() == 1 and win.locator("[data-fb-pic].on").count() == 1  # (The page, chosen)
    page.fill("#fb-win textarea[name=text]", "Speed should show the swim speed too.")
    page.click("[data-fb-send]")  # (what it is, never picked for you: Send asks for it first)
    win.locator("[data-fb-said]").wait_for(state="visible", timeout=5000)
    page.click("[data-fb-kind=idea]")
    assert page.locator("[data-fb-kind=idea]").get_attribute("aria-checked") == "true"
    assert page.locator("[data-fb-ask]").evaluate("e => e.textContent === document.querySelector('[data-fb-kind=idea]').dataset.ask")
    assert win.locator("[data-fb-line]").inner_text()  # (the line beside Send says what happens next)
    page.click("[data-fb-send]")
    page.locator("#cards > .card").first.wait_for(timeout=10000)
    (words, ctx, html, kind, state), = _rows(browser_db, "SELECT text, context, length(html), kind, state FROM fft_notes ORDER BY id DESC LIMIT 1")
    assert words == "Speed should show the swim speed too." and html > 1000 and kind == "idea" and state == "filed"
    assert ctx["window"] and ctx["browser"] and "signed_in_as" not in ctx
    assert _rows(browser_db, "SELECT count(*) FROM fft_pictures")[0][0] == 1
    page.keyboard.press("\\")  # (again, in a field: typing a backslash there never opens it)
    win.wait_for(state="visible", timeout=5000)
    assert page.locator("[data-fb-kind].on").count() == 0  # (opened again: nothing picked)
    page.fill("#fb-win textarea[name=text]", "a \\ b")
    assert page.locator("#fb-win textarea[name=text]").input_value() == "a \\ b"
    assert not admin.errors, admin.errors


def test_marks_and_words_are_drawn_into_what_is_sent_and_private_parts_covered(people, server, browser_db):
    """Box, Arrow, Draw and Text on the picture (Undo and Clear apart); what's sent carries them. A part of the page
    marked private (a player's character notes) is covered in the copy others see, and left whole in its sender's."""
    admin = people("admin")
    page = admin.open("/party")
    page.wait_for_load_state("networkidle")
    page.evaluate("""() => {
      const box = Object.assign(document.createElement('div'), { textContent: 'My secret plan' });
      box.setAttribute('data-private', '');
      Object.assign(box.style, { position: 'fixed', top: '120px', left: '120px', width: '220px', height: '80px', background: 'rgb(30, 200, 30)', zIndex: 40 });
      document.body.append(box);
    }""")
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    canvas = win.locator("[data-fb-canvas]")
    canvas.wait_for(state="visible", timeout=15000)
    assert win.locator("[data-fb-covered]").is_visible()  # (it says so)
    box = canvas.bounding_box()
    page.mouse.move(box["x"] + 40, box["y"] + 40)
    page.mouse.down()
    page.mouse.move(box["x"] + 200, box["y"] + 120, steps=5)
    page.mouse.up()
    win.locator("[data-fb-undo]").click()  # (Undo takes the box away; drawn again)
    page.mouse.move(box["x"] + 40, box["y"] + 40)
    page.mouse.down()
    page.mouse.move(box["x"] + 200, box["y"] + 120, steps=5)
    page.mouse.up()
    win.locator("[data-fb-tool=text]").click()
    page.mouse.click(box["x"] + 60, box["y"] + 60)
    win.locator(".fb-text-input").fill("Should be centered")
    page.keyboard.press("Enter")
    assert win.locator(".fb-text-input").count() == 0 and win.is_visible()
    page.fill("#fb-win textarea[name=text]", "This, marked.")
    page.click("[data-fb-kind=problem]")
    page.click("[data-fb-send]")
    page.locator("#cards > .card").first.wait_for(timeout=10000)
    (marked,), = _rows(browser_db, "SELECT context->>'marked' FROM fft_notes WHERE text = 'This, marked.'")
    assert marked == "2"
    (full, safe), = _rows(browser_db, "SELECT p.key, p.safe_key FROM fft_pictures p JOIN fft_notes n ON n.id = p.note_id WHERE n.text = 'This, marked.'")
    assert full and safe and full != safe  # (the safe copy, with the private part covered, is its own picture)
    (html,), = _rows(browser_db, "SELECT html FROM fft_notes WHERE text = 'This, marked.'")
    assert "My secret plan" not in html and 'data-private="emptied"' in html
    assert not admin.errors, admin.errors


def test_hide_while_i_take_a_screenshot_keeps_everything(people, server):
    admin = people("admin")
    page = admin.open("/party")
    page.wait_for_load_state("networkidle")
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    win.locator("[data-fb-wrap]").wait_for(state="visible", timeout=15000)
    page.click("[data-fb-kind=question]")
    page.fill("#fb-win textarea[name=text]", "Half written.")
    win.locator("[data-fb-hide]").click()
    win.wait_for(state="hidden")
    card = page.locator("#cards > .card", has=page.locator(".card-act"))
    card.wait_for()
    card.locator(".card-act").click()  # Back to it
    win.wait_for(state="visible")
    assert page.locator("#fb-win textarea[name=text]").input_value() == "Half written."
    assert page.locator("[data-fb-kind=question]").get_attribute("aria-checked") == "true"
    assert not admin.errors, admin.errors


def test_a_long_page_opens_at_once_and_draws_one_picture_of_what_is_on_screen(people, server):
    """Brett, Nov 3: with the item browser open the window was slow to come, and pressing fast froze the tab once. The
    window opens before the picture is drawn, only what's on screen is drawn (thousands of rows off screen), a second
    press while one is drawn waits for it, and a modal open on the page is in the picture where it is on screen."""
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.wait_for_load_state("networkidle")
    page.evaluate("""() => {  // a long list in a modal, as the item browser is
      const box = Object.assign(document.createElement('div'), { id: 'long' });
      Object.assign(box.style, { position: 'fixed', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: '400px',
                                 height: '300px', overflow: 'auto', background: 'rgb(200, 30, 30)', zIndex: 50 });
      for (let i = 0; i < 3000; i++) box.append(Object.assign(document.createElement('p'), { textContent: 'Row ' + i }));
      document.body.append(box);
      window.scrollTo(0, 400);
    }""")
    page.evaluate("""() => {  // which comes first, the window or its picture (the order is the promise, not a time)
      window.__fbFirst = '';
      const seen = () => {
        if (window.__fbFirst) return;
        const win = document.querySelector('#fb-win'), pic = document.querySelector('[data-fb-wrap]');
        if (pic && pic.checkVisibility()) window.__fbFirst = 'picture';
        else if (win && win.checkVisibility()) window.__fbFirst = 'window';  // (a fixed window has no offsetParent)
      };
      new MutationObserver(seen).observe(document.body, { subtree: true, childList: true, attributes: true });
    }""")
    page.keyboard.press("\\")
    page.locator("#fb-win").wait_for(state="visible")
    assert page.evaluate("window.__fbFirst") == "window"  # (before the picture: it used to wait for it)
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)  # (Chrome closes the window just after the key; a person is never quicker)
    page.keyboard.press("\\")  # (again at once, while the first picture is drawn: one picture, not two)
    page.locator("[data-fb-wrap]").wait_for(state="visible", timeout=15000)
    page.wait_for_function("() => { const c = document.querySelector('[data-fb-canvas]'); return c && c.width > 100; }")
    red = page.evaluate("""() => {  // the modal's red near the picture's centre: drawn where it is on screen
      const c = document.querySelector('[data-fb-canvas]'), g = c.getContext('2d');
      const [r, gr, b] = g.getImageData(c.width / 2 + 150, c.height / 2 + 120, 1, 1).data;
      return r > 150 && gr < 90 && b < 90;
    }""")
    assert red
    assert not admin.errors, admin.errors


def test_a_page_holding_a_nul_character_still_gets_its_picture(people, server):
    """Brett, Nov 4: a NUL character in the page made the picture's SVG invalid XML, which stopped the whole drawing:
    characters XML can't hold are taken out before it's painted."""
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.wait_for_load_state("networkidle")
    page.evaluate("() => document.querySelector('main').append(Object.assign(document.createElement('span'), { textContent: 'x\\u0000\\u0007y' }))")
    page.keyboard.press("\\")
    page.locator("[data-fb-wrap]").wait_for(state="visible", timeout=15000)
    assert not admin.errors, admin.errors


def test_the_window_fits_a_phone_and_a_laptop(people, server):
    """The window with its picture at a phone's width and a laptop's: the tools wrapped, nothing spilling."""
    from tests.browser.test_layout import problems

    admin = people("admin")
    page, found = admin.page, []
    for width in (375, 1280):
        page.set_viewport_size({"width": width, "height": 812 if width < 640 else 900})
        admin.open("/party")
        page.wait_for_load_state("networkidle")
        page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', { key: '\\\\', bubbles: true }))")
        page.locator("#fb-win [data-fb-wrap]").wait_for(state="visible", timeout=15000)
        found += problems(page, f"the window at {width}px")
    assert not found, "\n".join(found)
    assert not admin.errors, admin.errors
