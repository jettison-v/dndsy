"""Testing in askdnd in a real browser (app/testing.py; Brett's picks 1A, 2A, 3A, Nov 16; docs/mockups/testing/): a round
goes page to page with the step card at the bottom right; Passed moves on; Failed… opens the feedback window naming the
check with Something's broken picked, and sending it goes on to the next check's page; — folds the card to a pill."""

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

    card.locator("[data-cc-fold]").first.click()  # — folds it to a pill, and the pill stays folded on the next page
    assert card.locator(".cc-pill").is_visible() and not card.locator(".cc-body").is_visible()
    card.locator(".cc-pill").click()
    assert card.locator(".cc-body").is_visible()

    card.locator("[data-fb-open]").click()  # Failed…: the feedback window, the check named, broken picked
    win = page.locator("#fb-win")
    win.wait_for()
    assert win.locator("[data-fb-check-line]").is_visible()
    assert win.locator('[data-fb-kind="broken"]').get_attribute("aria-checked") == "true"
    win.locator("textarea[name=text]").fill("It doesn't look right.")
    win.locator("[data-fb-send]").click()
    page.wait_for_url("**/party")
    page.locator(f'[data-check-card="{three}"]').wait_for()

    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        rows = dict(conn.execute(text("SELECT id, status FROM checks WHERE id IN (:a, :b)"), {"a": one, "b": two}).all())
        failed_with = conn.execute(text("SELECT failed_id FROM checks WHERE id = :b"), {"b": two}).scalar()
    engine.dispose()
    assert rows == {one: "passed", two: "failed"} and failed_with
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
