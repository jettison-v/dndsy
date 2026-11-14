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

from app.config import TABLE_TIME
from tests.browser.test_layout import PAGES

OUT = Path(os.environ.get("VISUAL_OUT", "private/visual/out"))
WIDTHS = {"laptop": 1280, "phone": 375}  # (designed for a laptop first; a phone must hold together too)
# Whatever differs between two runs by itself: times and "ago", the live pill, Table rolls' newest moments
MASK = "time, .live-ago, .sb-time, .cond-time, .readied-when, .rider-when, #roll-log, [data-at], [data-clock]"
STILL = "*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }"


def name(who: str, path: str, width: str) -> str:
    return f"{who}--{re.sub(r'[^a-z0-9]+', '-', path.lower()).strip('-') or 'home'}--{width}.png"


@pytest.mark.parametrize("who", list(PAGES))
def test_pictures_of_every_main_page(people, server, who):
    OUT.mkdir(parents=True, exist_ok=True)
    person = people(who)
    person.allow("/map?v=")  # (no map picture in the test data)
    page = person.page
    page.clock.set_fixed_time(datetime(2026, 11, 13, 19, 30, tzinfo=TABLE_TIME))  # (one moment for both runs: the server's own times are masked)
    for path in PAGES[who]:
        for width_name, width in WIDTHS.items():
            page.set_viewport_size({"width": width, "height": 800})
            person.open(path.format(**server))
            page.wait_for_load_state("networkidle")
            page.add_style_tag(content=STILL)
            page.evaluate("document.fonts.ready")
            page.screenshot(path=str(OUT / name(who, path, width_name)), full_page=True,
                            mask=[page.locator(MASK)], mask_color="#888")
