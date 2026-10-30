"""Pop-ups on Battle in real pages (app.js busyHere; a side chat's fixes, Brett, 2026-10-30): a change landing doesn't
close + Condition or a condition's pill while you're in it, and shows once you've closed it; Prone's icon lies down."""

from tests.browser.test_table import battle

ADD = "details.cond-add"
PRONE = 'details.cond-pill[data-cond="prone"]'


def change(person, name, how=""):
    """Start or end a condition as another screen would, without the page's own swaps in the way."""
    r = person.context.request.post(f"{person.server['base']}/characters/{person.server['cole']}/conditions{how}", form={"name": name})
    assert r.ok, r.status


def test_a_change_landing_leaves_an_open_pop_up_alone_and_shows_when_its_closed(people, server):
    mine, other = people("player", "player")
    page = battle(mine, server)
    try:
        page.locator(f"{ADD} > summary").click()
        change(other, "Prone")  # the change landing, from another screen
        page.wait_for_timeout(3000)  # (past the live message and a retry of the update it holds back)
        assert page.locator(f"{ADD}[open]").count() == 1 and page.locator(PRONE).count() == 0

        page.locator("h1").first.click()  # closed: the update it held back comes in
        page.locator(PRONE).wait_for(timeout=6000)
        assert page.locator(f"{ADD}[open]").count() == 0

        page.locator(f"{PRONE} > summary").click()  # the same for a condition's own pill
        change(other, "Poisoned")
        page.wait_for_timeout(3000)
        assert page.locator(f"{PRONE}[open]").count() == 1 and page.locator('details.cond-pill[data-cond="poisoned"]').count() == 0
        page.locator("h1").first.click()
        page.locator('details.cond-pill[data-cond="poisoned"]').wait_for(timeout=6000)
        assert mine.errors == [] and other.errors == []
    finally:
        change(other, "Prone", "/end")
        change(other, "Poisoned", "/end")


def test_prones_icon_lies_down_on_its_pill_and_badge_and_nothing_else_does(people, server):
    player = people("player")
    change(player, "Prone")
    change(player, "Poisoned")
    page = battle(player, server)

    def shows(where, transform):  # (the page may swap in its new copy meanwhile: asked until it settles)
        page.wait_for_function("([s, t]) => { const e = document.querySelector(s); return e && getComputedStyle(e).transform === t; }",
                               arg=[where, transform], timeout=5000)

    thirty = "matrix(0.866025, -0.5, 0.5, 0.866025, 0, 0)"  # -30 degrees
    shows(f"{PRONE} .cond-icon", thirty)
    shows('.cond-badge[data-cond="prone"] .cond-icon', thirty)
    shows('details.cond-pill[data-cond="poisoned"] .cond-icon', "none")
    shows('.cond-badge[data-cond="poisoned"] .cond-icon', "none")
    change(player, "Prone", "/end")
    change(player, "Poisoned", "/end")
    assert player.errors == []
