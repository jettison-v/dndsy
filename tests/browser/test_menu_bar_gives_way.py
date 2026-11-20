"""The menu bar gives way in one order as it runs short, and nothing in it wraps or spills (Brett, Nov 13: "nothing wraps
onto two lines, and things give way in one order"; Nov 20, Menu Bar Doors: "Remember not to affect the wrapping
strategy"). The order is the bar's own width (app.css, the collapse order): Search's bar first, always (it takes only the
free room); below 1360px the word askdnd; 1200px your character's name; 1100px the Live pill's short words; 1000px the
campaign's name with "…"; below 1000px Search's magnifier alone. Asked of the admin (every door), the DM and a player."""

import pytest

WIDTHS = range(1900, 900, -20)  # (the window's; the bar's own width is what counts, narrower when Table rolls is open beside it)
STEPS = (1360, 1200, 1100, 1000)

READ = """() => {
  const bar = document.querySelector('.topbar-inner'), r = bar.getBoundingClientRect();
  const shown = sel => { const e = document.querySelector('.topbar ' + sel); return !!e && e.checkVisibility(); };
  const kids = [...bar.querySelectorAll(':scope > *, .nav > *, .table-nav > *, .bar-end > *')].filter(e => e.checkVisibility());
  const tall = kids.filter(e => e.getBoundingClientRect().height > 42).map(e => e.className || e.tagName);  // (one line is the bar's 36px)
  const out = kids.filter(e => { const b = e.getBoundingClientRect(); return b.right > r.right + 0.5 || b.left < r.left - 0.5; }).map(e => e.className || e.tagName);
  return { bw: document.querySelector('.topbar').clientWidth, hasChar: !!document.querySelector('.topbar a.char-btn'), word: shown('.brand-word'), charName: shown('a.char-btn .char-name'), longSearch: shown('.sp-long'), key: shown('.search-btn kbd'),
           scroll: bar.scrollWidth - bar.clientWidth, tall, out };
}"""


@pytest.mark.parametrize("who", ["admin", "dm", "player"])
def test_the_bar_gives_way_in_its_order_and_never_wraps(people, server, who):
    person = people(who)
    page = person.open("/c/main/campaign")
    seen = set()
    for w in WIDTHS:
        page.set_viewport_size({"width": w, "height": 800})
        page.wait_for_timeout(30)
        got = page.evaluate(READ)
        bw = got["bw"]
        if bw <= 900:  # (the phone layout: the bottom bar takes over)
            continue
        seen |= {(step, bw > step) for step in STEPS}
        where = f"{who} with the bar {bw}px wide"
        assert got["scroll"] <= 0 and not got["out"], f"{where}: something spills out of the bar: {got['out']}"
        assert not got["tall"], f"{where}: something wraps onto two lines: {got['tall']}"
        assert got["word"] == (bw > 1360), f"{where}: the word askdnd gives way below 1360px, first"
        if got["hasChar"]:  # (the DM, and an admin who plays no one here, have no character of their own in the bar)
            assert got["charName"] == (bw > 1200), f"{where}: your character's name gives way at 1200px"
        assert got["key"] == (bw > 999), f"{where}: below 1000px Search is its magnifier alone"
    assert seen == {(step, on) for step in STEPS for on in (True, False)}, f"not every step was seen both ways: {sorted(seen)}"


def test_the_way_to_the_other_half_reads_whole(people, server):
    """Backstage (Nov 20): each half's way to the other ("This campaign" on Global's pages, "Global" on the campaign's)
    is never cut short with "…", on a laptop or a phone (it was, for a day: its room was the old "Manage"'s)."""
    admin = people("admin")
    for width in (1280, 375):
        admin.page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        for path in ("/manage/usage", "/c/main/manage/inbox"):
            admin.open(path)
            cut = admin.page.locator(".manage-cross").evaluate("e => e.scrollWidth - e.clientWidth")
            assert cut <= 0, f"{path} at {width}px: the way to the other half is cut short by {cut}px"
