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
    win = page.locator("#peek")
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
    for n, words in enumerate(("Shorter title here.", "Not this one."), 1):
        page.locator("[data-comment-mode]").click()
        frame.locator("h1").first.click()
        composer = page.locator("[data-comment-composer]")
        composer.wait_for(state="visible")
        composer.locator("textarea").fill(words)
        composer.locator("button[type=submit]").click()
        page.wait_for_function(f"document.querySelectorAll('[data-doc-comments] .doc-comment').length === {n}")
    frame.locator(".askdnd-pin").nth(1).wait_for()  # (both pins drawn on the mockup)
    page.locator("[data-doc-comments] .doc-comment").nth(1).locator("[data-comment-drop]").click()
    page.wait_for_function("document.querySelectorAll('[data-doc-comments] .doc-comment').length === 1")
    frame.locator("input[name=queue][value=quiet]").check()
    frame.locator("form.decide button[type=submit]").click()
    frame.locator('form.decide .saved[data-state="saved"]').wait_for()
    words = _one(browser_db[0], "SELECT answer_text FROM fft_questions WHERE id = :i", i=qid)[0]
    assert "Comments on the mockup:" in words and "Shorter title here." in words and "Not this one." not in words
    page.wait_for_function("!document.querySelector('[data-doc-comments] .doc-comment.held')")  # (sent: no longer held)
