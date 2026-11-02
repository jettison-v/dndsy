"""The table without modes in real pages (Brett, 2026-10-30, docs/mockups/table-without-modes.html): a roll goes to the
table with nothing to turn on, Only me is remembered, a fight opens Table rolls once, and the roll window says whether a
roll reaches D&D Beyond's Game Log."""

import json
import time

from playwright.sync_api import expect
from sqlalchemy import create_engine, text

from tests.browser.test_table import LOG, battle, newest, save

WINDOW = ".roll-win"
ONLY_ME = f'{WINDOW} [data-to="self"]'


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
    assert page.locator(f'{WINDOW} [data-to="table"]').get_attribute("aria-pressed") == "true"
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#roll-log > li')?.textContent.includes('Dex save')")
    dm.page.wait_for_function("document.querySelector('#roll-log > li')?.textContent.includes('Dex save')", timeout=12000)
    assert "Dex save" in newest(page)
    assert player.errors == [] and dm.errors == []


def test_only_me_is_your_choice_and_stays_until_you_change_it(people, server):
    player = people("player")
    page = battle(player, server)
    page.click(save("Dex"))
    page.locator(ONLY_ME).click()
    page.keyboard.press("Escape")
    page = battle(player, server)  # another page, later
    page.click(save("Dex"))
    assert page.locator(ONLY_ME).get_attribute("aria-pressed") == "true"
    page.locator(f'{WINDOW} [data-to="table"]').click()
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
    roll_with(log="sheet")
    expect(note).to_contain_text("your sheet isn't open")
    page.locator(ONLY_ME).click()
    expect(note).to_be_hidden()  # it isn't going anywhere
    page.locator(f'{WINDOW} [data-to="table"]').click()
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

