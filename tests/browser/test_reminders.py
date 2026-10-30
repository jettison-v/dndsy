"""A condition's reminder in real pages (app.js "its reminders"; Brett, 2026-10-29): when its time runs out in the
fight heard from D&D Beyond's VTT, the character's player gets a corner card with End it and Keep, and the DM one to
know. Nothing ends by itself."""

import json
from datetime import UTC, datetime

from sqlalchemy import create_engine, text


def test_a_reminder_comes_as_a_card_and_keep_lets_it_last(people, server, browser_db):
    engine = create_engine(browser_db[0])
    now = datetime.now(UTC)
    fight = {"round": 2, "turn": 2, "seq": 1,
             "order": [{"key": "t-cole", "name": "Cole", "kind": "character", "character": server["cole"], "initiative": 18, "hidden": False, "active": False},
                       {"key": "t-e1", "name": "Enemy 1", "kind": "monster", "character": None, "initiative": 15, "hidden": False, "active": True}],
             "reminders": [{"id": 1, "at": now.isoformat(), "character": server["cole"], "who": "Cole", "kind": "ends",
                            "name": "Prone", "text": "Prone ends now"}]}
    conditions = [{"name": "Prone", "source": "", "lasts": {"kind": "startnext", "of": {"key": "t-e1", "name": "Enemy 1"}}, "due": True}]
    player, dm = people("player", "dm")  # (signed in first: a reminder shows once per browser, on whatever page it meets)
    with engine.begin() as conn:
        conn.execute(text("UPDATE campaigns SET fight = CAST(:f AS jsonb), fight_at = :t WHERE id = :c"),
                     {"f": json.dumps(fight), "t": now, "c": server["campaign"]})
        conn.execute(text("UPDATE characters SET conditions = CAST(:c AS jsonb) WHERE id = :i"), {"c": json.dumps(conditions), "i": server["cole"]})
    try:
        page = player.open(f"/characters/{server['cole']}/battle")
        card = page.locator("#cards .card", has_text="Prone ends now")
        card.wait_for()
        assert card.locator(".card-act", has_text="End it").count() == 1
        dm_card = dm.open(f"/characters/{server['cole']}/battle").locator("#cards .card", has_text="Cole")
        dm_card.wait_for()
        assert dm_card.locator(".card-act").count() == 0  # the DM's is to know
        card.locator(".card-act", has_text="Keep").click()
        page.wait_for_function("!document.querySelector('.cond-pill .cond-time.soon')")  # no longer due: it lasts
        page.reload()
        assert page.locator("#cards .card", has_text="Prone ends now").count() == 0  # shown once in this browser
        assert player.errors == [] and dm.errors == []
    finally:
        with engine.begin() as conn:
            conn.execute(text("UPDATE campaigns SET fight = NULL, fight_at = NULL WHERE id = :c"), {"c": server["campaign"]})
            conn.execute(text("UPDATE characters SET conditions = NULL WHERE id = :i"), {"i": server["cole"]})
        engine.dispose()
