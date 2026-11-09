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


def _sees(page, words: str, seconds: int = 20):
    """The newest rolls this person may see, from Table rolls' own address (a closed sidebar loads none), include these words."""
    for _ in range(seconds * 2):
        if words in page.evaluate("fetch('/rolls?since=-1').then(r => r.text())"):
            return
        time.sleep(0.5)
    raise AssertionError(f"{words} never reached Table rolls")


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
        _sees(dm_page, "Unarmed Strike")
        if card.locator("[data-roll-dmg]").count():  # (a natural 1 offers no damage)
            card.locator("[data-roll-dmg]").click()
            card.locator("[data-done]").wait_for()
            assert "damage" in card.inner_text().lower()
            _sees(page, "Damage")
        card.locator("[data-done], [data-missed]").first.click()
        assert page.locator(".roll-card").count() == 0
        # Grapple: no roll of yours, the DC for the DM
        page.locator(UNARMED).click()
        page.locator('.roll-card [data-choice="grapple"]').click()
        page.locator(".roll-card [data-done]").wait_for()
        assert "DC" in page.locator(".roll-card").inner_text()
        _sees(page, "Grapple")
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



def test_flat_damage_of_0_is_said_before_the_roll(people, server, browser_db):
    """Feedback (Nov 9): the roll window warns when an attack can only do 0 damage (1 + Strength −1); the card does too,
    and its header keeps the 0."""
    was = _pieces(browser_db, server, ["sync", "labs", "roll_card"])
    try:
        player = people("player")
        page = _battle_with(player, server, True)
        page.locator(UNARMED).evaluate("""b => { const p = JSON.parse(b.dataset.plan);
            p.damage = [{dice: '', flat: 0, type: 'bludgeoning', from: 'Unarmed Strike'}]; b.dataset.plan = JSON.stringify(p); }""")
        page.locator(UNARMED).click()
        card = page.locator(".roll-card")
        card.locator('[data-choice="damage"]').click()
        assert "0 bludgeoning" in card.locator(".rcard-sub").inner_text()
        assert "0 damage" in card.locator("[data-flat-note]").inner_text()
        page.keyboard.press("Escape")
        # A mastery on a miss (Graze) is said once the roll's in; a die can be taken off (Bane)
        page.locator(UNARMED).evaluate("""b => { const p = JSON.parse(b.dataset.plan);
            p.riders = [{name: 'Graze', when: 'miss', says: 'On a miss, damage equal to the ability modifier', on: 'mastery'}]; b.dataset.plan = JSON.stringify(p); }""")
        page.locator(UNARMED).click()
        card.locator('[data-choice="damage"]').click()
        card.locator("[data-adding]").click()
        card.locator('[data-add="-1d4"]').click()
        assert "-1d4" in card.locator("[data-roll-hit]").inner_text()
        card.locator("[data-roll-hit]").click()
        card.locator("[data-riders]").wait_for()
        assert "On a miss" in card.inner_text() and "Graze" in card.locator("[data-riders]").inner_text()
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_hidden_the_card_says_the_attack_ends_it_and_you_can_untick_it(people, server, browser_db):
    """Feedback (Nov 9): the card ended Hidden without a word, where the roll window offers "This attack ends Hidden"
    ticked (app/hiding.py; the DM may rule otherwise). Unticked, nothing ends."""
    was = _pieces(browser_db, server, ["sync", "labs", "roll_card"])
    try:
        player = people("player")
        page = _battle_with(player, server, True)
        page.evaluate("document.querySelector('#battle-body').dataset.hidden = '17'")
        ended = []
        page.on("request", lambda r: ended.append(r.url) if r.url.endswith("/conditions/end") else None)
        page.locator(UNARMED).click()
        card = page.locator(".roll-card")
        card.locator('[data-choice="damage"]').click()
        pill = card.locator("[data-ends-hidden]")
        assert pill.get_attribute("aria-pressed") == "true" and "ends Hidden" in pill.inner_text()
        pill.click()
        assert card.locator("[data-ends-hidden]").get_attribute("aria-pressed") == "false"
        card.locator("[data-roll-hit]").click()
        card.locator("[data-roll-dmg], [data-missed]").first.wait_for()
        page.wait_for_timeout(300)
        assert ended == [] and player.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_an_attack_spell_on_the_card_at_its_level(people, server, browser_db):
    """Next slice (Nov 9): an attack spell's damage from its recipe, a cantrip's at the character's level (Cole's Starry
    Wisp: 2d8 at level 8), sent with the attack, so its damage rolls from the card."""
    was = _pieces(browser_db, server, ["sync", "labs", "roll_card"])
    try:
        player = people("player")
        page = _battle_with(player, server, True)
        wisp = page.locator('[data-plan][data-label="Starry Wisp"]:visible >> nth=0')
        if not wisp.count():  # (pinned rows only: from See all otherwise)
            page.locator('[data-panel-url*="/all/action"]').first.click()
            wisp = page.locator('.peek [data-plan][data-label="Starry Wisp"] >> nth=0')
        wisp.click()
        card = page.locator(".roll-card")
        card.locator("[data-roll-hit]").wait_for()
        assert "2d8" in card.locator(".rcard-sub").inner_text()
        card.locator("[data-roll-hit]").click()
        card.locator("[data-roll-dmg], [data-missed]").first.wait_for()
        if card.locator("[data-roll-dmg]").count():
            assert "2d8" in card.locator("[data-roll-dmg]").inner_text()
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_a_save_spell_on_the_card(people, server, browser_db):
    """Save spells (Nov 9): the save and its DC first, Cast at when the level changes the dice (Cole's Moonbeam: 2d10 at
    level 2, 3d10 at 3), then its damage and what a success takes."""
    was = _pieces(browser_db, server, ["sync", "labs", "roll_card"])
    try:
        player = people("player")
        page = _battle_with(player, server, True)
        page.locator('[data-panel-url*="/all/action"]').first.click()
        page.locator('.peek [data-roll="damage"][data-label="Moonbeam"]').first.click()
        card = page.locator(".roll-card")
        card.locator("[data-roll-save]").wait_for()
        assert "Con save, DC" in card.locator(".rcard-sub").inner_text() and "2d10" in card.locator(".rcard-sub").inner_text()
        assert "half damage on a success" in card.inner_text()
        card.locator("[data-card-slot]").select_option("3")
        assert "3d10" in card.locator(".rcard-sub").inner_text()
        card.locator("[data-roll-save]").click()
        card.locator("[data-done]").wait_for(timeout=20000)
        assert "damage on a failed save" in card.inner_text().lower() and "On a success" in card.inner_text()
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_the_roll_button_finds_a_check_by_typing(people, server):
    """Checks and saves (Brett chose A, Nov 9, docs/mockups/find-checks/): Table rolls' Roll button opens a search over
    the character's skills, saves and checks; typing narrows it, Enter rolls the first; Escape closes it."""
    player = people("player")
    page = battle(player, server)
    if page.evaluate("document.body.classList.contains('rolls-closed')"):
        page.locator(".rs-edge").click()
    page.locator("[data-rs-roll]").click()
    q = page.locator(".rs-pick-q")
    page.locator("#rs-pick .rc").first.wait_for()
    q.fill("ste")
    shown = page.locator("#rs-pick .rc:not([hidden])")
    assert shown.count() == 1 and "Stealth" in shown.first.inner_text()
    q.fill("dex")
    assert page.locator("#rs-pick .rc:not([hidden])").count() >= 3  # (its skills, the save and the check)
    q.fill("stealth")
    q.press("Enter")
    page.locator(".roll-win").wait_for()
    assert "Stealth check" in page.locator(".roll-win").inner_text()
    assert page.locator("#rs-pick").is_hidden()
    page.keyboard.press("Escape")
    page.locator("[data-rs-roll]").click()
    page.locator(".rs-pick-q").press("Escape")
    assert page.locator("#rs-pick").is_hidden() and player.errors == []


def test_a_save_and_a_check_on_the_card(people, server, browser_db):
    """Checks and saves (Nov 9): a save on Battle's tiles and a skill from Table rolls' Roll open the card, one step,
    with the roll's own name on its result and Done (not "missed")."""
    was = _pieces(browser_db, server, ["sync", "labs", "roll_card"])
    try:
        player = people("player")
        page = _battle_with(player, server, True)
        page.locator('[data-roll="save"][data-label^="Dex"]:visible >> nth=0').click()
        card = page.locator(".roll-card")
        card.locator("[data-roll-hit]").wait_for()
        assert card.locator(".rcard-head b").inner_text() == "Dex save" and card.locator(".rcard-rail li").count() == 1
        card.locator("[data-roll-hit]").click()
        card.locator("[data-done]").wait_for(timeout=20000)
        assert "dex save" in card.locator(".rcard-what").inner_text().lower() and card.locator("[data-missed]").count() == 0
        _sees(page, "Dex save")
        card.locator("[data-done]").click()
        if page.evaluate("document.body.classList.contains('rolls-closed')"):
            page.locator(".rs-edge").click()
        page.locator("[data-rs-roll]").click()
        page.locator("#rs-pick .rc").first.wait_for()
        page.locator(".rs-pick-q").fill("stealth")
        page.locator(".rs-pick-q").press("Enter")
        page.locator(".roll-card [data-roll-hit]").wait_for()
        assert "Stealth check" in page.locator(".roll-card .rcard-head").inner_text()
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)
