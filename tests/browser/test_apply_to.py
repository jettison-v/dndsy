"""Apply to in Table rolls: who a healing or damage roll can go to, and the hit points window it opens."""

from sqlalchemy import create_engine, text

from tests.browser.test_roll_card import _pieces
from tests.browser.test_table import battle

SERVER_ENV = {"DDB_BRIDGE": "1"}  # (Apply to lists the characters the bridge reaches: on askdnd.ai, not by default)


def test_a_name_in_apply_tos_list_opens_the_hit_points_window(people, server, browser_db):
    """Brett, Nov 13: healing that can go to anyone lists the table under Apply to…, and picking a name there did
    nothing (the page's click handler ignored clicks inside any <details>, the list included). The DM picks a name;
    the hit points window opens for that character."""
    was = _pieces(browser_db, server, ["sync"])
    engine = create_engine(browser_db[0])
    with engine.begin() as conn:
        conn.execute(text("INSERT INTO table_rolls (campaign_id, character_id, label, kind, formula, dice, modifier, total, mode, visibility)"
                          " VALUES (:c, :ch, 'Cure Wounds', 'heal', '2d8+4', CAST('[8, 6]' AS jsonb), 4, 18, 'normal', 'table')"),
                     {"c": server["campaign"], "ch": server["cole"]})
    engine.dispose()
    try:
        dm = people("dm")
        page = battle(dm, server)
        if page.evaluate("document.body.classList.contains('rolls-closed')"):
            page.locator(".rs-edge").click()
        try:
            page.locator("details.roll-apply-to summary").first.click()
        except Exception as e:  # (what Table rolls held, said when it fails: on GitHub's machines only, Nov 13)
            held = page.evaluate("""() => ({ body: document.body.className,
              lists: document.querySelectorAll('details.roll-apply-to').length,
              shown: [...document.querySelectorAll('details.roll-apply-to')].map(d => d.checkVisibility()),
              single: document.querySelectorAll('.roll-apply > button[data-modal-url]').length,
              entries: [...document.querySelectorAll('#roll-log > li')].slice(0, 4).map(li => ({ kind: li.dataset.kind, cls: li.className, apply: !!li.querySelector('.roll-apply') })) })""")
            raise AssertionError(f"Apply to… wasn't there to press: {held}") from e
        page.locator(".roll-apply-list button").first.click()
        page.locator("#peek.open").wait_for(timeout=10000)
        assert "hit points" in page.locator("#peek.open").inner_text()
        assert dm.errors == []
    finally:
        _pieces(browser_db, server, was)
