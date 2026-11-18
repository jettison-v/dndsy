"""Feedback and Notes you sent in a real browser (Found, Fixed, Tried: app/fft/feedback_page.py, app/your_notes.py;
screens 10–15 of docs/mockups/found-fixed-tried/): a player's note waits on To approve; approving it gives a corner
card whose Undo puts it back; writing to the one who sent it reaches their Notes you sent as a new reply."""

from sqlalchemy import create_engine, text


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


def test_approve_undo_and_write_to_the_one_who_sent_it(people, server, browser_db):
    nid = _waiting_note(browser_db[0])
    admin, player = people("admin", "player")
    page = admin.open("/manage/feedback")
    art = page.locator(f'[data-fft-note="{nid}"]')
    art.wait_for()
    assert page.locator('[data-tab="approve"]').get_attribute("class") == "on"
    art.locator('[data-do="issue"]').click()
    page.wait_for_url("**/manage/feedback?tab=open&open=i*")
    card = page.locator("#cards > .card", has=page.locator(".card-act"))
    card.wait_for()
    card.locator(".card-act").click()  # Undo
    page.wait_for_url("**/manage/feedback?tab=approve&open=n*")
    assert _one(browser_db[0], "SELECT state FROM fft_notes WHERE id = :i", i=nid)[0] == "waiting"

    page.locator(f'[data-fft-note="{nid}"] [data-do="issue"]').click()
    page.wait_for_url("**/manage/feedback?tab=open&open=i*")
    issue = page.locator("[data-fft-issue]")
    assert issue.locator(".state-line .sw-claude").count() == 1  # (Claude's turn, in its colour)
    composer = issue.locator("[data-composer]")
    composer.locator('input[value="senders"]').check()
    composer.locator("textarea[name=words]").fill("Thanks: it's being fixed.")
    composer.locator("button[type=submit]").click()
    page.wait_for_url("**/manage/feedback?**")

    mine = player.open("/your-notes?tab=askdnd")
    row = mine.locator(f'[data-note="f{nid}"]')
    row.wait_for()
    assert row.locator("[data-new-reply]").count() == 1 and row.locator('[data-turn="claude"]').count() == 1
    assert "it's being fixed" in mine.locator(f'[data-fft-yours-note="{nid}"]').inner_text()
    assert not admin.errors, admin.errors
    assert not player.errors, player.errors


def test_same_as_searches_and_joins_in_its_window(people, server, browser_db):
    first = _waiting_note(browser_db[0], "Rests are wrong for my Wizard.")
    second = _waiting_note(browser_db[0], "Same thing after a rest.")
    admin = people("admin")
    page = admin.open(f"/manage/feedback?tab=approve&open=n{first}")
    page.locator(f'[data-fft-note="{first}"] [data-do="issue"]').click()
    page.wait_for_url("**/manage/feedback?tab=approve**")  # (on to the next waiting)
    page.locator(f'[data-fft-note="{second}"] [data-do="same"]').click()
    page.locator(".peek #fft-same-options").wait_for()
    page.locator(".peek input[type=search]").fill("Wizard")
    page.locator('.peek [data-option]').first.wait_for()
    page.locator('.peek [data-option] input').first.check()
    page.locator('.peek [data-do="join"]').click()
    page.wait_for_url("**/manage/feedback?tab=open&open=i*")
    (issue_a,), (issue_b,) = _one(browser_db[0], "SELECT issue_id FROM fft_notes WHERE id = :i", i=first), _one(browser_db[0], "SELECT issue_id FROM fft_notes WHERE id = :i", i=second)
    assert issue_a == issue_b and page.locator(f'[data-fft-issue="{issue_a}"] [data-report]').count() == 2
    assert not admin.errors, admin.errors


def test_back_to_a_window_keeps_what_was_typed(people, server, browser_db):
    """Brett, Nov 17: in Close it: why?, he typed a reason, pressed Same as another issue… by mistake, and ← Back brought
    the window back empty. Back now brings a window back as it was left, its words and picks too."""
    nid = _waiting_note(browser_db[0], "The rest button does nothing.")
    admin = people("admin")
    page = admin.open(f"/manage/feedback?tab=approve&open=n{nid}")
    page.locator(f'[data-fft-note="{nid}"] [data-do="issue"]').click()
    page.wait_for_url("**/manage/feedback?tab=open&open=i*")
    page.locator('[data-fft-issue] [data-do="close"]').click()
    win = page.locator("#peek")
    win.locator('[data-reason="withdrawn"] input').check()
    win.locator("textarea[name=words]").fill("Typed before Same as")
    win.locator('[data-reason="same"]').click()
    win.locator("#fft-same-options").wait_for()
    win.locator(".peek-back").click()
    win.locator('[data-reason="withdrawn"]').wait_for()
    assert win.locator("textarea[name=words]").input_value() == "Typed before Same as"
    assert win.locator('[data-reason="withdrawn"] input').is_checked()
    win.locator('[data-do="close"]').click()
    page.wait_for_url("**/manage/feedback?**")
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
    said = frame.locator("form.decide .saved")
    said.filter(has_text="Nothing saved yet").wait_for()
    for name, value in (("queue", "quiet"), ("split", "issue"), ("shot", "browser")):
        frame.locator(f"input[name={name}][value={value}]").check()
    frame.locator("form.decide textarea").fill("Fifteen minutes is fine.")
    frame.locator("form.decide button[type=submit]").click()
    said.filter(has_text="Saved in askdnd").wait_for()
    answered, picks, words = _one(browser_db[0], "SELECT answered_at, picks, answer_text FROM fft_questions WHERE id = :i", i=qid)
    assert answered is not None and [p["value"] for p in picks] == ["quiet", "issue", "browser"]
    assert words.startswith("Picks: 1 A") and words.endswith("Fifteen minutes is fine.")
    again = admin.open(f"/manage/documents/{doc_id(path)}")
    frame = again.frame_locator("iframe.doc-frame")
    frame.locator("form.decide .saved").filter(has_text="these are your picks").wait_for()
    assert frame.locator("input[name=shot][value=browser]").is_checked() and frame.locator("form.decide textarea").input_value() == "Fifteen minutes is fine."
