"""Pop-ups on Battle in real pages (app.js busyHere; a side chat's fixes, Brett, 2026-10-30): a change landing doesn't
close + Condition or a condition's pill while you're in it, and shows once you've closed it; Prone's icon lies down."""

from tests.browser.test_table import battle

ADD = "details.cond-add"
PRONE = 'details.cond-pill[data-cond="prone"]'


def start(page, name):
    page.locator(f"{ADD} > summary").click()
    page.locator(f"{ADD} .ls-chip", has_text=name).click()
    page.locator(f'details.cond-pill[data-cond="{name.lower()}"]').wait_for()


def end(page, name):
    pill = page.locator(f'details.cond-pill[data-cond="{name.lower()}"]')
    pill.locator("summary").click()
    pill.get_by_role("button", name=f"End {name}").click()
    pill.wait_for(state="detached")


def test_a_change_landing_leaves_an_open_pop_up_alone_and_shows_when_its_closed(people, server):
    mine, other = people("player", "player")
    page, elsewhere = battle(mine, server), battle(other, server)

    page.locator(f"{ADD} > summary").click()
    start(elsewhere, "Prone")  # the change landing, from another screen
    page.wait_for_timeout(3000)  # (past the live message and a retry of the update it holds back)
    assert page.locator(f"{ADD}[open]").count() == 1 and page.locator(PRONE).count() == 0

    page.locator("h1").first.click()  # closed: the update it held back comes in
    page.locator(PRONE).wait_for(timeout=6000)
    assert page.locator(f"{ADD}[open]").count() == 0

    page.locator(f"{PRONE} > summary").click()  # the same for a condition's own pill
    start(elsewhere, "Poisoned")
    page.wait_for_timeout(3000)
    assert page.locator(f"{PRONE}[open]").count() == 1 and page.locator('details.cond-pill[data-cond="poisoned"]').count() == 0
    page.locator("h1").first.click()
    page.locator('details.cond-pill[data-cond="poisoned"]').wait_for(timeout=6000)

    end(page, "Prone")
    end(page, "Poisoned")
    assert mine.errors == [] and other.errors == []


def test_prones_icon_lies_down_on_its_pill_and_badge_and_nothing_else_does(people, server):
    player = people("player")
    page = battle(player, server)
    start(page, "Prone")
    start(page, "Poisoned")
    def shows(where, transform):  # (the page may swap in its new copy meanwhile: asked until it settles)
        page.wait_for_function("([s, t]) => { const e = document.querySelector(s); return e && getComputedStyle(e).transform === t; }",
                               arg=[where, transform], timeout=5000)

    thirty = "matrix(0.866025, -0.5, 0.5, 0.866025, 0, 0)"  # -30 degrees
    shows(f"{PRONE} .cond-icon", thirty)
    shows('.cond-badge[data-cond="prone"] .cond-icon', thirty)
    shows('details.cond-pill[data-cond="poisoned"] .cond-icon', "none")
    shows('.cond-badge[data-cond="poisoned"] .cond-icon', "none")
    end(page, "Prone")
    end(page, "Poisoned")
    assert player.errors == []
