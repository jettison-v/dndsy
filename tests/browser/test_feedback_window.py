"""Send a note in a real page (Found, Fixed, Tried: app/fft/sending.py, app.js "send a note"; screen 9 of
docs/mockups/found-fixed-tried/): \\ opens the window at once and the page's picture follows, marked with Box, Arrow,
Draw and Text; Take a screenshot puts it away and brings it back (Cancel closes it); Send keeps where, when and how the page
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
    page.wait_for_function("() => document.fonts.status === 'loaded'")  # (askdnd's script runs before load; the picture wants its fonts)
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
    page.wait_for_function("() => document.fonts.status === 'loaded'")  # (askdnd's script runs before load; the picture wants its fonts)
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


def test_take_a_screenshot_keeps_everything_and_cancel_closes(people, server):
    """Brett's pick 3A (issue 18): Take a screenshot sits with the pictures and steps the window aside with a corner card
    that says how; Back to it brings it back as it was. Cancel, beside Send, closes it."""
    admin = people("admin")
    page = admin.open("/party")
    page.wait_for_function("() => document.fonts.status === 'loaded'")  # (askdnd's script runs before load; the picture wants its fonts)
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    win.locator("[data-fb-wrap]").wait_for(state="visible", timeout=15000)
    page.click("[data-fb-kind=question]")
    page.fill("#fb-win textarea[name=text]", "Half written.")
    assert win.locator("[data-fb-hide]").count() == 0  # (Cancel took Hide's place)
    win.locator("[data-fb-shot]").click()
    win.wait_for(state="hidden")
    card = page.locator("#cards > .card", has=page.locator(".card-act"))
    card.wait_for()
    card.locator(".card-act").click()  # Back to it
    win.wait_for(state="visible")
    assert page.locator("#fb-win textarea[name=text]").input_value() == "Half written."
    assert page.locator("[data-fb-kind=question]").get_attribute("aria-checked") == "true"
    win.locator("[data-fb-shot]").click()  # (again, and this time paste the screenshot)
    win.wait_for(state="hidden")
    page.evaluate("""async () => {
      const c = Object.assign(document.createElement('canvas'), { width: 300, height: 200 });
      c.getContext('2d').fillRect(0, 0, 300, 200);
      const blob = await new Promise(ok => c.toBlob(ok, 'image/png')), dt = new DataTransfer();
      dt.items.add(new File([blob], 'shot.png', { type: 'image/png' }));
      document.body.dispatchEvent(new ClipboardEvent('paste', { clipboardData: dt, bubbles: true }));
    }""")
    win.wait_for(state="visible")  # (the paste brings it back, the picture added and on the stage)
    page.wait_for_function("() => document.querySelectorAll('#fb-win [data-fb-pic]').length === 2 && document.querySelector('#fb-win [data-fb-canvas]').width === 300")
    chips = page.evaluate("() => [...document.querySelector('#fb-win [data-fb-chips]').children].filter(c => !c.hidden).map(c => c.dataset.fbShot !== undefined ? 'shot' : c.classList.contains('fb-add-pic') ? 'add' : 'pic')")
    assert chips == ["pic", "pic", "shot", "add"]  # (the pictures, then Take a screenshot and +)
    win.locator(".fb-sendline [data-fb-cancel]").click()  # Cancel
    win.wait_for(state="hidden")
    page.wait_for_function("() => !document.querySelector('#cards > .card:not(.out) .card-act')")  # (no card left waiting)
    assert not admin.errors, admin.errors


def test_a_long_page_opens_at_once_and_draws_one_picture_of_what_is_on_screen(people, server):
    """Brett, Nov 3: with the item browser open the window was slow to come, and pressing fast froze the tab once. The
    window opens before the picture is drawn, only what's on screen is drawn (thousands of rows off screen), a second
    press while one is drawn waits for it, and a modal open on the page is in the picture where it is on screen."""
    admin = people("admin")
    page = admin.open(f"/characters/{server['cole']}/battle")
    page.wait_for_function("() => document.fonts.status === 'loaded'")  # (askdnd's script runs before load; the picture wants its fonts)
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
    page.wait_for_function("() => document.fonts.status === 'loaded'")  # (askdnd's script runs before load; the picture wants its fonts)
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
        page.wait_for_function("() => document.fonts.status === 'loaded'")  # (askdnd's script runs before load; the picture wants its fonts)
        page.evaluate("document.dispatchEvent(new KeyboardEvent('keydown', { key: '\\\\', bubbles: true }))")
        page.locator("#fb-win [data-fb-wrap]").wait_for(state="visible", timeout=15000)
        found += problems(page, f"the window at {width}px")
    assert not found, "\n".join(found)
    assert not admin.errors, admin.errors


def test_the_pages_picture_keeps_what_the_screen_shows_when_scrolled(people, server, browser_db):
    """Brett's round, Nov 18: with the page scrolled, the page's picture came out with Feedback's list blank and its
    issue shifted up (what was above the screen was left out, so all below it moved up). The list scrolled inside its
    box and the page scrolled too: the picture's list area holds the same rows the screen does."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        for n in range(30):
            conn.execute(text("INSERT INTO fft_issues (title, feature, workspace_id) VALUES (:t, 'hp', 1)"), {"t": f"Row number {n} in a long list"})
    engine.dispose()
    admin = people("admin")
    page = admin.open("/manage/feedback?tab=open")
    page.set_viewport_size({"width": 1280, "height": 720})
    nav = page.locator(".reader-nav")
    nav.wait_for()
    page.evaluate("() => { scrollTo(0, 140); document.querySelector('.reader-nav').scrollTop = 600; }")
    box = nav.bounding_box()
    clip = {"x": box["x"], "y": box["y"], "width": box["width"], "height": min(box["height"], 400)}
    screen = page.screenshot(clip=clip)  # (the list as the screen shows it)
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    win.locator("[data-fb-wrap]").wait_for(state="visible", timeout=15000)
    drawn = page.evaluate("""b => { const c = document.querySelector('#fb-win [data-fb-canvas]'), o = document.createElement('canvas');
        o.width = Math.round(b.width); o.height = Math.round(b.height); o.getContext('2d').drawImage(c, b.x, b.y, b.width, b.height, 0, 0, o.width, o.height);
        return o.toDataURL('image/png'); }""", clip)
    import base64
    import io

    from PIL import Image, ImageChops, ImageStat

    def small(png):
        return Image.open(io.BytesIO(png)).convert("L").resize((48, 96))
    diff = ImageStat.Stat(ImageChops.difference(small(screen), small(base64.b64decode(drawn.split(",", 1)[1])))).mean[0]
    assert diff < 12, f"the list in the page's picture isn't what the screen shows (they differ by {diff:.1f})"


def test_an_arrow_looks_the_same_on_a_large_screenshot_as_on_a_small_one(people, server, tmp_path):
    """Issue 16 (Brett's round, Nov 18): the arrow was too small on his screenshot. Marks were sized by the picture's own
    width, so a large screenshot shown small in the window got a thin arrow with a small head. Now a mark is sized as it
    looks on screen: the same arrow drawn across the same stretch of screen shows the same on either picture."""
    import io

    from PIL import Image

    sizes, shown = {"small": (800, 500), "large": (3200, 2000)}, {}
    for name, (w, h) in sizes.items():
        Image.new("RGB", (w, h), (255, 255, 255)).save(tmp_path / f"{name}.png")
    admin = people("admin")
    page = admin.open("/party")
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    canvas = win.locator("[data-fb-canvas]")
    canvas.wait_for(state="visible", timeout=15000)
    win.locator("[data-fb-tool=arrow]").click()
    for name, (w, _h) in sizes.items():
        win.locator("[data-fb-file]").set_input_files(str(tmp_path / f"{name}.png"))
        page.wait_for_function(f"() => document.querySelector('[data-fb-canvas]').width === {w}")
        box = canvas.bounding_box()
        y = box["y"] + box["height"] / 2
        page.mouse.move(box["x"] + 30, y)
        page.mouse.down()
        page.mouse.move(box["x"] + 230, y, steps=5)
        page.mouse.up()
        shot = Image.open(io.BytesIO(canvas.screenshot())).convert("RGB")
        shown[name] = sum(1 for r, g, b in shot.getdata() if r > 200 and 120 < g < 200 and b < 90)  # (the mark's orange)
    # (a 200-pixel arrow, its line 3.5 screen pixels and its head 20: about 700 pixels of orange on screen either way;
    # before, about 230, a hairline with a small head)
    assert min(shown.values()) > 500 and 0.8 < shown["large"] / shown["small"] < 1.25, shown
    assert not admin.errors, admin.errors


def test_words_on_one_line_on_screen_stay_on_one_line_in_the_pages_picture(people, server):
    """Brett's round, Nov 18 (issues 20, 22; seen again walking issue 16): the page's picture drew "Party" as "Part" with
    the "y" on a line of its own, character names the same, and the menu bar's "Main" as "M…": its letters can come out
    a hair wider than the screen's, and a box as wide as its words then wraps or cuts the last of them. Words on one line
    on screen stay on one, whole, in the picture: the letters reach as far right in the picture as on the screen."""
    import base64
    import io

    from PIL import Image

    admin = people("admin")
    page = admin.open("/party")
    page.set_viewport_size({"width": 1440, "height": 800})
    page.wait_for_function("() => document.fonts.status === 'loaded'")
    boxes = {what: page.locator(what).first.bounding_box() for what in ("h1", ".topbar .campaign-name")}
    clips = {what: {"x": b["x"] - 4, "y": b["y"] - 4, "width": b["width"] + 60, "height": b["height"] * 2 + 8} for what, b in boxes.items()}
    screens = {what: Image.open(io.BytesIO(page.screenshot(clip=c))).convert("L") for what, c in clips.items()}
    page.keyboard.press("\\")
    page.locator("#fb-win [data-fb-wrap]").wait_for(state="visible", timeout=15000)

    def reach(im, b):  # (the right-most bright pixel on the words' own line: they're light on dark)
        line = im.crop((0, 4, im.size[0], 4 + int(b["height"])))
        px = line.load()
        return max((x for x in range(line.size[0]) for y in range(line.size[1]) if px[x, y] > 170), default=-1)
    for what, clip in clips.items():
        drawn = page.evaluate("""b => { const c = document.querySelector('#fb-win [data-fb-canvas]'), o = document.createElement('canvas');
            o.width = Math.round(b.width); o.height = Math.round(b.height); o.getContext('2d').drawImage(c, b.x, b.y, b.width, b.height, 0, 0, o.width, o.height);
            return o.toDataURL('image/png'); }""", clip)
        drawn = Image.open(io.BytesIO(base64.b64decode(drawn.split(",", 1)[1]))).convert("L").resize(screens[what].size)
        on_screen, in_picture = reach(screens[what], boxes[what]), reach(drawn, boxes[what])
        assert abs(in_picture - on_screen) <= 6, (what, on_screen, in_picture)  # (wrapped or cut, it fell well short)
    assert not admin.errors, admin.errors


def test_a_one_line_step_keeps_the_why_under_it_wrapping_in_the_pages_picture(people, server):
    """Issue 44 (Brett's round, Nov 18): in the page's picture of Testing, a check's first step held its own one line,
    and the why under it, inside the same box, ran on in one line past the reading pane. What's inside a one-line box
    wraps in the picture as it does on screen."""
    import base64
    import io

    from PIL import Image

    admin = people("admin")
    page = admin.open("/party")
    page.set_viewport_size({"width": 1280, "height": 800})
    page.wait_for_function("() => document.fonts.status === 'loaded'")
    page.evaluate("""() => { const d = document.createElement('div'); d.id = 'zz-step';
        Object.assign(d.style, { position: 'relative', zIndex: 50, width: '260px', height: '100px', overflow: 'hidden', background: '#000', color: '#fff', font: '16px/20px sans-serif' });  // (a fixed box: nothing below moves up into it)
        d.append('Look here.');
        const why = document.createElement('span'); why.style.display = 'block';
        why.textContent = 'this checks that the words under a one line step keep wrapping inside its box, as on screen';
        d.append(why); document.querySelector('main').prepend(d); window.scrollTo(0, 0); }""")
    box = page.locator("#zz-step").bounding_box()
    assert page.evaluate("document.querySelector('#zz-step span').getClientRects()[0].height") >= 60  # (on screen: the why on three lines or more)
    page.keyboard.press("\\")
    page.locator("#fb-win [data-fb-wrap]").wait_for(state="visible", timeout=15000)
    drawn = page.evaluate("""b => { const c = document.querySelector('#fb-win [data-fb-canvas]'), o = document.createElement('canvas');
        o.width = Math.round(b.width); o.height = Math.round(b.height); o.getContext('2d').drawImage(c, b.x, b.y, b.width, b.height, 0, 0, o.width, o.height);
        return o.toDataURL('image/png'); }""", box)
    im = Image.open(io.BytesIO(base64.b64decode(drawn.split(",", 1)[1]))).convert("L")
    third = im.crop((0, 44, im.size[0], 60)).load()  # (the why's second line, under the step's and the why's first: one only wrapping makes)
    assert any(third[x, y] > 170 for x in range(im.size[0]) for y in range(16)), "the why ran on in one line: nothing under its first line"
    assert not admin.errors, admin.errors


def test_a_picture_you_added_can_be_taken_away_and_the_pages_stays(people, server, browser_db, tmp_path):
    """Issue 21 (Brett's round, Nov 18): there was no way to remove a picture he'd added. Each one he adds is one pill,
    its name and its ✕; the ✕ takes it away (the one on the stage moves to its neighbour), and what's sent is what's
    left. The page's own picture has no ✕: it says where you were."""
    from PIL import Image

    for n, colour in ((1, (200, 30, 30)), (2, (30, 30, 200))):
        Image.new("RGB", (600, 400), colour).save(tmp_path / f"p{n}.png")
    admin = people("admin")
    page = admin.open("/party")
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    win.locator("[data-fb-wrap]").wait_for(state="visible", timeout=15000)
    for n in (1, 2):
        win.locator("[data-fb-file]").set_input_files(str(tmp_path / f"p{n}.png"))
        page.wait_for_function(f"() => document.querySelectorAll('#fb-win [data-fb-pic]').length === {n + 1}")
    pics = win.locator("[data-fb-pic]")
    assert pics.nth(0).locator("[data-fb-unpic]").count() == 0  # (the page's own: no ✕)
    assert win.locator("[data-fb-unpic]").count() == 2
    second = pics.nth(2)
    assert "on" in second.get_attribute("class")  # (the one just added is on the stage)
    second.locator("[data-fb-unpic]").click()  # (take away the one on the stage)
    page.wait_for_function("() => document.querySelectorAll('#fb-win [data-fb-pic]').length === 2")
    assert "on" in pics.nth(1).get_attribute("class")  # (its neighbour takes the stage)
    page.wait_for_function("() => { const c = document.querySelector('#fb-win [data-fb-canvas]'); return c.width === 600 && c.getContext('2d').getImageData(5, 5, 1, 1).data[0] > 150; }")
    page.click("[data-fb-kind=problem]")
    page.fill("#fb-win textarea[name=text]", "Two pictures, one taken away.")
    page.click("[data-fb-send]")
    page.locator("#cards > .card").first.wait_for(timeout=10000)
    (nid,), = _rows(browser_db, "SELECT id FROM fft_notes ORDER BY id DESC LIMIT 1")
    assert sorted(k for (k,) in _rows(browser_db, "SELECT kind FROM fft_pictures WHERE note_id = :n", n=nid)) == ["added", "page"]
    assert not admin.errors, admin.errors


def test_a_private_part_in_a_scrolled_box_is_covered_where_it_shows(people, server, browser_db):
    """A standing rule (Brett, 2026-10-17: character notes are visible to players but NOT the DM; T5). The review of PR
    #417 (Nov 18): the private parts were measured after the picture had moved a scrolled box's rows up by its scroll,
    so the covering landed above a player's note in the copy an admin, the DM and Claude see; and a window labelled
    with the note's title kept that label in the page as drawn. The private part is covered where the screen shows it,
    and the label goes."""
    import io

    from PIL import Image

    engine = create_engine(browser_db[0])  # (an account row, so the note is its sender's and Notes you sent serves its full copy)
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO users (email, name, feedback) VALUES ('admin@example.com', 'Dev Admin', true) ON CONFLICT (email) DO NOTHING"))
    engine.dispose()
    admin = people("admin")
    page = admin.open("/party")
    page.wait_for_function("() => document.fonts.status === 'loaded'")
    page.evaluate("""() => {
      const box = Object.assign(document.createElement('div'), { id: 'scrolly' });
      box.setAttribute('aria-label', 'Rob the bank at dawn');  // (a window labelled with a player's note's own title)
      Object.assign(box.style, { position: 'fixed', top: '140px', left: '420px', width: '300px', height: '240px', overflowY: 'auto', zIndex: 40, background: 'rgb(255, 255, 255)' });
      box.innerHTML = '<div style="height: 600px"></div><div data-private style="height: 80px; background: rgb(20, 160, 20); color: white">My secret plan</div><div style="height: 600px"></div>';
      document.body.append(box);
      box.scrollTop = 500;
    }""")
    r = page.evaluate("() => { const e = document.querySelector('#scrolly [data-private]').getBoundingClientRect(); return {x: e.x + e.width / 2, y: e.y + e.height / 2}; }")
    page.keyboard.press("\\")
    win = page.locator("#fb-win")
    win.locator("[data-fb-wrap]").wait_for(state="visible", timeout=15000)
    page.click("[data-fb-kind=problem]")
    page.fill("#fb-win textarea[name=text]", "Scrolled and private.")
    page.click("[data-fb-send]")
    page.locator("#cards > .card").first.wait_for(timeout=10000)
    (pid, full, safe), = _rows(browser_db, "SELECT p.id, p.key, p.safe_key FROM fft_pictures p JOIN fft_notes n ON n.id = p.note_id WHERE n.text = 'Scrolled and private.' AND p.kind = 'page'")
    assert safe and safe != full  # (a safe copy was made)
    base = server["base"]
    shown = Image.open(io.BytesIO(page.request.get(f"{base}/your-notes/pictures/{pid}").body())).convert("RGB")  # (its sender's own)
    covered = Image.open(io.BytesIO(page.request.get(f"{base}/manage/feedback/pictures/{pid}").body())).convert("RGB")  # (what others see)
    sx, sy = shown.size[0] / page.viewport_size["width"], shown.size[1] / page.viewport_size["height"]
    at = (int(r["x"] * sx), int(r["y"] * sy))
    assert shown.getpixel(at)[1] > 120  # (the private part, green, where the screen shows it)
    assert covered.getpixel(at)[1] < 120 or covered.getpixel(at) != shown.getpixel(at)  # (covered there in the safe copy)
    (html,), = _rows(browser_db, "SELECT html FROM fft_notes WHERE text = 'Scrolled and private.'")
    assert "Rob the bank" not in html and "My secret plan" not in html  # (nor its title, in the page as drawn)
    assert not admin.errors, admin.errors
