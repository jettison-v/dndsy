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


def test_a_long_button_stays_inside_its_window(people, server):
    """Brett, 2026-10-30: a button with a long label ran out of the roll window; fixed for every window at once."""
    player = people("player")
    page = battle(player, server)
    page.click('[data-roll=save][data-label="Dex save"]:visible >> nth=0', modifiers=["Shift"])
    page.locator(".roll-win").wait_for()
    label = "Roll damage (1d8 force + 4 spellcasting ability modifier + 2d6 radiant from an extra long feature name)"
    spilled = page.evaluate("""label => ['.roll-win', '#cards'].map(where => {
        const box = document.querySelector(where), b = document.createElement('button');
        if (where === '#cards') { box.innerHTML = '<div class="card"></div>'; }
        const host = where === '#cards' ? box.firstChild : box;
        b.className = 'btn primary'; b.textContent = label; host.append(b);
        const out = b.getBoundingClientRect().right - host.getBoundingClientRect().right;
        b.remove();
        return out;
    })""", label)
    assert all(x <= 0 for x in spilled), spilled
    page.keyboard.press("Escape")
    page.locator('[data-tour="battle"] .head-add').first.click()  # the side panel
    page.locator(".peek.open .peek-body").wait_for()
    out = page.evaluate("""label => {
        const box = document.querySelector('.peek.open .peek-body'), b = document.createElement('button');
        b.className = 'btn primary'; b.textContent = label; box.append(b);
        return b.getBoundingClientRect().right - box.getBoundingClientRect().right;
    }""", label)
    assert out <= 0, out



def test_a_picture_opens_large_and_a_tap_closes_it(people, server):
    """Feedback 44 (Mark, Nov 7): tapping a picture shows it large over the page; a picture that is a button keeps
    opening what it opens."""
    player = people("player")
    page = battle(player, server)
    dot = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    page.evaluate("""src => {
      const a = document.createElement('img'); a.className = 'ws-pic'; a.id = 'pic-plain'; a.src = src; a.width = 40; a.height = 40;
      const b = document.createElement('button'); b.type = 'button'; b.id = 'pic-button';
      const c = document.createElement('img'); c.className = 'ws-pic'; c.src = src; c.width = 40; c.height = 40; b.append(c);
      document.querySelector('h1').after(a, b);
    }""", dot)
    page.click("#pic-plain")
    assert page.locator("dialog.pic-big[open] img").is_visible()
    page.mouse.click(5, 5)
    page.wait_for_function("!document.querySelector('dialog.pic-big')")
    page.click("#pic-button img")
    assert page.locator("dialog.pic-big").count() == 0
    assert player.errors == []
