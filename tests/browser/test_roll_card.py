"""The roll card in real pages (Brett chose the Roll Card Prototype, Nov 9; every roll since Nov 10): Cole's Unarmed
Strike asks first (Damage, Grapple or Shove), rolls to hit with an added die, then its damage, each into Table rolls;
Grapple sends its DC; the DM sees the attack live. tests/browser/test_every_roll.py plays every roll button."""

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


def _battle_with(person, server, on: bool = True):
    """Battle (the card has no switch since Nov 10: `on` is kept for the tests that still pass it)."""
    return battle(person, server)


def _sees(page, words: str, seconds: int = 20):
    """The newest rolls this person may see, from Table rolls' own address (a closed sidebar loads none), include these words."""
    for _ in range(seconds * 2):
        if words in page.evaluate("fetch('/rolls?since=-1').then(r => r.text())"):
            return
        time.sleep(0.5)
    raise AssertionError(f"{words} never reached Table rolls")


def test_an_attack_on_the_roll_card_and_the_dm_sees_it(people, server, browser_db):
    was = _pieces(browser_db, server, ["sync"])
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


def test_flat_damage_of_0_is_said_before_the_roll(people, server, browser_db):
    """Feedback (Nov 9): the roll window warns when an attack can only do 0 damage (1 + Strength −1); the card does too,
    and its header keeps the 0."""
    was = _pieces(browser_db, server, ["sync"])
    try:
        player = people("player")
        page = _battle_with(player, server, True)
        page.locator(UNARMED).evaluate("""b => { const p = JSON.parse(b.dataset.plan);
            p.damage = [{dice: '', flat: 0, type: 'bludgeoning', from: 'Unarmed Strike'}]; p.flat = 0; p.dmg = '0 bludgeoning'; b.dataset.plan = JSON.stringify(p); }""")
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
        card.locator(".rcard-result:not(.rolling)").wait_for()
        assert card.locator("[data-riders]").count() or "Natural 20" in card.inner_text(), card.inner_text()  # (a 20 always hits: nothing for a miss)
        assert "Natural 20" in card.inner_text() or "On a miss" in card.inner_text() and "Graze" in card.locator("[data-riders]").inner_text()
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_hidden_the_card_says_the_attack_ends_it_and_you_can_untick_it(people, server, browser_db):
    """Feedback (Nov 9): the card ended Hidden without a word, where the roll window offers "This attack ends Hidden"
    ticked (app/hiding.py; the DM may rule otherwise). Unticked, nothing ends."""
    was = _pieces(browser_db, server, ["sync"])
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
    was = _pieces(browser_db, server, ["sync"])
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
    was = _pieces(browser_db, server, ["sync"])
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


def test_the_roll_window_finds_a_check_by_typing_and_rolls_any_dice(people, server):
    """Table rolls' Roll (Brett chose A, Nov 10, docs/mockups/roll-kinds/, his note 58): a window of the character's
    rolls by ability, as the sheet groups them, and Any dice; typing narrows it, Enter opens the first's roll window and
    the window closes behind it, with the focus on the roll so Enter rolls it; Escape closes it; Any dice rolls there; and
    Your dice is its second tab (Brett, Nov 10), whose dice load only once the tab is shown."""
    player = people("player")
    page = battle(player, server)
    if page.evaluate("document.body.classList.contains('rolls-closed')"):
        page.locator(".rs-edge").click()

    def open_roll():
        page.locator("[data-rs-roll]").click()
        page.locator("#peek.open .roll-board .rb-q").wait_for()  # (the new window, not the last one's hidden copy)
        return page.locator("#peek.open .roll-board .rb-q")

    q = open_roll()
    assert page.locator("#peek.open .rb-ability").count() == 6 and page.locator("#peek.open .dp-die").count() >= 6
    q.fill("ste")
    shown = page.locator("#peek.open .roll-board .rc:not([hidden])")
    assert shown.count() == 1 and "Stealth" in shown.first.inner_text()
    q.fill("dex")
    assert page.locator("#peek.open .roll-board .rc:not([hidden])").count() >= 3  # (its skills, the save and the check)
    q.fill("stealth")
    q.press("Enter")
    page.locator(".roll-card").wait_for()
    assert "Stealth check" in page.locator(".roll-card").inner_text()
    page.locator("#peek.open").wait_for(state="detached")
    assert page.evaluate("!!document.activeElement.closest('.roll-win')")  # (Enter now rolls it)
    page.keyboard.press("Escape")

    open_roll().press("Escape")
    page.locator("#peek.open").wait_for(state="detached")

    open_roll()
    page.locator('#peek.open .dp-die:has-text("d6")').first.click()
    page.locator("#peek.open [data-manual-roll]").click()
    page.locator(".roll-card").wait_for()
    assert "1d6" in page.locator(".roll-card").inner_text()
    page.locator("#peek.open").wait_for(state="detached")
    page.keyboard.press("Escape")

    open_roll()
    assert page.locator("[data-dice-preview] canvas").count() == 0
    page.get_by_role("tab", name="Your dice").click()
    page.locator("#peek.open .dice-picker.in-roll [name=material]").first.wait_for()
    assert player.errors == []


def test_a_save_and_a_check_on_the_card(people, server, browser_db):
    """Checks and saves (Nov 9): a save on Battle's tiles and a skill from Table rolls' Roll open the card, one step,
    with the roll's own name on its result and Done (not "missed")."""
    was = _pieces(browser_db, server, ["sync"])
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
        page.locator("#peek.open .roll-board .rb-q").wait_for()
        page.locator("#peek.open .roll-board .rb-q").fill("stealth")
        page.locator("#peek.open .roll-board .rb-q").press("Enter")
        page.locator(".roll-card [data-roll-hit]").wait_for()
        assert "Stealth check" in page.locator(".roll-card .rcard-head").inner_text()
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_a_spell_from_the_spell_book_opens_the_card(people, server, browser_db):
    """Every roll button goes through one choice (app.js openRoll): a spell in the Spell Book has no plan of its own, so
    the card works one out from its recipe and the button's note (Cole's Moonbeam: a Con save, half on a success)."""
    was = _pieces(browser_db, server, ["sync"])
    try:
        player = people("player")
        page = _battle_with(player, server, True)
        page.locator(".spellbook-btn").first.click()
        spell = page.locator('[data-roll="damage"][data-label="Moonbeam"]:visible >> nth=0')
        spell.wait_for()
        spell.click()
        card = page.locator(".roll-card")
        card.locator("[data-roll-save]").wait_for()
        assert "Con save, DC" in card.locator(".rcard-sub").inner_text() and "half damage on a success" in card.inner_text()
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_several_rays_roll_a_to_hit_each(people, server, browser_db):
    """Scorching Ray, Eldritch Blast (Nov 9): one to-hit per ray on the card, then damage for each that isn't a 1.
    Cole's Starry Wisp is made a two-ray spell in the page."""
    was = _pieces(browser_db, server, ["sync"])
    try:
        player = people("player")
        page = _battle_with(player, server, True)
        wisp = page.locator('[data-plan][data-label="Starry Wisp"]:visible >> nth=0')
        if not wisp.count():
            page.locator('[data-panel-url*="/all/action"]').first.click()
            wisp = page.locator('.peek [data-plan][data-label="Starry Wisp"] >> nth=0')
        wisp.evaluate("""b => { const p = JSON.parse(b.dataset.plan), e = p.rolls.effects[0];
            e.each = 'ray'; Object.values(e.at).forEach(a => { if (a) a.count = 2; }); b.dataset.plan = JSON.stringify(p); }""")
        wisp.click()
        card = page.locator(".roll-card")
        card.locator("[data-roll-hit]").click()
        card.locator(".rcard-result:not(.rolling)").wait_for(timeout=20000)
        assert " · " in card.locator(".rcard-big").inner_text() and "one per ray" in card.inner_text().lower()
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_the_card_lets_the_dice_show_through_while_they_are_thrown(people, server, browser_db):
    """Feedback 59 (Nov 9): a die that landed behind the card was hidden; while dice are on screen the card is see-through."""
    was = _pieces(browser_db, server, ["sync"])
    try:
        player = people("player")
        player.context.add_init_script("localStorage.setItem('askdnd.rollsAnim', 'on')")  # (after Person's own, which turns dice off)
        page = _battle_with(player, server, True)
        page.locator(UNARMED).click()
        page.locator('.roll-card [data-choice="damage"]').click()
        page.mouse.move(2, 2)  # (not pointing at the card)
        page.locator(".roll-card [data-roll-hit]").click()
        page.mouse.move(2, 2)
        page.wait_for_function("document.querySelector('.dice-throw.on')", timeout=10000)
        page.wait_for_timeout(300)
        assert float(page.evaluate("getComputedStyle(document.querySelector('.roll-win')).opacity")) < 0.6
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)


def test_healing_and_any_dice_are_one_step_on_the_card(people, server, browser_db):
    """Finishing the card, step 1 (Brett, Nov 10): healing (a Hit Point Die, a spell), damage with no attack or save,
    and any dice roll on the card in one step, Roll, with what to add, who sees it, and where it goes next."""
    was = _pieces(browser_db, server, ["sync"])
    try:
        player = people("player")
        page = _battle_with(player, server, True)
        if page.evaluate("document.body.classList.contains('rolls-closed')"):
            page.locator(".rs-edge").click()
        page.locator("[data-rs-roll]").click()
        page.locator('#peek.open .rc[data-label="Hit Point Die"]').first.click()
        card = page.locator(".roll-card")
        card.locator("[data-roll-single]").wait_for()
        assert card.locator(".rcard-rail li").count() == 1 and "Roll healing" in card.locator("[data-roll-single]").inner_text()
        card.locator("[data-roll-single]").click()
        card.locator("[data-done]").wait_for(timeout=20000)
        assert card.locator(".rcard-what").inner_text().lower() == "healing" and "Apply to" in card.inner_text()
        _sees(page, "Hit Point Die")
        card.locator("[data-done]").click()

        page.locator("[data-rs-roll]").click()
        page.locator('#peek.open .dp-die:has-text("d6")').first.click()
        page.locator("#peek.open [data-manual-roll]").click()
        card.locator("[data-card-for]").fill("Falling into the pit")
        card.locator("[data-roll-single]").click()
        card.locator("[data-done]").wait_for(timeout=20000)
        assert "falling into the pit" in card.inner_text().lower()
        _sees(page, "Falling into the pit")
        assert player.errors == []
    finally:
        _pieces(browser_db, server, was)
