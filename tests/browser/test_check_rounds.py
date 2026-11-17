"""Testing in askdnd in a real browser (app/testing.py; Brett's picks 1A, 2A, 3A, Nov 16; docs/mockups/testing/): a round
goes page to page with the step card at the bottom right; Passed moves on; Failed… opens the feedback window naming the
check with Something's broken picked, and the card stays on it for every issue until Done · Next check (2A, Nov 17); —
folds the card to a pill and its top bar drags it to a corner, both drawn so on the next page (6A, notes 83, 85)."""

from sqlalchemy import create_engine, text


def _checks(url, rows):
    engine = create_engine(url)
    with engine.begin() as conn:
        ids = [conn.execute(text("INSERT INTO checks (title, area, setup, path, \"do\", expect, minutes, place) VALUES (:t, 'Test', 'laptop', :p, 'Look.', 'It looks right.', 1, :n) RETURNING id"),
                            {"t": t, "p": p, "n": n}).scalar() for n, (t, p) in enumerate(rows)]
    engine.dispose()
    return ids


def test_a_round_goes_page_to_page_with_its_card(people, server, browser_db):
    one, two, three = _checks(browser_db[0], [("First check", f"/characters/{server['cole']}/battle"), ("Second check", "/c/main/campaign"),
                                              ("Third check", "/party")])
    admin = people("admin")
    page = admin.open("/manage/testing")
    assert page.locator(f'[data-check-read="{one}"]').is_visible()  # (the Reader opens on the first)
    page.locator("[data-round-start]").click()
    page.wait_for_url(f"**/characters/{server['cole']}/battle")
    card = page.locator(f'[data-check-card="{one}"]')
    card.wait_for()
    card.locator('[data-check-result="passed"]').click()
    page.wait_for_url("**/c/main/campaign")
    card = page.locator(f'[data-check-card="{two}"]')
    card.wait_for()

    card.locator("[data-cc-fold]").first.click()  # — folds it to a pill, and it's drawn folded on the next page (note 85)
    assert card.locator(".cc-pill").is_visible() and not card.locator(".cc-body").is_visible()
    page.reload()
    card = page.locator(f'[data-check-card="{two}"]')
    card.wait_for()
    assert "folded" in card.get_attribute("class").split() and not card.locator(".cc-body").is_visible()  # (folded as drawn)
    card.locator(".cc-pill").click()
    assert card.locator(".cc-body").is_visible()

    bar = card.locator("[data-cc-drag]")  # dragged by its top bar to the top left, it stays there (6A, note 83)
    box = bar.bounding_box()
    page.mouse.move(box["x"] + 20, box["y"] + box["height"] / 2)
    page.mouse.down()
    page.mouse.move(60, 160, steps=8)
    page.mouse.up()
    assert card.get_attribute("data-corner") == "tl"
    assert card.bounding_box()["x"] < 100 and card.bounding_box()["y"] < 300

    card.locator('[data-fb-open]:not([data-fb-issue])').first.click()  # Failed…: the feedback window, the check named, broken picked
    win = page.locator("#fb-win")
    win.wait_for()
    assert win.locator("[data-fb-check-line]").is_visible()
    assert win.locator('[data-fb-kind="broken"]').get_attribute("aria-checked") == "true"
    win.locator("textarea[name=text]").fill("It doesn't look right.")
    win.locator("[data-fb-send]").click()
    issue = card.locator("[data-issue]")  # (the card stays on the check, listing it: Brett's 2A)
    issue.first.wait_for()
    card.locator("[data-fb-open]").first.click()  # + Another issue
    win.wait_for()
    win.locator('[data-fb-kind="idea"]').click()
    win.locator("textarea[name=text]").fill("And the heading could be bigger.")
    win.locator("[data-fb-send]").click()
    page.wait_for_function("document.querySelectorAll('[data-check-card] [data-issue]').length === 2")
    card.locator("[data-check-next]").click()  # Done · Next check
    page.wait_for_url("**/party")
    page.locator(f'[data-check-card="{three}"]').wait_for()
    assert page.locator(f'[data-check-card="{three}"]').get_attribute("data-corner") == "tl"  # (where it was left)

    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, status FROM checks WHERE id IN (:a, :b)"), {"a": one, "b": two}).all())
        sent = conn.execute(text("SELECT count(*) FROM feedback WHERE check_id = :b"), {"b": two}).scalar()
    engine.dispose()
    assert rows == {one: "passed", two: "failed"} and sent == 2
    page.locator(f'[data-check-card="{three}"] [data-check-result="skipped"]').click()
    page.wait_for_url("**/manage/testing")
    assert page.locator("[data-check-card]").count() == 0  # (the round is done: no card)
    assert not admin.errors, admin.errors


def test_go_opens_the_checks_page_with_its_card(people, server, browser_db):
    """Brett, Nov 16: Go from the Reader brings the check's card along; Passed comes back to it in the Reader."""
    (only,) = _checks(browser_db[0], [("One check", "/party")])
    admin = people("admin")
    page = admin.open(f"/manage/testing?check={only}")
    page.locator("[data-check-go]").click()
    page.wait_for_url("**/party")
    card = page.locator(f'[data-check-card="{only}"]')
    card.wait_for()
    card.locator('[data-check-result="passed"]').click()
    page.wait_for_url(f"**/manage/testing?show=done&check={only}")
    assert page.locator(f'[data-check-read="{only}"]').is_visible()  # (back to it, where it now is)
    assert page.locator("[data-check-card]").count() == 0
    assert not admin.errors, admin.errors


def test_a_player_says_whether_their_fix_works(people, server, browser_db):
    """Brett's 6C: a fix to a player's note asks them on Notes you sent, Does it work now?; Yes passes its check."""
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        uid = conn.execute(text("SELECT id FROM users WHERE email = 'player@example.com'")).scalar()
        conn.execute(text("UPDATE users SET feedback = true WHERE id = :u"), {"u": uid})
        fb = conn.execute(text("INSERT INTO feedback (user_id, sender, text, kind, status, url) VALUES (:u, 'Cole (player)', 'The panel closes.', 'broken', 'done', '/party') RETURNING id"),
                          {"u": uid}).scalar()
        check = conn.execute(text("INSERT INTO checks (title, setup, path, \"do\", expect, status, feedback_id) VALUES ('The panel stays', 'player', '/party', 'Open it.', 'It stays.', 'again', :f) RETURNING id"),
                             {"f": fb}).scalar()
    engine.dispose()
    player = people("player")
    page = player.open(f"/your-notes?tab=askdnd&note=f{fb}")
    box = page.locator(f'[data-try="{fb}"]')
    box.wait_for()
    box.locator('[data-works="yes"]').click()
    page.wait_for_url(f"**note=f{fb}")
    assert page.locator(f'[data-try="{fb}"]').count() == 0
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        assert conn.execute(text("SELECT status FROM checks WHERE id = :c"), {"c": check}).scalar() == "passed"
    engine.dispose()
    assert not player.errors, player.errors
