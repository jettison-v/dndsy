"""The table without modes in real pages (Brett, 2026-10-30, docs/mockups/table-without-modes.html): a roll goes to the
table with nothing to turn on, Only me is remembered, a fight opens Table rolls once, and the roll window says whether a
roll reaches D&D Beyond's Game Log."""

import json
import re
import time

from playwright.sync_api import expect
from sqlalchemy import create_engine, text

from tests.browser.test_table import LOG, battle, newest, save

WINDOW = ".roll-card"
ONLY_ME = f'{WINDOW} [data-to="self"]'
SEES = f"{WINDOW} .rcard-vis"


def to(page, who: str):
    """Who sees the roll: the card's one line, Change, then the choice (it closes again)."""
    page.locator(f"{WINDOW} [data-vis-open]").click()
    page.locator(f'{WINDOW} [data-to="{who}"]').click()


def fight_starts(browser_db, server, fid):
    engine = create_engine(browser_db[0])
    order = [{"key": "t-e1", "name": "Enemy 1", "kind": "monster", "initiative": 15, "active": True, "hidden": False}]
    with engine.connect() as conn:
        conn.execute(text("UPDATE campaigns SET fight = CAST(:f AS JSONB), fight_at = now() WHERE id = :c"),
                     {"f": json.dumps({"id": fid, "round": 1, "turn": 1, "order": order}), "c": server["campaign"]})
        conn.execute(text("SELECT pg_notify('askdnd_table', :p)"), {"p": json.dumps({"c": server["campaign"], "m": json.dumps({"type": "game"})})})
        conn.commit()
    engine.dispose()


def fight_ends(browser_db, server):
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        conn.execute(text("UPDATE campaigns SET fight = NULL, fight_at = NULL WHERE id = :c"), {"c": server["campaign"]})
        conn.commit()
    engine.dispose()


def test_a_roll_goes_to_the_table_with_nothing_to_turn_on(people, server):
    player, dm = people("player", "dm")
    dm.open("/c/main/")
    dm.live()
    dm.page.wait_for_selector(LOG, state="attached")
    page = battle(player, server)
    page.click(save("Dex"))
    expect(page.locator(SEES)).to_contain_text("The table sees this")
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#roll-log > li')?.textContent.includes('Dex save')")
    dm.page.wait_for_function("document.querySelector('#roll-log > li')?.textContent.includes('Dex save')", timeout=12000)
    assert "Dex save" in newest(page)
    assert player.errors == [] and dm.errors == []


def test_only_me_is_your_choice_and_stays_until_you_change_it(people, server):
    player = people("player")
    page = battle(player, server)
    page.click(save("Dex"))
    to(page, "self")
    expect(page.locator(SEES)).to_contain_text("Only you see this")
    page.keyboard.press("Escape")
    page = battle(player, server)  # another page, later
    page.click(save("Dex"))
    expect(page.locator(SEES)).to_contain_text("Only you see this")
    to(page, "table")
    page.keyboard.press("Escape")
    assert player.errors == []


def test_the_window_says_whether_a_roll_reaches_the_game_log(people, server):
    player = people("player")
    page = battle(player, server)
    player.live()
    note = page.locator(f"{WINDOW} [data-log-note]")

    def roll_with(**log):
        """What the bridge would have said on the Live pill, just before the roll window opens (set each time: the page
        may draw the pill afresh meanwhile, and a busy machine makes that likelier)."""
        page.keyboard.press("Escape")
        page.locator(WINDOW).wait_for(state="detached")
        page.evaluate("log => { const d = document.getElementById('live-pill').dataset; delete d.log; delete d.logUntil; Object.assign(d, log); }", log)
        page.click(save("Dex"))
        page.locator(WINDOW).wait_for()

    roll_with()
    expect(note).to_be_hidden()  # no bridge here: nothing to say
    roll_with(log="sheet", sheet="https://www.dndbeyond.com/characters/75423618")
    expect(note).to_contain_text("your sheet isn't open")
    expect(note).to_have_class(re.compile("rw-log-warn"))  # said loudly, with the way to fix it (connection-drops, Nov 13)
    expect(note.locator("a")).to_have_attribute("href", "https://www.dndbeyond.com/characters/75423618")
    # The sheet connects while the card is open: its line follows at once (Brett, Nov 13), the card stays where it is
    # (where it is beside its button: a card follows its button when the page moves under it, by design; on GitHub's
    # machines the page shifted a few pixels as the connection changed, Nov 13, and the card rightly went with it)
    beside = lambda: page.locator(WINDOW).bounding_box()["y"] - page.locator(save("Dex")).bounding_box()["y"]
    was = beside()
    page.evaluate("until => { Object.assign(document.getElementById('live-pill').dataset, { log: 'on', logUntil: until }); document.dispatchEvent(new Event('askdnd:pill')); }", str(time.time() + 60))
    expect(note).to_contain_text("Also goes to D&D Beyond's Game Log")
    expect(note).not_to_have_class(re.compile("rw-log-warn"))
    assert abs(beside() - was) < 2  # (less than a pixel or two of rounding)
    to(page, "self")
    expect(note).to_be_hidden()  # it isn't going anywhere
    to(page, "table")
    roll_with(log="on", logUntil=str(time.time() + 60))
    expect(note).to_contain_text("Also goes to D&D Beyond's Game Log")
    roll_with(log="on", logUntil=str(time.time() - 1))  # not heard for a while
    expect(note).to_contain_text("your sheet isn't open")
    page.keyboard.press("Escape")
    assert player.errors == []


def test_a_fight_opens_table_rolls_once_and_then_it_stays_as_you_leave_it(people, server, browser_db):
    player = people("player")
    page = battle(player, server)
    player.live()
    is_open = "document.body.classList.contains('rolls-open')"
    page.evaluate("document.querySelector('.rs-toggle').click()")
    page.wait_for_function(f"!({is_open})")
    try:
        fight_starts(browser_db, server, "one")
        page.wait_for_function(is_open, timeout=6000)
        page.evaluate("document.querySelector('.rs-toggle').click()")
        page.wait_for_function(f"!({is_open})")
        fight_starts(browser_db, server, "one")  # the next turn of the same fight
        page.wait_for_timeout(2500)
        assert not page.evaluate(is_open)
        fight_starts(browser_db, server, "two")  # another fight
        page.wait_for_function(is_open, timeout=6000)
    finally:
        fight_ends(browser_db, server)
    assert player.errors == []


def test_rolls_made_while_you_were_away_dont_replay_when_you_come_back(people, server):
    """Brett, 2026-10-30: back from the VTT to askdnd, five or six rolls played in a row."""
    player, dm = people("player", "dm")
    watching = dm.open("/c/main/party")
    dm.live()
    watching.wait_for_selector(LOG, state="attached")
    watching.evaluate("document.querySelector('.rs-toggle').click()")  # Table rolls closed
    watching.wait_for_function("document.body.classList.contains('rolls-closed')")
    cards = watching.locator("#cards > .card")
    watching.evaluate("""() => {
        Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => window.__seen });
        window.__seen = 'hidden';
        document.dispatchEvent(new Event('visibilitychange'));
    }""")  # the DM goes to the VTT
    page = battle(player, server)
    for ability in ("Dex", "Con", "Wis"):
        page.click(save(ability), modifiers=["Shift"])
        page.wait_for_function(f"document.querySelector('#roll-log > li')?.textContent.includes('{ability} save')")
        page.keyboard.press("Escape")
    watching.wait_for_timeout(1000)
    assert cards.count() == 0
    watching.evaluate("window.__seen = 'visible'; document.dispatchEvent(new Event('visibilitychange'))")  # back
    card = watching.locator("#cards > .card", has_text="while you were away")
    card.wait_for(timeout=5000)
    assert "3 rolls" in card.inner_text() and cards.count() == 1
    card.locator(".card-act").click()
    watching.wait_for_function("document.body.classList.contains('rolls-open')")
    assert "Wis save" in newest(watching)



def test_others_rolls_are_full_screen_unless_you_chose_the_dice_tray(people, server):
    """Brett, 2026-11-03: someone else's roll is thrown across the whole screen with who rolled; the dice tray (Labs,
    each person's own in Your dice) puts it in the bottom-left corner instead."""
    player, dm = people("player", "dm")
    dm.context.add_init_script("localStorage.setItem('askdnd.rollsAnim', 'on')")  # (after Person's own, which turns dice off)
    watching = dm.open("/c/main/party")
    dm.live()
    page = player.open(f"/characters/{server['cole']}/battle")
    dex = '[data-roll=save][data-label="Dex save"]:visible >> nth=0'
    page.wait_for_selector(dex)
    page.click(dex, modifiers=["Shift"])
    watching.wait_for_selector(".dice-throw.others", timeout=15000)
    assert "Dex save" in watching.locator(".dice-throw .dt-who").inner_text()
    assert watching.locator(".dice-tray.up").count() == 0
    watching.evaluate("""async () => {
        const f = new FormData(); f.append('set', 'bronze'); f.append('material', 'glass'); f.append('tray', '1');
        await fetch('/dice', {method: 'POST', body: f});
    }""")  # Your dice › Dice tray
    watching.reload()
    dm.live()
    watching.wait_for_function("JSON.parse(document.body.dataset.dice).tray === true")
    page.keyboard.press("Escape")
    page.click(dex, modifiers=["Shift"])
    watching.wait_for_selector(".dice-tray.up", timeout=15000)
    assert "Dex save" in watching.locator(".dice-tray").inner_text()
    box = watching.locator(".dice-tray").bounding_box()  # grows with the window, twice as wide as tall (feedback 7)
    assert box["width"] >= 300 and abs(box["height"] - box["width"] / 2) < 2
    assert player.errors == [] and dm.errors == []
