"""The action widgets (roadmap 8, docs/plans/2026-11-05-action-widgets.md): what an action costs, spent where it's
used, with Undo. First, a row's own cost spent as its roll is made (Brett, Nov 13: Flurry of Blows showed its Focus
Point and didn't spend it)."""

from sqlalchemy import create_engine, text

from tests.browser.test_roll_card import _pieces
from tests.browser.test_table import battle

SERVER_ENV = {"DDB_BRIDGE": "1"}  # (askdnd spends on D&D Beyond only where the bridge may run: on askdnd.ai, not by default)



def test_a_rows_own_cost_is_spent_as_it_is_rolled_with_undo(people, server, browser_db):
    """The action widgets (roadmap 8; Brett, Nov 13: Flurry of Blows showed its Focus Point and didn't spend it): the
    card says what the roll spends, a pill on while there's enough left; once the roll is made it goes to D&D Beyond as
    Use one does (app/resources.py), and the corner card's Undo gives it back. Unpressed, nothing is spent."""
    was = _pieces(browser_db, server, ["sync"])
    engine = create_engine(browser_db[0])

    def heard():  # (Cole's own sheet open in Chrome: askdnd can reach it)
        with engine.begin() as conn:
            conn.execute(text("UPDATE characters SET sheet_heard_at = now(), sheet_seen_at = now() WHERE id = :c"), {"c": server["cole"]})

    def spent() -> list:
        with engine.begin() as conn:
            return [r[0] for r in conn.execute(text("SELECT data FROM bridge_intents WHERE character_id = :c AND kind = 'use' ORDER BY id"), {"c": server["cole"]})]

    def flurry(page):
        page.locator("[data-search-open]").click()
        page.fill("#search-q", "flurry of blows")
        page.locator(".search-res.on", has_text="Flurry of Blows").wait_for()
        page.keyboard.press("Enter")
        card = page.locator(".roll-card")
        card.locator("[data-pays]").first.wait_for()
        return card

    def to_hit(card):  # (Damage first where the card asks which Unarmed Strike)
        card.locator('[data-choice="damage"], [data-roll-hit]').first.wait_for()
        if card.locator('[data-choice="damage"]').count():
            card.locator('[data-choice="damage"]').click()
        card.locator("[data-roll-hit]").click()

    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM bridge_intents WHERE character_id = :c"), {"c": server["cole"]})
        player = people("player")
        for _ in range(20):  # (the server keeps a campaign's switches for a few seconds)
            heard()
            page = battle(player, server)
            if page.locator("main[data-spends='play']").count():
                break
            page.wait_for_timeout(500)
        card = flurry(page)
        pay = card.locator("[data-pay]").first
        assert pay.get_attribute("aria-pressed") == "true" and "1 Focus Point" in pay.inner_text()
        to_hit(card)
        page.locator("#cards > .card", has_text="Focus Points").wait_for()
        focus = [d for d in spent() if d.get("delta") == 1]
        assert len(focus) == 1 and focus[0]["field"].startswith("uses:")
        page.locator("#cards > .card", has_text="Focus Points").get_by_role("button", name="Undo").click()
        page.locator("#cards > .card", has_text="Focus Points: 2").wait_for()
        assert [d["delta"] for d in spent()][-2:] == [1, -1]
        if card.count():  # (pressing Undo, outside the card, may have closed it)
            card.locator("[data-done], [data-missed]").first.click()

        heard()  # (unpressed: the roll is made and nothing is spent)
        n = len(spent())
        card = flurry(page)
        card.locator("[data-pay]").first.click()
        assert card.locator("[data-pay]").first.get_attribute("aria-pressed") == "false"
        to_hit(card)
        card.locator("[data-roll-dmg], [data-missed]").first.wait_for()
        page.wait_for_timeout(500)
        assert len(spent()) == n and player.errors == []
    finally:
        _pieces(browser_db, server, was)
        engine.dispose()
