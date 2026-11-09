"""Feedback for Claude in a real page (app/feedback.py, app.js "feedback for Claude"; Brett, 2026-11-03,
docs/mockups/feedback-queue/): \\ opens the window at once and the page's picture follows, Point at it marks a thing on
the page, and Send puts the note in the queue with where, when and how the page was."""

from sqlalchemy import create_engine, text


def test_backslash_point_and_send(people, server, browser_db):
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.wait_for_load_state("networkidle")
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    win.wait_for(state="visible", timeout=5000)
    page.locator("[data-fb-shot]").wait_for(state="visible", timeout=15000)  # the page's picture, taken as it opened
    page.fill("#fb-win textarea[name=text]", "Speed should show the swim speed too.")
    page.click("[data-fb-point]")
    page.locator("#fb-win").wait_for(state="hidden", timeout=5000)
    page.click("h1")  # (pointing: the next click marks it)
    win.wait_for(state="visible", timeout=5000)
    assert "Pointed at" in page.locator("[data-fb-pointed]").inner_text()
    page.click("[data-fb-send]")
    page.locator("#cards > .card", has_text="In the queue").wait_for(timeout=10000)
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        row = conn.execute(text("SELECT text, context, shot_key, length(html) FROM feedback ORDER BY id DESC LIMIT 1")).one()
    engine.dispose()
    words, ctx, shot, html = row
    assert words == "Speed should show the swim speed too." and shot and html > 1000
    assert ctx["window"] and ctx["browser"] and ctx["pointed"]["label"] and ctx["signed_in_as"].endswith("(admin)")
    page.keyboard.press("\\")  # (again, in a field: typing a backslash there never opens it)
    win.wait_for(state="visible", timeout=5000)
    page.fill("#fb-win textarea[name=text]", "a \\ b")
    assert page.locator("#fb-win textarea[name=text]").input_value() == "a \\ b"
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
    page.evaluate("""() => {  // which comes first, the window or its picture (the order is the promise, not a time:
      window.__fbFirst = '';      // a second on GitHub's shared machines missed now and then, Nov 6)
      const seen = () => {
        if (window.__fbFirst) return;
        const win = document.querySelector('#fb-win'), shot = document.querySelector('[data-fb-shot]');
        if (shot && shot.checkVisibility()) window.__fbFirst = 'picture';
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
    page.locator("[data-fb-shot]").wait_for(state="visible", timeout=15000)
    red = page.evaluate("""async () => {  // the modal's red at the picture's centre: it was drawn where it is on screen
      const img = document.querySelector('[data-fb-shot]');
      await img.decode();
      const c = Object.assign(document.createElement('canvas'), { width: img.naturalWidth, height: img.naturalHeight });
      const g = c.getContext('2d');
      g.drawImage(img, 0, 0);
      const [r, gr, b] = g.getImageData(img.naturalWidth / 2 + 150, img.naturalHeight / 2 + 120, 1, 1).data;
      return r > 150 && gr < 90 && b < 90;
    }""")
    assert red
    assert not admin.errors, admin.errors


def test_a_page_holding_a_nul_character_still_gets_its_picture(people, server):
    """Brett, Nov 4: on beta the picture never came ("No picture this time"), and the note itself answered 500. A NUL
    character in the page (another extension's text; Postgres refuses it too) makes the picture's SVG invalid XML, which
    stopped the whole drawing: characters XML can't hold are taken out before it's painted."""
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.wait_for_load_state("networkidle")
    page.evaluate("() => document.querySelector('main').append(Object.assign(document.createElement('span'), { textContent: 'x\\u0000\\u0007y' }))")
    page.keyboard.press("\\")
    page.locator("[data-fb-shot]").wait_for(state="visible", timeout=15000)
    assert not admin.errors, admin.errors


def test_point_at_leaves_the_roll_window_open_to_point_inside_it(people, server):
    """Brett, Nov 9: "clicking Point at closes all modals". Point at, its click and Escape belong to Feedback for Claude:
    the roll window under it stays open, and pointing at its Advantage marks it without pressing it."""
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.locator(".roll-hit:visible").first.click()
    page.locator(".roll-win").wait_for()
    page.keyboard.press("\\")
    page.locator("#fb-win").wait_for(state="visible")
    page.locator("#fb-win [data-fb-point]").click()
    page.locator(".roll-win [data-mode='adv']").click()
    page.locator("#fb-win").wait_for(state="visible")
    assert page.locator(".roll-win").count() == 1 and "Advantage" in page.locator("[data-fb-pointed]").inner_text()
    assert page.locator(".roll-win [data-mode='adv']").get_attribute("aria-pressed") == "false"
    page.keyboard.press("Escape")
    assert page.locator("#fb-win").is_hidden() and page.locator(".roll-win").count() == 1
    assert not admin.errors, admin.errors
