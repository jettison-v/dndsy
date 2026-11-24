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
        dm.open("/c/main/campaign")  # (Table rolls lists the campaign last opened: another file on this worker may have left the DM in its own; issue 112)
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


def test_healing_applied_moves_its_roll_up_but_throws_no_dice_and_the_hit_points_beside_names_stay_current(people, server, browser_db):
    """Brett's test, Nov 16: applying a heal made every other screen throw its dice again (the applied row moved the
    roll's sequence, read as a new roll), and the Hit Points beside each name in Apply to… stayed as they were when the
    roll was drawn. A new roll still arrives as one (the dice, or a corner card where dice can't play); an applied one
    doesn't; and a character's change brings the Hit Points beside their name up to date."""
    was = _pieces(browser_db, server, ["sync"])
    engine = create_engine(browser_db[0])

    def roll(label, kind="heal", parent=None):
        with engine.begin() as conn:
            return conn.execute(text(
                "INSERT INTO table_rolls (campaign_id, character_id, label, kind, formula, dice, modifier, total, mode, visibility, parent_id)"
                " VALUES (:c, :ch, :l, :k, '2d8+4', CAST('[8, 6]' AS jsonb), 4, 18, 'normal', 'table', :p) RETURNING id"),
                {"c": server["campaign"], "ch": server["cole"], "l": label, "k": kind, "p": parent}).scalar()

    first = roll("Cure Wounds")
    try:
        dm = people("dm")
        dm.open("/c/main/campaign")  # (Table rolls lists the campaign last opened: issue 112)
        page = battle(dm, server)
        if page.evaluate("document.body.classList.contains('rolls-closed')"):
            page.locator(".rs-edge").click()
        page.locator(f'#roll-log .roll-item[data-id="{first}"]').wait_for()
        page.evaluate("""() => { window.__arrived = 0; const t = window.askdndThrowing.throwing;
          window.askdndThrowing.throwing = id => { window.__arrived++; t(id); };
          new MutationObserver(ms => ms.forEach(m => m.addedNodes.forEach(n => { if (n.classList && n.classList.contains('card')) window.__arrived++; })))
            .observe(document.getElementById('cards') || document.body, { childList: true }); }""")
        load = "htmx.trigger(document.getElementById('roll-log'), 'rolls:load')"
        # Applied to someone: the row comes again, moved up, and nothing is thrown
        roll("Cure Wounds", kind="applied", parent=first)
        page.evaluate(load)
        page.wait_for_function(f"+document.querySelector('#roll-log .roll-item[data-id=\"{first}\"]').dataset.seq > {first}")
        page.wait_for_timeout(300)
        assert page.evaluate("window.__arrived") == 0
        # A new roll still arrives as one
        roll("Healing Word")
        page.evaluate(load)
        page.wait_for_function("window.__arrived > 0")
        # The Hit Points beside a name follow the character, not the roll
        pill = page.locator(f'[data-hp-of="{server["cole"]}"]').first
        before = pill.get_attribute("data-hp")
        with engine.begin() as conn:
            conn.execute(text("UPDATE character_snapshots SET summary = jsonb_set(summary, '{hit_points,current}', '1')"
                              " WHERE character_id = :ch"), {"ch": server["cole"]})
        page.evaluate(f"document.dispatchEvent(new CustomEvent('askdnd:live', {{ detail: {{ type: 'character', id: {server['cole']} }} }}))")
        page.wait_for_function(f"/^1\\//.test(document.querySelector('[data-hp-of=\"{server['cole']}\"]').dataset.hp)")
        assert before != pill.get_attribute("data-hp")
        assert dm.errors == []
    finally:
        engine.dispose()
        _pieces(browser_db, server, was)
