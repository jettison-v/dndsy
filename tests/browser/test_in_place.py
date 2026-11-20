"""A press redraws in place (the Live UI Audit, Brett, Nov 19: "only what changed redraws, and nothing needs a refresh";
issue 40, the page flashing on the freeze and lanes). A plain form in a page's main is sent in the background and the
page's new copy goes in through swapMain (app.js "A press redraws in place"): no reload, the scroll where it was, the
corner card says what happened. An answer that is another page still loads it."""

from sqlalchemy import create_engine, text


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


def test_where_it_stands_redraws_in_place(people, server, browser_db):
    """Where it stands (issue 40's page): the answer is a redirect to the same page with its query, drawn in place, the
    address kept."""
    admin = people("admin")
    page = admin.open("/manage/testing?show=stands")
    page.evaluate("window.__stayed = true")
    page.locator(".fft-deploys > summary").click()
    page.locator('[data-mode-pick="frozen"]').click()
    page.locator('#fft-pause-why [data-do="pause"]').click()
    page.locator('.fft-status[data-mode="frozen"]').wait_for()
    assert page.evaluate("window.__stayed === true") and "show=stands" in page.url
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
