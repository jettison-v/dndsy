"""The roll card in real pages (Labs `roll_card`; Brett chose the Roll Card Prototype, Nov 9): Cole's Unarmed Strike asks
first (Damage, Grapple or Shove), rolls to hit with an added die, then its damage, each into Table rolls; Grapple sends
its DC; the DM sees the attack live; with the switch off, the roll window opens as before."""

import json
import time

from sqlalchemy import create_engine, text

from tests.browser.test_table import battle

UNARMED = '[data-plan][data-label="Unarmed Strike"]:visible >> nth=0'


def _pieces(browser_db, server, pieces):
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        was = conn.execute(text("SELECT vtt_pieces FROM campaigns WHERE id = :c"), {"c": server["campaign"]}).scalar()
        conn.execute(text("UPDATE campaigns SET vtt_pieces = CAST(:v AS jsonb) WHERE id = :c"), {"v": json.dumps(pieces), "c": server["campaign"]})
    engine.dispose()
    return was


def _battle_with(person, server, on: bool):
    """Battle once the page shows the switch as set (the server keeps a campaign's switches for a few seconds)."""
    for _ in range(40):
        page = battle(person, server)
        if page.evaluate("document.body.hasAttribute('data-roll-card')") == on:
            return page
        time.sleep(0.5)
    raise AssertionError("The roll card's switch never reached the page")


def test_an_attack_on_the_roll_card_and_the_dm_sees_it(people, server, browser_db):
    was = _pieces(browser_db, server, ["sync", "labs", "roll_card"])
    try:
        player, dm = people("player", "dm")
        page = _battle_with(player, server, True)
        dm_page = dm.open("/party")
        page.locator(UNARMED).click()
        card = page.locator(".roll-card")
        card.locator("[data-choice]").first.wait_for()
        assert card.locator("[data-choice]").all_inner_texts()[0].startswith("Damage") and card.locator("[data-choice]").count() == 3
        card.locator('[data-choice="damage"]').click()
        card.locator("[data-adding]").click()
        card.locator('[data-add="+1d4"]').click()
        assert "+1d4" in card.locator("[data-roll-hit]").inner_text()
        card.locator("[data-roll-hit]").click()
        card.locator("[data-roll-dmg], [data-missed]").first.wait_for()
        assert "to hit" in card.inner_text().lower() and "Added" in card.inner_text()
        dm_page.wait_for_function("document.querySelector('#roll-log > li') && /Unarmed Strike/.test(document.querySelector('#roll-log > li').innerText)")
        if card.locator("[data-roll-dmg]").count():  # (a natural 1 offers no damage)
            card.locator("[data-roll-dmg]").click()
            card.locator("[data-done]").wait_for()
            assert "damage" in card.inner_text().lower()
            page.wait_for_function("/Damage/.test(document.querySelector('#roll-log > li').innerText)")
        card.locator("[data-done], [data-missed]").first.click()
        assert page.locator(".roll-card").count() == 0
        # Grapple: no roll of yours, the DC for the DM
        page.locator(UNARMED).click()
        page.locator('.roll-card [data-choice="grapple"]').click()
        page.locator(".roll-card [data-done]").wait_for()
        assert "DC" in page.locator(".roll-card").inner_text()
        page.wait_for_function("/Grapple/.test(document.querySelector('#roll-log > li').innerText)")
        assert player.errors == [] and dm.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_with_the_switch_off_the_roll_window_opens_as_before(people, server, browser_db):
    was = _pieces(browser_db, server, ["sync"])
    try:
        player = people("player")
        page = _battle_with(player, server, False)
        page.locator(UNARMED).click()
        page.locator(".roll-win").wait_for()
        assert page.locator(".roll-card").count() == 0 and page.locator(".roll-win [data-go]").count() == 1
        page.keyboard.press("Escape")
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)

