"""Feedback and Notes you sent in a real browser (Found, Fixed, Tried: app/fft/feedback_page.py, app/your_notes.py;
screens 10–15 of docs/mockups/found-fixed-tried/): a player's note waits on To sort; it opens in the item window
(app/fft/item_page.py, The Work Pages, Nov 20), filing it gives a corner card whose Undo puts it back; writing to the
one who sent it reaches their Notes you sent as a new reply."""

from sqlalchemy import create_engine, text

from tests.browser.pages import press


def _waiting_note(url, words="My spell slots came back after a Short Rest."):
    engine = create_engine(url)
    with engine.begin() as conn:
        uid = conn.execute(text("SELECT id FROM users WHERE email = 'player@example.com'")).scalar()
        nid = conn.execute(text("INSERT INTO fft_notes (user_id, first_name, role, kind, text, page, url, workspace_id) VALUES "
                                "(:u, 'Pat', 'player', 'problem', :t, 'Cole · Battle', '/party', 1) RETURNING id"), {"u": uid, "t": words}).scalar()
    engine.dispose()
    return nid


def _one(url, sql, **params):
    engine = create_engine(url)
    with engine.connect() as conn:
        got = conn.execute(text(sql), params).one()
    engine.dispose()
    return got


def _item(page, key):
    """The item window, open on this item (a row pressed, ↑ ↓, or an old ?open= link)."""
    win = page.locator(f'#peek [data-item-panel="{key}"]')
    win.wait_for()
    return page.locator("#peek")


def _issue_of(url, nid):
    return _one(url, "SELECT issue_id FROM fft_notes WHERE id = :i", i=nid)[0]


def test_approve_undo_and_write_to_the_one_who_sent_it(people, server, browser_db):
    nid = _waiting_note(browser_db[0])
    admin, player = people("admin", "player")
    page = admin.open("/manage/feedback")
    assert page.locator('[data-tab="approve"]').get_attribute("class") == "on"  # (To sort first, while a note waits)
    page.locator(f'tr[data-row="n{nid}"] td.dt-title').click()
    win = _item(page, f"n{nid}")
    page.evaluate("window.__stayed = true")
    win.locator('[data-do="fix"]').click()
    card = page.locator("#cards > .card", has=page.locator(".card-act"))
    card.wait_for()
    assert page.evaluate("window.__stayed === true") and "/manage/feedback" in page.url and "tab=open" not in page.url  # (this page stayed)
    assert page.locator(f'tr[data-row="n{nid}"]').count() == 0  # (filed: it left To sort)
    card.locator(".card-act").click()  # Undo
    page.locator(f'tr[data-row="n{nid}"]').wait_for()
    assert _one(browser_db[0], "SELECT state FROM fft_notes WHERE id = :i", i=nid)[0] == "waiting"

    page.locator(f'tr[data-row="n{nid}"] td.dt-title').click()
    press(_item(page, f"n{nid}").locator('[data-do="fix"]'))
    iid = _issue_of(browser_db[0], nid)
    page = admin.open(f"/manage/feedback?tab=open&open=i{iid}")
    issue = _item(page, f"i{iid}").locator("[data-fft-issue]")
    assert issue.locator(".state-line .sw-claude").count() == 1  # (Claude's turn, in its colour)
    composer = issue.locator("[data-composer]")
    composer.locator('input[value="senders"]').check()
    composer.locator("textarea[name=words]").fill("Thanks: it's being fixed.")
    press(composer.locator("button[type=submit]"))  # (the reply saved; the window stays on the issue)
    _item(page, f"i{iid}")

    mine = player.open("/your-notes?tab=askdnd")
    row = mine.locator(f'[data-note="f{nid}"]')
    row.wait_for()
    assert row.locator("[data-new-reply]").count() == 1 and row.locator('[data-turn="claude"]').count() == 1
    lid, = _one(browser_db[0], "SELECT id FROM fft_lines WHERE text = :t", t="Thanks: it's being fixed.")
    assert mine.locator(f'[data-fft-yours-note="{nid}"] [data-line="{lid}"]').count() == 1  # (the reply reached its sender)
    assert not admin.errors, admin.errors
    assert not player.errors, player.errors


def test_the_window_walks_its_list_and_moves_on_after_a_press(people, server, browser_db):
    """The Work Pages (Brett, Nov 20): ↑ ↓ walk the list the window came from; after a press it moves on to the next."""
    first = _waiting_note(browser_db[0], "One.")
    second = _waiting_note(browser_db[0], "Two.")
    admin = people("admin")
    page = admin.open(f"/manage/feedback?tab=approve&open=n{first}")
    _item(page, f"n{first}")
    page.keyboard.press("ArrowDown")
    _item(page, f"n{second}")
    page.keyboard.press("ArrowUp")
    win = _item(page, f"n{first}")
    win.locator('[data-do="fix"]').click()
    _item(page, f"n{second}")  # (filed: on to the next)
    assert page.locator(f'tr[data-row="n{first}"]').count() == 0 and _issue_of(browser_db[0], first) is not None
    assert not admin.errors, admin.errors


def test_same_as_searches_and_joins_in_its_window(people, server, browser_db):
    first = _waiting_note(browser_db[0], "Rests are wrong for my Wizard.")
    second = _waiting_note(browser_db[0], "Same thing after a rest.")
    admin = people("admin")
    page = admin.open(f"/manage/feedback?tab=approve&open=n{first}")
    press(_item(page, f"n{first}").locator('[data-do="fix"]'))
    page = admin.open(f"/manage/feedback?tab=approve&open=n{second}")  # (this note, whatever a failed first try left waiting)
    _item(page, f"n{second}").locator('[data-do="same"]').click()
    page.locator(".peek #fft-same-options").wait_for()
    page.eval_on_selector(".peek #fft-same-options", "el => el.dataset.before = '1'")
    page.locator(".peek input[type=search]").fill("Wizard")
    # (the search's own list, swapped in after its short wait: a pick made before the swap is lost, GitHub Nov 18)
    page.wait_for_function("() => { const o = document.querySelector('.peek #fft-same-options'); return o && !o.dataset.before }")
    assert page.locator(".peek [data-option]").count() == 1
    page.locator(".peek input[type=search]").press("Enter")  # (Enter in the search never joins: nothing is picked for you)
    assert _issue_of(browser_db[0], second) is None
    page.locator('.peek [data-option] input').first.check()
    press(page.locator('.peek [data-do="join"]'))
    issue_a, issue_b = _issue_of(browser_db[0], first), _issue_of(browser_db[0], second)
    assert issue_a == issue_b
    page = admin.open(f"/manage/feedback?tab=open&open=i{issue_a}")
    assert _item(page, f"i{issue_a}").locator(f'[data-fft-issue="{issue_a}"] [data-report]').count() == 2
    assert not admin.errors, admin.errors


def test_back_to_a_window_keeps_what_was_typed(people, server, browser_db):
    """Brett, Nov 17: in Close it: why?, he typed a reason, pressed Same as another issue… by mistake, and ← Back brought
    the window back empty. Back now brings a window back as it was left, its words and picks too."""
    nid = _waiting_note(browser_db[0], "The rest button does nothing.")
    admin = people("admin")
    page = admin.open(f"/manage/feedback?tab=approve&open=n{nid}")
    press(_item(page, f"n{nid}").locator('[data-do="fix"]'))
    iid = _issue_of(browser_db[0], nid)
    page = admin.open(f"/manage/feedback?tab=open&open=i{iid}")
    _item(page, f"i{iid}").locator('[data-fft-issue] [data-do="close"]').click()
    win = page.locator("#peek-top")  # (a window opened from the side panel goes over it: issue 108)
    win.locator('[data-reason="withdrawn"] input').check()
    win.locator("textarea[name=words]").fill("Typed before Same as")
    win.locator('[data-reason="same"]').click()
    win.locator("#fft-same-options").wait_for()
    win.locator(".peek-back").click()
    win.locator('[data-reason="withdrawn"]').wait_for()
    assert win.locator("textarea[name=words]").input_value() == "Typed before Same as"
    assert win.locator('[data-reason="withdrawn"] input').is_checked()
    press(win.locator('[data-do="close"]'))
    assert _one(browser_db[0], "SELECT i.state, i.close_words FROM fft_issues i JOIN fft_notes n ON n.issue_id = i.id WHERE n.id = :i", i=nid) == ("closed", "Typed before Same as")
    assert not admin.errors, admin.errors


def test_picks_on_a_mockup_save_in_askdnd_and_come_back(people, server, browser_db):
    """Brett's round, Nov 18: picks made on a mockup opened inside askdnd were lost (its sealed frame could only save on
    claude.ai). Save my picks hands them to askdnd, which answers the mockup's question with them, and opening the
    mockup again shows them."""
    from app.documents import doc_id

    path = "docs/mockups/fft-round-2/index.html"
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        qid = conn.execute(text("INSERT INTO fft_questions (about, about_id, doc_path, text, choices, workspace_id) VALUES "
                                "('document', NULL, :p, 'Which?', '[]', 1) RETURNING id"), {"p": path}).scalar()
    engine.dispose()
    admin = people("admin")
    admin.allow("lacks the 'allow-same-origin' flag")  # (the test's own watcher, reading storage inside the sealed frame)
    page = admin.open(f"/manage/documents/{doc_id(path)}")
    frame = page.frame_locator("iframe.doc-frame")
    frame.locator('form.decide .saved[data-state="none"]').wait_for()
    for name, value in (("queue", "quiet"), ("split", "issue"), ("shot", "browser")):
        frame.locator(f"input[name={name}][value={value}]").check()
    frame.locator("form.decide textarea").fill("Fifteen minutes is fine.")
    frame.locator("form.decide button[type=submit]").click()
    frame.locator('form.decide .saved[data-state="saved"]').wait_for()
    answered, picks, words = _one(browser_db[0], "SELECT answered_at, picks, answer_text FROM fft_questions WHERE id = :i", i=qid)
    assert answered is not None and [p["value"] for p in picks] == ["quiet", "issue", "browser"]
    assert words.startswith("Picks: 1 A") and words.endswith("Fifteen minutes is fine.")
    again = admin.open(f"/manage/documents/{doc_id(path)}")
    frame = again.frame_locator("iframe.doc-frame")
    frame.locator('form.decide .saved[data-state="loaded"]').wait_for()
    assert frame.locator("input[name=shot][value=browser]").is_checked() and frame.locator("form.decide textarea").input_value() == "Fifteen minutes is fine."


def test_a_question_answered_by_picks_in_its_mockup_leaves_for_you_without_a_reload(people, server, browser_db):
    """Issue 115 (Brett, Nov 24): he saved his picks in Q19's mockup, opened from For you, and the question stayed in
    Decide until he reloaded. Once the window closes, For you redraws itself without it."""
    path = "docs/mockups/fft-round-2/index.html"
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        qid = conn.execute(text("INSERT INTO fft_questions (about, about_id, doc_path, text, choices, workspace_id) VALUES "
                                "('document', NULL, :p, 'Which?', '[]', 1) RETURNING id"), {"p": path}).scalar()
    engine.dispose()
    admin = people("admin")
    admin.allow("lacks the 'allow-same-origin' flag")
    admin.page.route_web_socket("**/live/connect*", lambda ws: ws.close())  # (no live connection, as his page likely had)
    page = admin.open("/manage/for-you")
    row = page.locator(f'main [data-panel-url^="/manage/item/q{qid}"]').first
    row.click()
    page.locator("#peek.open .fft-doc a[data-modal-url]").click()
    frame = page.frame_locator(".peek.full.open iframe.doc-frame")
    # (askdnd has answered the frame: nothing saved yet, or another test's picks on the same mockup when run after it)
    frame.locator('form.decide .saved:is([data-state="none"], [data-state="loaded"])').wait_for()
    for name, value in (("queue", "quiet"), ("split", "issue"), ("shot", "browser")):
        frame.locator(f"input[name={name}][value={value}]").check()
    frame.locator("form.decide button[type=submit]").click()
    frame.locator('form.decide .saved[data-state="saved"]').wait_for()
    page.locator(".peek.full.open .peek-close").click()  # (the mockup's window: the focus is in its frame, so ✕)
    page.locator("#peek.open .peek-close").first.click()  # (then the question's)
    page.wait_for_function("() => !document.querySelector('.peek.open')")
    page.locator(f'main [data-panel-url^="/manage/item/q{qid}"]').wait_for(state="detached", timeout=8000)


def test_a_long_area_heading_wraps_above_its_rows_never_over_them(people, server, browser_db):
    """Brett's round, Nov 18: FEEDBACK AND TESTING wrapped over its first row. A Product Area's heading in Feedback's
    list is the lists' group heading: however long, it pushes its rows down."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO fft_issues (title, feature, workspace_id) VALUES ('Temp HP box is cramped', 'hp', 1)"))
    engine.dispose()
    admin = people("admin")
    page = admin.open("/manage/feedback?tab=open")
    page.set_viewport_size({"width": 1000, "height": 800})
    head = page.locator('#fb-list tr.dt-group[data-group="battle"]')
    head.wait_for()
    head.locator("td").first.evaluate("s => { s.textContent = 'Battle, with a name long enough to wrap onto a second line and a third, and a fourth, and on past the width of the whole table so it must wrap'; s.style.whiteSpace = 'normal'; }")
    box, row = head.bounding_box(), page.locator('#fb-list tr.dt-group[data-group="battle"] + tr').bounding_box()
    assert box["y"] + box["height"] <= row["y"] + 0.5  # (however tall it grows, the row starts below it)


def test_change_and_rename_close_with_cancel_or_escape_and_change_nothing(people, server, browser_db):
    """Issue 25 on askdnd.ai (Brett's round, Nov 18): Change… on an issue opened its picker with only Save, so nothing
    but saving closed it; Rename… the same. Every folded form has Cancel beside its button, and Escape inside it is
    its Cancel; neither changes the issue."""
    nid = _waiting_note(browser_db[0], "The rest button is grey.")
    admin = people("admin")
    page = admin.open(f"/manage/feedback?tab=approve&open=n{nid}")
    press(_item(page, f"n{nid}").locator('[data-do="fix"]'))
    iid, feature, title = _one(browser_db[0], "SELECT i.id, i.feature, i.title FROM fft_issues i JOIN fft_notes n ON n.issue_id = i.id WHERE n.id = :i", i=nid)
    page = admin.open(f"/manage/feedback?tab=open&open=i{iid}")
    _item(page, f"i{iid}")
    form = page.locator(f"#fft-feature-{iid}")
    page.locator('[data-fft-issue] [data-do="feature"]').click()
    assert form.is_visible()
    form.locator("[data-cancel]").click()
    assert form.is_hidden()
    page.locator('[data-fft-issue] [data-do="feature"]').click()
    assert form.is_visible()
    page.keyboard.press("Escape")  # (the picker has the focus: Escape inside it)
    assert form.is_hidden()
    page.locator("[data-fft-issue] details.act-more summary").click()
    page.locator(f'[data-show="fft-title-{iid}"]').click()
    rename = page.locator(f"#fft-title-{iid}")
    rename.locator("input[name=words]").fill("Something else")
    page.keyboard.press("Escape")
    assert rename.is_hidden()
    assert _one(browser_db[0], "SELECT feature, title FROM fft_issues WHERE id = :i", i=iid) == (feature, title)
    assert not admin.errors, admin.errors


def test_comments_pinned_to_a_mockup_go_with_the_picks(people, server, browser_db):
    """Issue 24 (Brett's picks, Nov 21): on any mockup askdnd opens, Comment then a click pins a comment where he clicked;
    the column beside it lists it (Take back while held); Save my picks sends it with his answer, and it says so."""
    from app.documents import doc_id

    path = "docs/mockups/fft-round-2/index.html"
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        qid = conn.execute(text("INSERT INTO fft_questions (about, about_id, doc_path, text, choices, workspace_id) VALUES "
                                "('document', NULL, :p, 'Which?', '[]', 1) RETURNING id"), {"p": path}).scalar()
    engine.dispose()
    admin = people("admin")
    admin.allow("lacks the 'allow-same-origin' flag")  # (the test's own watcher, reading storage inside the sealed frame)
    page = admin.open(f"/manage/documents/{doc_id(path)}")
    frame = page.frame_locator("iframe.doc-frame")
    # (the mockup has heard from askdnd: nothing saved yet, or the picks test before this one's picks loaded)
    frame.locator('form.decide .saved[data-state="none"], form.decide .saved[data-state="loaded"]').wait_for(timeout=20000)
    rail = page.locator("[data-doc-comments]")
    rail.wait_for()
    composer = page.locator("[data-comment-composer]")
    # (issue 102, Brett's note Nov 23: the pin shows where he clicked while he writes, as not sent; Cancel takes it away)
    page.locator("[data-comment-mode]").click()
    frame.locator("h1").first.click()
    composer.wait_for(state="visible")
    frame.locator(".askdnd-pin.draft").wait_for()
    assert frame.locator(".askdnd-pin.draft").get_attribute("data-draft") == "1" and composer.locator(".doc-pin-n.draft").get_attribute("data-n") == "1"
    composer.locator("[data-comment-cancel]").click()
    frame.locator(".askdnd-pin.draft").wait_for(state="detached")
    for n, words in enumerate(("Shorter title here.", "Not this one."), 1):
        page.locator("[data-comment-mode]").click()
        frame.locator("h1").first.click()
        composer.wait_for(state="visible")
        assert frame.locator(".askdnd-pin.draft").get_attribute("data-draft") == str(n)
        composer.locator("textarea").fill(words)
        composer.locator("button[type=submit]").click()
        page.wait_for_function(f"document.querySelectorAll('[data-doc-comments] .doc-comment').length === {n}")
        frame.locator(".askdnd-pin.draft").wait_for(state="detached")
    frame.locator(".askdnd-pin").nth(1).wait_for()  # (both pins drawn on the mockup)
    page.locator("[data-doc-comments] .doc-comment").nth(1).locator("[data-comment-drop]").click()
    page.wait_for_function("document.querySelectorAll('[data-doc-comments] .doc-comment').length === 1")
    frame.locator("input[name=queue][value=quiet]").check()
    frame.locator("form.decide button[type=submit]").click()
    frame.locator('form.decide .saved[data-state="saved"]').wait_for()
    words = _one(browser_db[0], "SELECT answer_text FROM fft_questions WHERE id = :i", i=qid)[0]
    assert "Comments on the mockup:" in words and "Shorter title here." in words and "Not this one." not in words
    page.wait_for_function("!document.querySelector('[data-doc-comments] .doc-comment.held')")  # (sent: no longer held)


def test_send_now_shows_while_comments_wait_and_the_column_keeps_its_place(people, server, browser_db):
    """Issue 116 (Brett, Nov 25): Send now, beside Comment, shows only while a comment of his waits; it sends them and
    goes; the question stays open for his picks. And the column keeps its place without the mockup beside it (a page's
    picture can't copy the sealed frame: the comments slid under the mockup's own picture)."""
    from app.documents import doc_id

    path = "docs/mockups/fft-round-2/index.html"
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        qid = conn.execute(text("INSERT INTO fft_questions (about, about_id, doc_path, text, choices, workspace_id) VALUES "
                                "('document', NULL, :p, 'Which?', '[]', 1) RETURNING id"), {"p": path}).scalar()
    engine.dispose()
    admin = people("admin")
    admin.allow("lacks the 'allow-same-origin' flag")
    page = admin.open(f"/manage/documents/{doc_id(path)}")
    frame = page.frame_locator("iframe.doc-frame")
    page.locator("[data-doc-comments]").wait_for()
    send_now = page.locator("[data-comments-send]")
    assert not send_now.is_visible()  # (nothing waiting)
    page.locator("[data-comment-mode]").click()
    frame.locator("h1").first.click()
    composer = page.locator("[data-comment-composer]")
    composer.wait_for(state="visible")
    composer.locator("textarea").fill("Would a fourth pick change it?")
    composer.locator("button[type=submit]").click()
    send_now.wait_for(state="visible")
    send_now.click()
    send_now.wait_for(state="hidden")
    page.wait_for_function("!document.querySelector('[data-doc-comments] .doc-comment.held')")
    assert _one(browser_db[0], "SELECT answered_at FROM fft_questions WHERE id = :i", i=qid)[0] is None  # (still open for his picks)
    page.evaluate("document.querySelector('.doc-with-comments iframe.doc-frame').remove()")  # (as the picture's copy has it)
    box, col = (page.locator(".doc-with-comments").bounding_box(), page.locator("[data-comments-slot]").bounding_box())
    assert col["x"] > box["x"] + box["width"] / 2  # (still in its own column, on the right)


def test_a_comment_made_on_claude_ai_is_pinned_by_its_words(people, server, browser_db):
    """Item 39, 6 of 6: a comment brought in from claude.ai has no spot, only the words it was pinned to; askdnd lists it
    as made on claude.ai and pins it at those words on the mockup."""
    from app.documents import doc_id

    path = "docs/mockups/work-board/index.html"  # (a mockup no other test pins)
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:  # (its own row each try: a rerun starts clean)
        conn.execute(text("DELETE FROM fft_doc_comments WHERE doc = :p"), {"p": path})
        conn.execute(text("INSERT INTO fft_doc_comments (doc, page, n, x, y, near, words, origin, ext_id, workspace_id) VALUES "
                          "(:p, '', 1, 0, 0, 'How the queue feeds the board', 'Shorter, please.', 'claude.ai', 't1:1', 1)"), {"p": path})
    engine.dispose()
    admin = people("admin")
    admin.allow("lacks the 'allow-same-origin' flag")  # (the test's own watcher, reading storage inside the sealed frame)
    page = admin.open(f"/manage/documents/{doc_id(path)}")
    page.locator('[data-doc-comments] [data-origin="claude.ai"]').wait_for()
    frame = page.frame_locator("iframe.doc-frame")
    pin = frame.locator('.askdnd-pin[data-n="1"]')
    pin.wait_for()
    for _ in range(50):  # (the pin follows its words as the page settles: wait for it to sit by them)
        at, h1 = pin.bounding_box(), frame.locator("#h-qflow").bounding_box()
        if abs(at["y"] - h1["y"]) < 50 and abs(at["x"] - h1["x"]) < 50:
            break
        page.wait_for_timeout(100)
    assert abs(at["y"] - h1["y"]) < 50 and abs(at["x"] - h1["x"]) < 50 and at["y"] > 1000  # (at the words, drawn just above them as every pin is; not the corner)


def test_a_mockup_draws_its_own_picture_for_a_note(people, browser_db):
    """Issue 103 (Brett's note, Nov 23): a note's screenshot came out blank where a mockup was, as askdnd can't read
    inside its sealed frame; the frame's layer draws what it shows and hands the picture back."""
    from app.documents import doc_id

    admin = people("admin")
    admin.allow("lacks the 'allow-same-origin' flag")
    page = admin.open(f"/manage/documents/{doc_id('docs/mockups/fft-round-2/index.html')}")
    page.frame_locator("iframe.doc-frame").locator("h1").first.wait_for()
    png = page.evaluate("""() => new Promise(ok => {
        const f = document.querySelector('iframe.doc-frame');
        addEventListener('message', e => { if (e.source === f.contentWindow && e.data && e.data.askdnd === 'picture') ok(e.data.png); });
        f.contentWindow.postMessage({ askdnd: 'picture', id: 't' }, '*');
    })""")
    assert png.startswith("data:image/jpeg") and len(png) > 5000


def test_a_notes_picture_shows_the_mockup_in_its_window(people, browser_db):
    """Issue 103 (Brett's note, Nov 23): a note sent over an open mockup had a blank window where the mockup was. Its
    own picture is laid over the frame while the page is drawn, so the note's picture shows what the mockup shows."""
    from app.documents import doc_id

    admin = people("admin")
    admin.allow("lacks the 'allow-same-origin' flag")
    page = admin.open(f"/manage/documents/{doc_id('docs/mockups/fft-round-2/index.html')}")
    page.frame_locator("iframe.doc-frame").locator("h1").first.wait_for()
    page.wait_for_function("() => document.fonts.status === 'loaded'")
    page.keyboard.press("\\")
    page.locator("[data-fb-wrap]").wait_for(state="visible", timeout=20000)
    page.wait_for_function("() => { const c = document.querySelector('[data-fb-canvas]'); return c && c.width > 100; }")
    shades = page.evaluate("""() => {  // the shades and light pixels where the mockup is on screen
      const c = document.querySelector('[data-fb-canvas]'), g = c.getContext('2d'), s = c.width / innerWidth;
      const f = document.querySelector('iframe.doc-frame').getBoundingClientRect();
      const top = Math.max(f.top, 0), bottom = Math.min(f.bottom, innerHeight);
      const d = g.getImageData(Math.floor(f.left * s), Math.floor(top * s), Math.floor(f.width * s), Math.floor((bottom - top) * s)).data;
      const seen = new Set();
      for (let i = 0; i < d.length; i += 4) seen.add((d[i] >> 3) + ',' + (d[i + 1] >> 3) + ',' + (d[i + 2] >> 3));
      let light = 0;  // (the mockup's words and boxes; blank, the frame's area is the window's dark ground)
      for (let i = 0; i < d.length; i += 4) if (d[i] > 180 && d[i + 1] > 180 && d[i + 2] > 180) light++;
      return [seen.size, light];
    }""")
    assert shades[0] > 500 and shades[1] > 3000, shades  # (Nov 23: with it, ~1,070 shades and ~9,400 light pixels; blank, ~170 and ~270)


def test_a_window_opened_from_the_side_panel_leaves_it_open(people, server, browser_db):
    """Issue 108 (Brett, Nov 23: "Clicking on these buttons which open a modal should not close the sidebar"): Same as…,
    Split… and Close with a reason… open their window over the issue's side panel; closing it leaves the panel as it was."""
    nid = _waiting_note(browser_db[0], "The rest button does nothing.")
    admin = people("admin")
    page = admin.open(f"/manage/feedback?tab=approve&open=n{nid}")
    press(_item(page, f"n{nid}").locator('[data-do="fix"]'))
    iid = _issue_of(browser_db[0], nid)
    page = admin.open(f"/manage/feedback?tab=open&open=i{iid}")
    for do in ("same", "split", "close"):
        _item(page, f"i{iid}").locator(f'[data-fft-issue] [data-do="{do}"]').click()
        top = page.locator("#peek-top.open")
        top.wait_for()
        assert page.locator(f'#peek.open [data-item-panel="i{iid}"]').count() == 1, do  # (the side panel stays, behind it)
        box, wide = top.bounding_box(), page.evaluate("document.documentElement.clientWidth")  # (the page's width, past its scrollbar)
        assert abs(box["x"] + box["width"] / 2 - wide / 2) < 12, do  # (centred, like any window, give or take a scrollbar)
        page.keyboard.press("Escape")
        page.wait_for_function("() => !document.querySelector('#peek-top.open')")
        assert page.locator(f'#peek.open [data-item-panel="i{iid}"]').count() == 1, do
    assert not admin.errors, admin.errors


def test_the_bars_rows_keep_its_spacing_with_a_round_and_claudes_hands(people, server, browser_db):
    """Issue 107 (Brett, Nov 23: "Spacing is off when below trying a check when Claude has things in its hands"): the
    hands row is a fold, and a fold's own 14px margin opened a gap under the round's row. Each row now sits on the next."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO fft_issues (title, state, kind, workspace_id) VALUES ('No Feature yet', 'to_fix', 'fix', 1)"))
        conn.execute(text("INSERT INTO fft_rounds (user_id, holds, last_at, workspace_id) VALUES (NULL, false, now(), 1)"))
    engine.dispose()
    admin = people("admin")
    page = admin.open("/manage/feedback")  # (Feedback has the bar too: issue 109)
    page.locator('.fft-status [data-stat="hands"]').wait_for()
    gaps = page.evaluate("""() => { const rows = [...document.querySelector('.fft-status').children];
        return rows.slice(1).map((r, i) => Math.round(r.getBoundingClientRect().top - rows[i].getBoundingClientRect().bottom)); }""")
    assert gaps and all(g == 0 for g in gaps), gaps
    assert not admin.errors, admin.errors


def test_a_corner_card_stays_in_the_corner_over_the_side_panel_above_its_foot(people, server, browser_db):
    """Issue 66 (Brett: "The side panel pushes over the notifications"): pushed left by a fixed 494px, a card landed mid-
    page across a wider panel's edge. His answer: bottom right, over the panel, just above its foot."""
    nid = _waiting_note(browser_db[0], "The rest button does nothing.")
    admin = people("admin")
    page = admin.open(f"/manage/feedback?tab=approve&open=n{nid}")
    panel = _item(page, f"n{nid}")
    page.evaluate("askdndToast('Saved')")
    page.locator("#cards > .card.k-ok").wait_for()
    card = page.locator("#cards > .card.k-ok").last.bounding_box()
    wide, high = page.evaluate("[document.documentElement.clientWidth, innerHeight]")
    assert card["x"] + card["width"] > wide - 30  # (in the corner, not pushed beside the panel)
    if panel.locator(".peek-foot").count():
        assert card["y"] + card["height"] <= panel.locator(".peek-foot").first.bounding_box()["y"] + 1  # (above its foot)
    else:
        assert card["y"] + card["height"] > high - 40  # (no foot: the corner itself)
    assert not admin.errors, admin.errors
