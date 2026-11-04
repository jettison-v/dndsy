"""The DM changes the fight's order in real pages (Initiative from askdnd, app/initiative.py; Brett, Nov 4,
docs/mockups/initiative/ board 5): ↑ on Party's Rows moves a fighter, the corner card says the number it got with Undo,
and a player's open page shows the new order at once (realtime "game"); players get no handles."""

import json
from datetime import UTC, datetime

from sqlalchemy import create_engine, text


def test_the_dm_moves_a_fighter_and_everyone_sees_the_new_order(people, server, browser_db):
    engine = create_engine(browser_db[0])
    row = lambda key, name, ini, kind="monster", character=None, active=False: {  # noqa: E731
        "key": key, "name": name, "kind": kind, "character": character, "initiative": ini, "hidden": False, "active": active,
        "image": None, "monster": None, "group": "Enemy" if kind == "monster" else "Party Member", "gkey": key}
    fight = {"round": 1, "turn": 1, "seq": 0, "id": "f1", "reminders": [],
             "order": [row("t-cole", "Cole", 18, "character", server["cole"], active=True), row("t-e1", "Enemy 1", 15), row("t-e2", "Enemy 2", 10)]}
    player, dm = people("player", "dm")
    with engine.begin() as conn:
        was = conn.execute(text("SELECT vtt_pieces FROM campaigns WHERE id = :c"), {"c": server["campaign"]}).scalar()
        conn.execute(text("""UPDATE campaigns SET fight = CAST(:f AS jsonb), fight_at = :t, vtt_pieces = '["sync", "labs", "initiative"]' WHERE id = :c"""),
                     {"f": json.dumps(fight), "t": datetime.now(UTC), "c": server["campaign"]})
    try:
        seen = player.open("/party")
        assert seen.locator("[data-ft-move]").count() == 0  # (a player sees the order, without handles)
        page = dm.open("/party")
        page.locator('tr[data-ft-key="t-e2"] [data-ft-move="up"]').click()
        card = page.locator("#cards .card", has_text="Enemy 2: 10 → 16")
        card.wait_for()
        assert card.locator(".card-act", has_text="Undo").count() == 1
        names = "[...document.querySelectorAll('.fight-band .fb-name')].map(x => x.textContent.trim()).join(',')"
        seen.wait_for_function(f"{names} === 'Cole,Enemy 2,Enemy 1'")  # the player's page, live
        page.wait_for_function("document.querySelector('tr[data-ft-key=\"t-e2\"] .ft-pending')")  # on its way to D&D Beyond
        card.locator(".card-act", has_text="Undo").click()
        seen.wait_for_function(f"{names} === 'Cole,Enemy 1,Enemy 2'")
        assert player.errors == [] and dm.errors == []
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE campaigns SET fight = NULL, fight_at = NULL, vtt_pieces = CAST(:v AS jsonb) WHERE id = :c"),
                         {"v": json.dumps(was), "c": server["campaign"]})
        engine.dispose()
