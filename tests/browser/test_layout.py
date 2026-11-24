"""Every page holds together at phone, tablet, in-between and wide widths (docs/DESIGN.md › Narrow screens): nothing
scrolls sideways, spills out of its box, breaks a one-line control onto two lines, or overlaps in the menu bar
(tests/browser/layout_check.js). With long names on purpose, since real names are what break layouts. Each page's
tabs, the menu bar's menus and Battle's side panel are checked too."""

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from tests.browser.conftest import Person

CHECK = (Path(__file__).parent / "layout_check.js").read_text()

# Brett, Nov 19 (measured: phone work was ~9-10% of active time, and he waits while he watches): every change checks
# admin pages at phone and tablet widths for hard breaks only; their polish (a control that wraps, squeezed words, a
# word broken, a cut hint, tiny words in a chart) is the weekly phone sweep's (scripts/phone_sweep.py). Players' pages
# keep every check at every width: they're used at the table. LAYOUT_LAPTOP=1 runs only the laptop widths (Claude's
# runs while Brett watches; GitHub runs them all).
HARD = {"scrolls sideways", "spills", "overlaps", "zooms", "repeats an id"}
LAPTOP_ONLY = bool(os.environ.get("LAYOUT_LAPTOP"))
WIDTHS = (1000, 1280) if LAPTOP_ONLY else (375, 768, 1000, 1280)
POLISH_FROM = 1000  # (admin pages below it: hard breaks only)
PAGES = {
    "player": ("/c/main/campaign", "/c/main/campaign?tab=sessions", "/c/main/campaign?tab=world", "/characters/{cole}/battle", "/characters/{cole}",
               "/characters/{cole}/plan", "/c/main/campaign?tab=glossary", "/party", "/help", "/your-notes", "/your-notes?tab=askdnd"),
    "admin": tuple(f"/c/main/manage{p}" for p in ("", "/inbox", "/sessions", "/table", "/house-rules", "/history", "/settings", "/places",
                                                  "/dm-guide"))
             + tuple(f"/manage/{p}" for p in ("askdnd", "campaigns", "accounts", "tool-corrections", "usage", "features", "backups", "history",
                                               "design", "dice", "feedback", "roadmap", "work", "work?tab=queue", "work?tab=checks", "work?tab=scheduled", "work?tab=how", "product-areas"))
             + ("/c/main/dm", "/c/main/dm/items/new"),  # (DM Tools: app/homebrew.py)
}


@pytest.fixture(scope="module")
def long_names(browser_db):
    """A campaign and a character with the long names a real table might pick."""
    url, ids = browser_db
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("UPDATE campaigns SET name = 'The Adventure Begins Beneath the Sunless Citadel' WHERE id = :c"), {"c": ids["campaign"]})
        conn.execute(text("UPDATE characters SET name = 'Coleridge Thistlewood' WHERE id = :c"), {"c": ids["cole"]})
    engine.dispose()


@pytest.fixture(scope="module")
def told_session(browser_db):
    """A published session with a full tale, awards and who talked (Session Story, Nov 7): its own page's address."""
    import json

    url, ids = browser_db
    engine = create_engine(url)
    tale = [{"title": f"Chapter of the Very Long Night Number {n}", "kind": k, "at": n * 3000, "text": "The fog closed in. " * 40}
            for n, k in enumerate(("exploring", "story", "fight", "rest"))]
    awards = [{"award": a, "character": "Coleridge Thistlewood", "why": "Kept the boat off the rocks the whole time. " * 3,
               "quote": "If it rings for the dead, it can ring them home." if a == "Line of the Night" else "", "at": 3600}
              for a in ("Most Strategic", "Line of the Night", "DM Shining Moment")]
    with engine.begin() as conn:
        sid = conn.execute(text("INSERT INTO game_sessions (campaign_id, played_on, title, source, talk, created_at, updated_at) "
                                "VALUES (:c, '2026-11-06', 'The Drowned Bell of Saltmere Reach', 'transcript', :talk, now(), now()) RETURNING id"),
                           {"c": ids["campaign"], "talk": json.dumps({"speakers": {"dm": 4000, "player": 2000}, "length": 12000})}).scalar()
        conn.execute(text("INSERT INTO recaps (session_id, version, body, author, status, tale, awards, created_at, updated_at) "
                          "VALUES (:s, 1, 'Fog rolled off the Reach.', 'ai', 'published', :tale, :awards, now(), now())"),
                     {"s": sid, "tale": json.dumps(tale), "awards": json.dumps(awards)})
    engine.dispose()
    return f"/c/main/sessions/{sid}"


def problems(page, where: str, hard_only: bool = False) -> list[str]:
    return [f"{where} · {p['kind']}: {p['where']} ({p['detail']})" for p in page.evaluate(CHECK) if not hard_only or p["kind"] in HARD]


def check(person, server, paths, widths=WIDTHS, hard_below: int = 0) -> list[str]:
    page, found = person.page, []
    for width in widths:
        if page.viewport_size["width"] != width:
            page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        for path in paths:
            path = path.format(cole=server["cole"])
            person.open(path)
            page.wait_for_load_state("load")
            hard = width < hard_below
            found += problems(page, f"{path} at {width}px", hard)
            tabs = page.locator("main [role=tab]:visible")
            for k in range(tabs.count()):
                tabs.nth(k).click()
                found += problems(page, f"{path} › {tabs.nth(k).inner_text().split(chr(10))[0]} at {width}px", hard)
        for opener in page.locator(".topbar [data-menu]:visible").all():  # the menu bar's menus
            opener.click()
            page.wait_for_timeout(300)
            found += problems(page, f"menu {opener.get_attribute('data-menu')} at {width}px", width < hard_below)
            page.keyboard.press("Escape")
            page.mouse.click(2, 400)
    return found


def test_a_players_pages_hold_together_at_every_width(people, server, long_names, told_session):
    player = people("player")
    found = check(player, server, PAGES["player"] + (told_session,))
    player.open(f"/characters/{server['cole']}/battle")  # Battle's side panel (+ Add)
    for width in WIDTHS:
        player.page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        player.page.locator(".head-add:visible").first.click()
        player.page.wait_for_selector(".peek.open")
        player.page.wait_for_timeout(300)
        found += problems(player.page, f"+ Add panel at {width}px")
        player.page.keyboard.press("Escape")
    assert not found, "\n".join(found)
    assert player.errors == []


# Safari's engine as Brett's iPhone and an iPad draw them (Playwright's own settings for each: size, touch, Safari's
# user agent). Every browser on an iPhone is WebKit underneath, so a page that holds together in Chromium can still
# break there (fonts, form controls, flex and grid details).
SAFARI = {375: "iPhone 13 Mini", 768: "iPad Mini"}


@pytest.mark.parametrize("who", ["player", "admin"])
def test_pages_hold_together_in_safari_on_a_phone_and_a_tablet(webkit, playwright, server, long_names, who):
    if LAPTOP_ONLY:
        pytest.skip("laptop widths only (LAYOUT_LAPTOP): GitHub runs Safari")
    found = []
    for width, device in SAFARI.items():
        person = Person(webkit, server, who, **{k: v for k, v in playwright.devices[device].items() if k != "default_browser_type"})
        try:
            found += [f"Safari · {f}" for f in check(person, server, PAGES[who], widths=(width,), hard_below=POLISH_FROM if who == "admin" else 0)]
            assert person.errors == [], person.errors
        finally:
            person.context.close()
    assert not found, "\n".join(found)


def test_a_folded_filter_column_on_a_phone_is_one_row_with_one_clear(people, server):
    """Brett's iPhone test, Nov 16: in the Spell Book's folded Filters, "Filters" sat out of line with Clear, and opened
    it showed a second Clear by the yellow FILTERS heading. One row (Filters, its count, the arrow, Clear), one Clear."""
    player = people("player")
    player.page.set_viewport_size({"width": 375, "height": 812})
    page = player.open(f"/characters/{server['cole']}/battle")
    page.locator(".spellbook-btn").first.click()
    fold = page.locator(".ls-fold").first
    fold.locator("> summary").click()
    fold.locator(".ls-chip").first.click()
    clears = page.evaluate("() => [...document.querySelectorAll('.ls-fold [data-ls-clear]')].filter(e => e.checkVisibility()).length")
    assert clears == 1
    row = page.evaluate("""() => { const s = document.querySelector('.ls-fold > summary');
      const mid = e => { const r = e.getBoundingClientRect(); return r.top + r.height / 2; };
      return Math.abs(mid(s.firstChild.parentElement.querySelector('.ls-above-chev')) - mid(s.querySelector('[data-ls-clear]'))); }""")
    assert row < 4  # (Filters' arrow and Clear on one line, centred together)
    found = problems(page, "The Spell Book's folded filters at 375px")
    assert not found, "\n".join(found)
    assert not player.errors, player.errors


def test_see_alls_count_is_its_links_colour_and_the_bell_sits_on_the_pill(people, server):
    """Feedback 74 and 75 (Brett, Nov 16): "See all actions 17" had its count grey inside the red link (it was the link's
    colour as "(17)"), and in the See all panel each row's bell sat above the middle of the Roll or Cast pill beside it."""
    player = people("player")
    page = player.open(f"/characters/{server['cole']}/battle")
    link = page.locator("div.seeall a:has(.count)").first
    assert link.evaluate("a => getComputedStyle(a.querySelector('.count')).color === getComputedStyle(a).color")
    page.locator('a[data-panel-url*="/all/"]:visible').first.click()
    page.locator(".peek.open .ri").first.wait_for()
    off = page.evaluate("""() => [...document.querySelectorAll('.peek.open .ri')].map(r => {
        const bell = r.querySelector('.ri-pk.end .pick.remind'), hit = r.querySelector('.ri-hit button, .ri-hit .btn');
        if (!bell || !hit || !bell.checkVisibility() || !hit.checkVisibility()) return 0;
        const mid = e => { const b = e.getBoundingClientRect(); return b.top + b.height / 2; };
        return Math.abs(mid(bell) - mid(hit)); })""")
    assert off and max(off) <= 3, off
    assert not player.errors, player.errors


def test_a_long_group_of_resources_fits_a_phone(people, server):
    """Oct 31: Eldritch Cannon's rows on one line made Party 647px wide on a 375px phone."""
    player = people("player")
    player.page.set_viewport_size({"width": 375, "height": 812})
    player.open("/party")
    player.page.evaluate("""() => {
      const card = document.querySelector('.pt-card');
      const res = card.querySelector('.pt-res') || card.appendChild(Object.assign(document.createElement('div'), {className: 'pt-res'}));
      res.insertAdjacentHTML('beforeend', '<span class="pt-group">Eldritch Cannon: ' + '<span>Flamethrower</span>'.repeat(6) + '</span>');
    }""")
    found = problems(player.page, "Party's resources at 375px")
    assert not found, "\n".join(found)


def test_resources_shorten_only_when_they_would_wrap(people, server):
    """Brett, 2026-11-01: whole names while they fit on one line; once they don't, the short ones, and back again.

    The test sets the row's contents itself; a fresh copy of Battle can arrive at any moment (a change announced for
    Cole), so its contents are set again on each one and the row refitted (Nov 13: the cause of this test's flakes)."""
    player = people("player")
    page = player.page
    page.set_viewport_size({"width": 1280, "height": 800})
    player.open(f"/characters/{server['cole']}/battle")
    row = ".battlebar > .res-row:not(.slots)"
    short = f"document.querySelector('{row}').classList.contains('short')"
    page.wait_for_selector(row)
    page.evaluate(f"""() => {{
      window.resExtras = 0;
      const set = () => {{
        const r = document.querySelector('{row}');
        r.querySelectorAll(':scope > .res:not(.res-insp), :scope > .res-group').forEach(e => e.remove());
        const first = r.querySelector('.res-insp');
        for (let i = 0; i < window.resExtras; i++) first.insertAdjacentHTML('beforebegin',
          '<span class="res extra"><span class="rn-full">A resource with a long name</span><span class="rn-short">R</span></span>');
      }};
      window.resSet = set;  // (each step's resize then refits it: what the test checks)
      document.addEventListener('askdnd:swapped', () => {{ set(); document.body.dispatchEvent(new CustomEvent('htmx:afterSettle', {{ detail: {{ target: document.body, elt: document.body }} }})); }});  // (a fresh copy: set again, app.js refits)
      set();
    }}""")
    # (what the row measured, said when a step fails: on GitHub's machines it once never shortened, Nov 13)
    measured = f"""() => {{ const r = document.querySelector('{row}'), i = r && r.querySelector('.res-insp');
      return r && {{ short: r.classList.contains('short'), height: r.offsetHeight, line: i && i.offsetHeight, width: r.offsetWidth,
        extras: r.querySelectorAll('.res.extra').length, items: r.children.length, viewport: innerWidth }}; }}"""

    def until(expression):
        try:
            page.wait_for_function(expression)
        except Exception as e:
            raise AssertionError(f"{expression}: the row measured {page.evaluate(measured)}") from e

    # New contents refit as the page does after any change (htmx:afterSettle, a fresh copy)
    refit = "document.body.dispatchEvent(new CustomEvent('htmx:afterSettle', { detail: { target: document.body, elt: document.body } }))"
    page.evaluate(f"window.resExtras = 0; window.resSet(); {refit}")
    until(f"!({short})")
    page.evaluate(f"window.resExtras = 12; window.resSet(); {refit}")
    until(short)
    # A change of width refits on its own (the row's ResizeObserver): back to whole names once they fit again.
    # (1280 to 1000: below 1241 Table rolls opens over the page, so the row's own width changes; 1270 to 1280 left it
    # the same, 892px, and only passed when something else happened to refit it, Nov 13)
    width = page.evaluate(f"document.querySelector('{row}').offsetWidth")
    page.evaluate("window.resExtras = 0; window.resSet()")
    page.set_viewport_size({"width": 1000, "height": 800})
    page.wait_for_function(f"document.querySelector('{row}').offsetWidth !== {width}")
    until(f"!({short})")


def test_tap_targets_on_a_phone(people, server):
    """A standing rule: DESIGN.md › Principles 8, Works on a phone. A control is at least 36px tall there (Oct 31: Battle's Cast and +7 were 21px)."""
    player = people("player")
    player.page.set_viewport_size({"width": 375, "height": 812})
    small = []
    for path in (f"/characters/{server['cole']}/battle", f"/characters/{server['cole']}", "/party", "/help"):
        player.open(path)
        small += player.page.evaluate("""(path) => [...document.querySelectorAll('.btn, .roll-chip, .roll-hit, .res-go, .rs-toggle, .hp-btn, .live-pill, .help-btn, .chip, .ls-chip, .ws-chip, .spell-chip')]
          .map(e => [path, e.className, e.offsetHeight]).filter(([, , h]) => h && h < 36)""", path)
    assert not small, small


def test_manage_pages_hold_together_at_every_width(people, server, long_names, told_session):
    admin = people("admin")
    review = told_session.replace("/sessions/", "/manage/sessions/")  # (the review wizard: every step's tab is checked)
    found = check(admin, server, PAGES["admin"] + (review,), hard_below=POLISH_FROM)
    # The review's seven steps fit a laptop's column, with Table rolls open beside it and closed (the UI review, Nov 16:
    # "6 Award…" at 1440)
    for width, rolls in ((1000, "closed"), (1280, "open"), (1280, "closed"), (1440, "open"), (1440, "closed"), (1512, "open")):
        admin.page.set_viewport_size({"width": width, "height": 900})
        admin.open(review)
        if admin.page.evaluate("document.body.classList.contains('rolls-closed')") != (rolls == "closed") and admin.page.locator(".rs-edge:visible, .rs-toggle:visible").count():
            admin.page.locator(".rs-edge:visible, .rs-toggle:visible").first.click()
            admin.page.wait_for_timeout(300)
        cut = admin.page.evaluate("(() => { const t = document.querySelector('.review-steps'); return t.scrollWidth - t.clientWidth; })()")
        if cut > 1:
            found.append(f"{review} at {width}px, Table rolls {rolls} · the review's steps run {cut}px past their bar")
    assert not found, "\n".join(found)
    assert admin.errors == []


def test_the_dms_manage_pages_hold_together_at_every_width(people, server, long_names, told_session):
    """The UI review, Nov 16: the DM sees Manage without ⚙ Admin, and the room kept for it broke titles one letter per
    line on a phone and pushed the title's button in on a laptop. The same pages as the DM, who has no way across."""
    dm = people("dm")
    review = told_session.replace("/sessions/", "/manage/sessions/")
    found = check(dm, server, tuple(p for p in PAGES["admin"] if p.startswith("/c/")) + (review,), hard_below=POLISH_FROM)
    for width in (375, 1280):
        dm.page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        dm.open("/c/main/manage/sessions")
        assert dm.page.locator(".manage-cross").count() == 0, "a DM has no way to askdnd admin"
        room = dm.page.evaluate("parseFloat(getComputedStyle(document.querySelector('.title-row')).paddingRight)")
        if room:
            found.append(f"Sessions at {width}px · the title row keeps {room}px for a link that isn't there")
    assert not found, "\n".join(found)
    assert dm.errors == []


def test_the_sheets_lists_line_up_at_every_width(people, server):
    """The UI review, Nov 16: Sheet's Features, Spells and Wild Shape rows ended their marks in different places once
    their columns folded (a row's words decided where it wrapped). One template per list: the layout check's rows."""
    player = people("player")
    found = []
    for width in WIDTHS:
        player.page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        player.open(f"/characters/{server['cole']}")
        for tab in ("t-features", "t-spells", "t-forms", "t-items"):
            button = player.page.locator(f'main [data-tab="{tab}"]:visible')
            if not button.count():
                continue
            button.first.click()
            found += [f"Sheet › {tab} at {width}px · {p['kind']}: {p['where']} ({p['detail']})"
                      for p in player.page.evaluate(CHECK, {"rows": True}) if p["kind"] == "misaligned"]
    assert not found, "\n".join(found)


STAYS = """head => {  // where a list's column headings are once its rows have scrolled under them, against the edge
    // they stay at (a window's top, else Sheet's tabs), measured in one go: a window still opening moves both (Nov 16)
    const box = head.getBoundingClientRect(), hit = document.elementFromPoint(box.left + 40, box.top + box.height / 2);
    const win = head.closest('.peek-body'), edge = win ? win.getBoundingClientRect().top : document.querySelector('main .tabbar').getBoundingClientRect().bottom;
    const above = document.elementFromPoint(box.left + 40, box.top - 0.5);  // nothing of the rows shows above them
    return { off: box.top - edge, onTop: head.contains(hit), stuck: head.hasAttribute('data-stuck'),
             rowsAbove: !!(above && above.closest('.ls-row, .ls-grouphead')) };
}"""


def test_a_lists_column_headings_stay_while_it_scrolls(people, server):
    """Feedback 73 (Brett, Nov 16): in Change Wild Shape forms the column headings scrolled away, and the numbers under
    them meant nothing. Every list's headings stay at the top: on Sheet under the tabs, in a window at its top edge
    (the window's padding doesn't leave a gap the rows show through); a row brought into view lands below them. Brett,
    trying it: a sliver of the rows showed above them (the tabs' height had been rounded), and floating they were hard
    to tell from the rows: no gap now, and floating (`data-stuck`) they carry a shadow."""
    player = people("player")
    page = player.page
    page.set_viewport_size({"width": 1440, "height": 700})
    player.open(f"/characters/{server['cole']}")
    seen = 0
    for tab in ("t-features", "t-spells", "t-forms", "t-items"):
        page.click(f'main [data-tab="{tab}"]')
        head = page.locator(f"#{tab} .ls-head")
        if not head.is_visible():
            continue
        seen += 1
        rows = page.locator(f"#{tab} .ls-rows")
        page.evaluate("r => scrollTo(0, r.getBoundingClientRect().top + scrollY + 300)", rows.element_handle())
        page.wait_for_function("h => h.hasAttribute('data-stuck')", arg=head.element_handle())  # (marked on the frame after a scroll)
        at = head.evaluate(STAYS)
        assert at["onTop"] and at["stuck"] and not at["rowsAbove"] and abs(at["off"]) < 0.1, (tab, at)
        last = page.locator(f"#{tab} .ls-row").last
        last.evaluate("r => r.scrollIntoView({ block: 'start' })")
        assert last.evaluate("r => r.getBoundingClientRect().top") >= head.evaluate("h => h.getBoundingClientRect().bottom") - 1 or page.evaluate(
            "innerHeight + scrollY >= document.documentElement.scrollHeight - 1"), tab  # (or the page can't scroll further)
    assert seen >= 2, seen  # (the test Cole: the lists wide enough for their headings)

    page.set_viewport_size({"width": 1440, "height": 420})  # the Spell Book's window, short enough to scroll
    player.open(f"/characters/{server['cole']}/battle")
    page.click('[data-modal-url$="/spellbook"]')
    body = page.locator(".peek.open .peek-body")
    head = body.locator(".ls-head")
    head.wait_for()
    assert body.evaluate("b => (b.scrollTop = b.scrollHeight) > 0 && b.scrollTop > 0"), "the Spell Book's list doesn't scroll"
    page.wait_for_function("h => h.hasAttribute('data-stuck')", arg=head.element_handle())
    at = head.evaluate(STAYS)
    assert at["onTop"] and at["stuck"] and not at["rowsAbove"] and abs(at["off"]) < 0.1, at
    body.evaluate("b => b.scrollTop = 0")
    page.wait_for_function("h => !h.hasAttribute('data-stuck')", arg=head.element_handle())  # (at rest it's a plain heading again)
    assert not player.errors, player.errors


def test_nothing_covers_a_manage_pages_title_action(people, server):
    """Brett, Nov 16: on DM Tools "+ New item" sat under "⚙ Admin" (the way to the other half, placed over the top
    right), which kept room only beside a title placed straight under it, not one a page wraps (DM Tools' .dm-main).
    On every Manage and DM Tools page, at a laptop's widths, the page title's action is what's on top at its middle."""
    admin = people("admin")
    page, found = admin.page, []
    for width in (1280, 1440):
        page.set_viewport_size({"width": width, "height": 900})
        for path in PAGES["admin"]:
            admin.open(path)
            covered = page.evaluate("""() => [...(document.querySelector('main .title-row')?.querySelectorAll(':scope > .title-action') || [])].filter(a => a.checkVisibility()).filter(a => {
                const b = a.getBoundingClientRect(), hit = document.elementFromPoint((b.left + b.right) / 2, (b.top + b.bottom) / 2);
                return !hit || !a.contains(hit); }).length""")
            if covered:
                found.append(f"{path} at {width}px: a title action is covered")
    assert not found, "\n".join(found)
    assert not admin.errors, admin.errors


def _pills() -> dict:
    """The Live pill in each of its states, drawn by its own template (tn: what app/live.py hands it)."""
    from types import SimpleNamespace as N

    from app.templating import templates

    pill = templates.get_template("_live_pill.html")
    me = {"mine": True, "connects": True, "by_hand": 0, "step": False, "via": False, "failed": False, "dropped": False, "name": "Coleridge Thistlewood",
          "fetched_at": None, "in_game": True, "ddb_id": 1, "step_until": 0}
    party = dict(me, mine=False, connects=False, name="the party")

    def draw(p, **tn):  # (a player's own pill: their sheet is theirs to connect, so the bridge is wanted)
        tn = {"pill": N(**p), "focus": None, "mine": N(**p) if p["mine"] else None, "connectable": 1, "connected": 0, "via": 0,
              "playing": False, "dm": False, "every": 60, "party_pill": False, **tn}
        return pill.render(tn=N(**tn), fight_now=lambda: None)

    return {"connected": draw({**me, "step": True}), "via the DM": draw({**me, "via": True}), "not connected": draw(me),
            "open your sheet": draw(me, playing=True), "not sent": draw({**me, "by_hand": 1}), "not answering": draw({**me, "failed": True}),
            "party connected": draw(party, connectable=4, connected=4, dm=True), "party via": draw(party, connectable=4, connected=2, via=1, dm=True),
            "party some": draw(party, connectable=4, connected=2, dm=True), "party none": draw(party, connectable=4, dm=True)}


def test_the_live_pill_says_its_state_at_every_width(people, server):
    """The UI review, Nov 16: under 900px an old rule hid every state's words, so Not connected and None connected were a
    bare dot like Connected; and without the bridge a connected pill showed "Add the bridge" in a dot's width, 35px
    out of its box. Every state but connected says something at every width, one label at a time, inside the pill."""
    player = people("player")
    page = player.page
    found = []
    for width in WIDTHS:
        page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        player.open("/party")
        for bridge in (True, False):
            page.evaluate("b => document.body.classList.toggle('no-bridge', !b)", bridge)
            for state, html in _pills().items():
                seen = page.evaluate("""html => {
                  document.getElementById('live-pill').outerHTML = html;
                  const p = document.getElementById('live-pill'), on = e => e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden';
                  const labels = [...p.querySelectorAll('.lw-long, .lw-short, .live-noext')].filter(on);
                  return { dot: p.classList.contains('dot'), words: labels.map(l => l.textContent.trim()).filter(Boolean),
                           spills: p.scrollWidth > p.clientWidth + 1 };
                }""", html)
                where = f"{state} at {width}px{'' if bridge else ', no bridge'}"
                if not seen["dot"] and not seen["words"]:
                    found.append(f"{where}: a bare dot")
                if len(seen["words"]) > 1:
                    found.append(f"{where}: two labels at once, {seen['words']}")
                if seen["spills"]:
                    found.append(f"{where}: its words run out of the pill")
                found += problems(page, where)
    assert not found, "\n".join(found)



SHIFTS = """new PerformanceObserver(l => { window.__shifts = (window.__shifts || []).concat(
  l.getEntries().filter(e => !e.hadRecentInput).map(e => ({ value: e.value, nodes: (e.sources || []).map(s => s.node && (s.node.id || s.node.className || s.node.nodeName)) }))); })
  .observe({ type: 'layout-shift', buffered: true });"""


def test_pages_dont_shift_as_they_load(people, server):
    """The Table rolls sidebar takes its place before the page is drawn (base.html's first script),
    so nothing moves sideways while the page loads and the log arrives (Brett, 2026-10-26: every page jumped)."""
    player = people("player")
    player.context.add_init_script(SHIFTS)
    found = []
    for width in (1400, 1000):
        player.page.set_viewport_size({"width": width, "height": 900})
        for path in ("/c/main/campaign", "/c/main/campaign?tab=world", f"/characters/{server['cole']}/battle", f"/characters/{server['cole']}", "/party"):
            player.open(path)
            player.page.wait_for_load_state("networkidle")
            player.page.wait_for_timeout(800)  # the log's first load, and anything it moves
            shifts = player.page.evaluate("window.__shifts || []")
            total = sum(s["value"] for s in shifts)
            if total > 0.005:  # (none at all, today)
                found.append(f"{path} at {width}px moved {total:.3f}: {shifts[:3]}")
    assert not found, "\n".join(found)
    assert player.errors == []



def test_the_table_page_holds_together(people, server, browser_db, long_names):
    """askdnd's table (VTT slice 1) as a player, with a fight heard from D&D Beyond's VTT and without one, at every
    width; askdnd's VTT (Labs) on in its campaign for the test only."""
    import json
    from datetime import UTC, datetime

    order = [{"key": "t-cole", "name": "Cole", "kind": "character", "character": server["cole"], "monster": None, "initiative": 18,
              "hidden": False, "active": True, "image": None},
             {"key": "t-e1", "name": "Enemy 1 the Exceptionally Long-Named", "kind": "monster", "character": None, "monster": None,
              "initiative": 15, "hidden": False, "active": False, "image": None}]
    fight = {"id": "f1", "round": 2, "turn": 1, "order": order, "reminders": []}
    engine = create_engine(browser_db[0])
    player = people("player")
    player.allow("/map?v=")  # (the map's picture isn't there: only its layout is)

    def set_campaign(vtt_on, f):
        with engine.connect() as conn:
            conn.execute(text("UPDATE campaigns SET vtt_pieces = CAST(:p AS JSONB), fight = CAST(:f AS JSONB), fight_at = :at WHERE id = :c"),
                         {"p": json.dumps(["labs", "vtt"] if vtt_on else []), "f": json.dumps(f) if f else None,
                          "at": datetime.now(UTC) if f else None, "c": server["campaign"]})
            conn.commit()

    def with_map():  # a place with a map (its picture needn't be there for the layout), shown, with tokens on it
        with engine.connect() as conn:
            conn.execute(text("INSERT INTO stored_files (key, campaign_id, content_type, size) VALUES ('layout/map.webp', :c, 'image/webp', 1) ON CONFLICT DO NOTHING"),
                         {"c": server["campaign"]})
            pid = conn.execute(text("INSERT INTO places (campaign_id, name, map_key, map_w, map_h, grid) VALUES (:c, "
                                    "'The Exceptionally Long-Named Ruined Chapel of the Drowned Bell', 'layout/map.webp', 2100, 1400, "
                                    "CAST('{\"size\": 70, \"x\": 0, \"y\": 0}' AS JSONB)) RETURNING id"), {"c": server["campaign"]}).scalar()
            conn.execute(text("UPDATE campaigns SET shown_place_id = :p WHERE id = :c"), {"p": pid, "c": server["campaign"]})
            conn.execute(text("INSERT INTO tokens (campaign_id, place_id, kind, character_id, name, x, y, size) VALUES (:c, :p, 'character', :ch, 'Cole', 4, 4, 1)"),
                         {"c": server["campaign"], "p": pid, "ch": server["cole"]})
            conn.execute(text("INSERT INTO tokens (campaign_id, place_id, kind, name, x, y, size, hp, monster) VALUES (:c, :p, 'monster', "
                              "'Enemy 1 the Exceptionally Long-Named', 8, 4, 2, CAST('{\"current\": 20, \"max\": 59}' AS JSONB), "
                              "CAST('{\"key\": \"ogre\", \"name\": \"Ogre\"}' AS JSONB))"), {"c": server["campaign"], "p": pid})
            conn.commit()
        return pid

    def without_map():
        with engine.connect() as conn:
            conn.execute(text("UPDATE campaigns SET shown_place_id = NULL WHERE id = :c"), {"c": server["campaign"]})
            conn.execute(text("DELETE FROM places WHERE campaign_id = :c"), {"c": server["campaign"]})
            conn.commit()

    try:
        set_campaign(True, None)
        found = check(player, server, ("/c/main/table",))
        set_campaign(True, fight)
        found += check(player, server, ("/c/main/table",))
        with_map()
        found += check(player, server, ("/c/main/table",))
        admin = people("admin")
        admin.allow("/map?v=")
        found += check(admin, server, ("/c/main/table",))  # (the DM's tools: an admin has them too)
    finally:
        without_map()
        set_campaign(False, None)
        engine.dispose()
    assert not found, "\n".join(found)
    assert player.unexpected() == []


def test_table_rolls_is_a_full_height_panel_beside_the_bar_and_the_band(people, server):
    """Brett chose it, Nov 13: on a laptop Table rolls runs from the window's top as its own column (its title row level
    with the menu bar, a thin line under it, the red line the bar's alone: option A of docs/mockups/table-rolls-top/),
    and the menu bar and the connection band sit over the page beside it (#328 had the bar span the window with an empty
    stretch over Table rolls, and the band, inside the bar, lost its colour there and pushed Table rolls down)."""
    player = people("player")
    page = player.page
    page.set_viewport_size({"width": 1440, "height": 900})
    player.open(f"/characters/{server['cole']}/battle")
    if page.evaluate("document.body.classList.contains('rolls-closed')"):
        page.locator(".rs-edge").click()
    box = lambda sel: page.evaluate(f"(() => {{ const r = document.querySelector('{sel}').getBoundingClientRect(); return {{x: r.left, y: r.top, right: r.right, bottom: r.bottom}}; }})()")

    def check(band: bool):
        side, head, bar = box(".rolls-side"), box(".rs-head"), box(".topbar-inner")
        top = box(".topbar")
        assert side["y"] == 0, "Table rolls starts at the window's top"
        assert abs(head["bottom"] - (top["y"] + 62)) <= 1, "its title row ends level with the menu bar"
        line = page.evaluate("getComputedStyle(document.querySelector('.rs-head')).borderBottomColor")
        red = page.evaluate("getComputedStyle(document.querySelector('.topbar')).borderBottomColor")
        assert line != red, "its own column: a thin line under its title, the red line is the bar's alone (Brett chose A)"
        assert abs(top["x"] - side["right"]) <= 1 and bar["x"] >= side["right"], "the menu bar sits beside it, not over it"
        if band:
            b = box(".conn-band")
            assert abs(b["x"] - side["right"]) <= 1 and b["y"] >= top["y"] + 60, "the band sits under the bar, beside Table rolls"

    check(band=False)
    page.evaluate("const b = document.querySelector('.conn-band'); b.hidden = false; b.classList.remove('later'); b.classList.add('bad')")  # (as a dropped sheet shows it)
    page.wait_for_function("document.querySelector('.conn-band').offsetHeight > 0")
    check(band=True)
    page.set_viewport_size({"width": 1100, "height": 900})  # (narrower: it opens over the page, under the bar)
    page.wait_for_function("document.querySelector('.rolls-side').getBoundingClientRect().top > 0")


SPILL = """above => {
  const col = above.parentElement.closest('.reader-nav, .peek-body'), cs = getComputedStyle(col), c = col.getBoundingClientRect();
  const left = c.left + parseFloat(cs.paddingLeft), right = c.right - parseFloat(cs.paddingRight) - (col.offsetWidth - col.clientWidth);
  const out = [];
  above.querySelectorAll('*').forEach(el => { const r = el.getBoundingClientRect();
    if (r.width && (r.right > right + 0.5 || r.left < left - 0.5)) out.push((el.className || el.tagName) + ' by ' + Math.round(Math.max(r.right - right, left - r.left)) + 'px'); });
  const row = above.querySelector('.ls-above-row'), ch = parseFloat(getComputedStyle(row).getPropertyValue('--control-h'));
  return {out, lines: row.getBoundingClientRect().height / ch, pills: above.querySelectorAll('[data-ls-pills] > *').length};
}"""


@pytest.fixture(scope="module")
def every_kind(browser_db):
    """A published World entry of every kind, with long names, so World's Kind filter has all its chips."""
    url, ids = browser_db
    engine = create_engine(url)
    with engine.begin() as conn:
        for kind, name in (("npc", "Archivist Wendeline Ashgrove-Thorne"), ("place", "The Observatory Beneath the Drowned Bell"),
                           ("faction", "The Order of the Unbroken Saltmere Lantern"), ("item", "Lantern of the Long Night Watch"),
                           ("creature", "Hollow-Eyed Fog Wraith of the Reach"), ("other", "The Bargain at the Crossroads Shrine")):
            conn.execute(text("INSERT INTO entities (campaign_id, kind, name, traits, summary, status, created_at, updated_at) "
                              "VALUES (:c, :k, :n, '{}', '', 'published', now(), now())"), {"c": ids["campaign"], "k": kind, "n": name})
    engine.dispose()


def test_filters_above_a_list_stay_in_their_column_whatever_is_on(people, server, long_names, every_kind):
    """Brett, Nov 16 (chose A on docs/mockups/filters-above/ after three kinds on pushed World's filters past its
    column): in every place the filters sit above a list, at a laptop's and a phone's width, with one filter on, with
    every chip on, open and closed, nothing spills out of the column, the closed line takes two lines at most, its
    pills are two and "+N" at most, a pill's × takes off just its filter, and Clear takes them all off."""
    player = people("player")
    page, found = player.page, []
    places = (("World", "/c/main/campaign?tab=world", None),
              ("Notes you sent", "/your-notes?tab=askdnd", None),
              ("Battle's See all", "/characters/{cole}/battle", "[data-panel-url$='/all/action']"))
    for width in (375, 1280):
        page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
        for name, path, opener in places:
            player.open(path.format(cole=server["cole"]))
            page.wait_for_load_state("load")
            if opener:
                page.locator(f"{opener}:visible").first.click()
            above = page.locator(".ls-above:visible").first
            above.wait_for()
            where = f"{name} at {width}px"
            if above.locator("[data-ls-above-body]").is_hidden():
                above.locator(".ls-above-btn").click()
            chips = above.locator("[data-ls-group]")
            assert chips.count() >= 2, where
            for k in range(chips.count()):  # (every chip on: the most there can be)
                if chips.nth(k).get_attribute("aria-pressed") != "true":
                    chips.nth(k).click()
                if k == 0:
                    above.locator(".ls-above-btn").click()  # one on, closed
                    one = above.evaluate(SPILL)
                    found += [f"{where}, one on: {o}" for o in one["out"]]
                    assert one["pills"] == 1 and one["lines"] < 1.5, (where, one)
                    above.locator(".ls-above-btn").click()
            found += [f"{where}, all on, open: {o}" for o in above.evaluate(SPILL)["out"]]
            above.locator(".ls-above-btn").click()
            closed = above.evaluate(SPILL)
            found += [f"{where}, all on, closed: {o}" for o in closed["out"]] + problems(page, f"{where}, all on, closed")
            assert closed["lines"] < 2.6 and closed["pills"] <= 3, (where, closed)
            before = chips.evaluate_all("cs => cs.filter(c => c.getAttribute('aria-pressed') === 'true').length")
            above.locator(".ls-pill:not(.more)").first.click()  # (one ×: just that filter)
            assert chips.evaluate_all("cs => cs.filter(c => c.getAttribute('aria-pressed') === 'true').length") == before - 1, where
            above.locator("[data-ls-clear-filters]").click()
            assert chips.evaluate_all("cs => cs.filter(c => c.getAttribute('aria-pressed') === 'true').length") == 0, where
            assert above.locator(".ls-pill").count() == 0 and above.locator("[data-ls-clear-filters]").is_hidden(), where
    assert not found, "\n".join(found)


def test_the_menu_bar_never_runs_wider_than_a_phone(people, server, long_names):
    """GitHub's runs on main (Nov 16, twice): on askdnd's table at 375px, with a long campaign name, the menu bar spilled
    4px when the Live pill showed words (GitHub's fonts are a little wider than a Mac's). Every pill state, in the real bar
    at 320px, the narrowest iPhone (narrow enough to fail here without the fix): the bar stays inside the screen (the
    pill's words give way with …)."""
    player = people("player")
    page = player.page
    page.set_viewport_size({"width": 320, "height": 812})
    player.open("/c/main/campaign")
    found = []
    for state, html in _pills().items():
        spill = page.evaluate("""html => { const old = document.getElementById('live-pill'), t = document.createElement('template');
            t.innerHTML = html.trim(); old.replaceWith(t.content.firstElementChild);
            const bar = document.querySelector('header.topbar');
            return bar.scrollWidth - bar.clientWidth; }""", html)
        if spill > 0:
            found.append(f"{state}: {spill}px wider than the screen")
    assert not found, "\n".join(found)


def test_the_check_catches_words_squeezed_onto_two_lines_and_off_their_line(people, server):
    """Brett, Nov 19 ("is there a way to put a check in for alignment and wrapping that is more robust"): a row whose
    parts are equal shares wraps the longer one though everything fits on one line (squeezed); a bold label beside a
    smaller note, centred as boxes, puts their words on different lines (off baseline, a rule since the Live UI Audit;
    an icon like ✕ is left out). The same rows done right pass."""
    page = people("player").open("/help")
    page.set_content("""<body style="font: 15px sans-serif; width: 900px">
      <div id="even" style="display:flex; gap:12px; width:700px"><span style="flex:1">Available until 4:59 PM</span>
        <span style="flex:1">Claude isn't listening (last heard 4:10 PM) and a little more</span><span style="flex:1">Freeze off</span></div>
      <div id="natural" style="display:flex; gap:12px; width:700px"><span>Available until 4:59 PM</span>
        <span>Claude isn't listening (last heard 4:10 PM)</span><span>Freeze off</span></div>
      <div id="boxes" style="display:flex; align-items:center; gap:8px"><b style="font-size:24px">Available</b><span style="font-size:12px">until 4:59 PM</span></div>
      <div id="lined" style="display:flex; align-items:baseline; gap:8px"><b style="font-size:24px">Available</b><span style="font-size:12px">until 4:59 PM</span></div>
      <div id="icon" style="display:flex; align-items:center; gap:8px"><b style="font-size:24px">Spell Book</b><span style="font-size:12px">✕</span></div>
    </body>""")
    found = page.evaluate(CHECK, {})  # (off baseline is a rule since the Live UI Audit: no asking)
    kinds = {(p["kind"], p["where"].split(" > ")[0]) for p in found}
    assert ("squeezed", "#even") in kinds and ("off baseline", "#boxes") in kinds
    assert not {k for k in kinds if k[1] in ("#natural", "#lined", "#icon")}  # (an icon with no words is centred on purpose)
