"""Pictures of every main page, for a before-and-after (foundation F7, docs/plans/2026-11-13-engineering-practices.md).

Not part of the suite: it runs only when scripts/visual_compare.py sets VISUAL_OUT (tests/browser/conftest.py leaves it
out otherwise), once on main and once on the branch, with the same seeded data, widths and clock; the script compares
the two. The pictures show the party's saved sheets, so they stay on this computer (private/visual/), never on GitHub.
"""

import os
import re
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from app.config import TABLE_TIME
from tests.browser.test_layout import PAGES
from tests.browser.test_roll_card import _pieces

SERVER_ENV = {"DDB_BRIDGE": "1"}  # (as askdnd.ai runs: the bridge's parts of each page drawn too)

OUT = Path(os.environ.get("VISUAL_OUT", "private/visual/out"))
WIDTHS = {"laptop": 1280, "phone": 375}  # (designed for a laptop first; a phone must hold together too)
# Whatever differs between two runs by itself: times and "ago", the live pill, Table rolls' newest moments
MASK = "time, .live-ago, .sb-time, .cond-time, .readied-when, .rider-when, .hist-head .note, [data-at], [data-clock]"  # (Table rolls' list itself is compared)
# (a mask hides the words but keeps their width, which moves with the time: each gets the same words first)
SAME = f"document.querySelectorAll('{MASK}').forEach(e => {{ e.textContent = '00:00'; }})"
STILL = "*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }"


def name(who: str, path: str, width: str) -> str:
    return f"{who}--{re.sub(r'[^a-z0-9]+', '-', path.lower()).strip('-') or 'home'}--{width}.png"


@pytest.mark.parametrize("who", list(PAGES))
def test_pictures_of_every_main_page(people, server, browser_db, who):
    OUT.mkdir(parents=True, exist_ok=True)
    person = people(who)
    person.allow("/map?v=")  # (no map picture in the test data)
    person.allow(" 404 ")  # (a page the branch adds isn't on the base yet: no picture of it there, the report says "new page")
    page = person.page
    page.clock.set_fixed_time(datetime(2026, 11, 13, 19, 30, tzinfo=TABLE_TIME))  # (one moment for both runs: the server's own times are masked)
    for path in PAGES[who]:
        for width_name, width in WIDTHS.items():
            page.set_viewport_size({"width": width, "height": 800})
            answer = page.goto(server["base"] + path.format(**server))
            if answer is not None and answer.status == 404:
                break  # (not on this side: a new page)
            page.wait_for_load_state("networkidle")
            page.add_style_tag(content=STILL)
            page.evaluate(SAME)
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(OUT / name(who, path, width_name)), full_page=True,
                            mask=[page.locator(MASK)], mask_color="#888")
    if who == "player":
        band(person, server, browser_db)


def band(person, server, browser_db):
    """A state a page only shows sometimes, drawn on purpose (Nov 13: the connection band and Table rolls broke each
    other, and no picture had the band): Cole's sheet heard tonight, then closed, with Sync on, as the band shows it."""
    page = person.page
    engine = create_engine(browser_db[0])
    with engine.connect() as conn:
        ddb = conn.execute(text("SELECT ddb_id FROM characters WHERE id = :c"), {"c": server["cole"]}).scalar()
    engine.dispose()
    was = _pieces(browser_db, server, ["sync"])
    try:
        for step in ("heard", "closed"):  # (refused, the picture would quietly lose the band: say so instead)
            answer = page.request.post(f"{server['base']}/bridge/{step}/{ddb}")
            assert answer.ok, f"/bridge/{step}: {answer.status}"
        for width_name, width in WIDTHS.items():
            page.set_viewport_size({"width": width, "height": 800})
            person.open(f"/characters/{server['cole']}/battle")
            page.wait_for_load_state("networkidle")
            page.add_style_tag(content=STILL)
            page.evaluate(SAME)
            page.screenshot(path=str(OUT / name("player", "battle-with-the-connection-band", width_name)),
                            mask=[page.locator(MASK)], mask_color="#888")
    finally:
        _pieces(browser_db, server, was)
