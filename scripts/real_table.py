"""Real fights on the real D&D Beyond: named runs on the Mac Mini's test seats (docs/testing-setup.md).

On the Mini, never on GitHub: `.venv/bin/python real_table.py [run …]` after `real_table_seats.sh open` (every run when
none is named), and every night at 4:00 through real_table_nightly.sh, which adds `--sentry` (a miss goes to Sentry).
A run that misses is tried once more on tidied sheets (`--once`: not); passing then, its first misses are reported as
passed only on a second try, not as misses. Each night's checks are added to logs/results.jsonl (scripts/live_results.py).
`--after-deploy=<version>` is the quick check real_table_after_deploy.sh runs when beta's version changes (its own
Sentry issue). `--via-dm` runs the same changes with each player's sheet closed and only the DM's seat on a D&D Beyond page (the
campaign page), so the DM's browser makes them (Brett, 2026-11-04: Manage › askdnd › D&D Beyond bridge's table of what
each connection can change); every run that changes a sheet takes part, read back from the DM's page.
Each run does what a person would do, then says what happened and what it expected, and puts back what it changed;
part 1 starts by checking the test sheets are clean. It only ever touches the test seats in VTT test on beta: Brett's
primary account is not a seat here, and it never signs in to anything.
"""

import json
import sys
import time
from html import unescape

from playwright.sync_api import Page, sync_playwright
from playwright.sync_api import TimeoutError as PlaywrightTimeout

BETA = "https://beta.askdnd.ai/c/vtt-test"
SEATS = {"dm": 9231, "player2": 9232, "player3": 9233, "player4": 9234}
SHEETS = {"player2": 172986165, "player3": 172992073, "player4": 173148163}  # Cathartic, the new Vi and Levi; never the first Vi or Spurt
CAMPAIGN = "https://www.dndbeyond.com/campaigns/8224496"  # (VTT test on D&D Beyond: the DM's page for --via-dm)

# How long a change may take to show in D&D Beyond's own record. Usually a few seconds; now and then much longer (Nov 2:
# up to a minute, while D&D Beyond served an older copy for a moment), and a pass past 10 seconds is said as slow.
SLOW = 60


class Seats(dict):
    """Each seat's Chrome, reached the first time a run needs it."""

    def __init__(self, p):
        super().__init__()
        self.p = p

    def __missing__(self, seat: str):
        self[seat] = self.p.chromium.connect_over_cdp(f"http://127.0.0.1:{SEATS[seat]}").contexts[0]
        return self[seat]


class Remote:
    """A seat's sheet while it's closed (--via-dm): read and tidied from the DM's D&D Beyond page, whose browser makes
    askdnd's changes on it. Only what runs do with a sheet that isn't looking at it: its url (which sheet) and evaluate."""

    def __init__(self, page: Page, ddb_id: int):
        self.page, self.url = page, f"https://www.dndbeyond.com/characters/{ddb_id}"

    def evaluate(self, *args):
        return self.page.evaluate(*args)


class Table:
    def __init__(self, p, via_dm: bool = False):
        self.contexts = Seats(p)
        self.results: list[tuple[bool | None, str]] = []  # (True passed, False missed, None passed only on a second try)
        self.checks: list[dict] = []  # every check with its run and how long it took: the night's line in logs/results.jsonl
        self.run = ""
        self.last: Page | None = None
        self.via_dm = via_dm

    def page(self, seat: str, url: str) -> Page:
        page = next((x for x in self.contexts[seat].pages if x.url.startswith(url)), None) or self.contexts[seat].new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self.last = page  # (what a run that stops was looking at)
        return page

    def sheet(self, seat: str, frames: list[str] | None = None, ddb: int | None = None) -> Page:
        """A seat's sheet (or `ddb`, another character on its account: the twins); `frames` collects what passes on its
        connections, so a run can see the Game Log itself. With --via-dm, the sheet closed everywhere and the DM's D&D
        Beyond page standing in for it (`Remote`)."""
        ddb = ddb or SHEETS[seat]
        url = f"https://www.dndbeyond.com/characters/{ddb}"
        if self.via_dm:
            for ctx in [self.contexts[x] for x in SEATS]:
                for x in [x for x in ctx.pages if "dndbeyond.com/characters/" in x.url]:
                    x.close()
            return Remote(self.page("dm", CAMPAIGN), ddb)
        page = next((x for x in self.contexts[seat].pages if x.url.startswith(url)), None) or self.contexts[seat].new_page()
        if frames is not None:
            def listen(ws):
                ws.on("framesent", lambda text: frames.append(str(text)))
                ws.on("framereceived", lambda text: frames.append(str(text)))
            page.on("websocket", listen)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        return page

    def battle_of(self, seat: str, name: str) -> Page:
        """Another character the seat's account plays (a twin), found by its name in the menu bar's Party list, on Battle."""
        home = self.page(seat, f"{BETA}/party")
        cid = home.evaluate("""n => { const a = [...document.querySelectorAll('a[href^="/characters/"]')].find(x => x.textContent.includes(n));
                                      return a && a.getAttribute('href').match(/\\d+/)[0]; }""", name)
        if not cid:
            raise RuntimeError(f"{name} isn't on Party for {seat}'s account (is it in VTT test, played by it?)")
        page = self.page(seat, f"https://beta.askdnd.ai/characters/{cid}/battle")
        page.wait_for_selector(save("Dex"), timeout=20000)
        return page

    def battle(self, seat: str) -> Page:
        """The seat's own character on Battle, reached from the menu bar like a person would."""
        home = self.page(seat, f"{BETA}/party")
        cid = home.evaluate("document.querySelector('header a[href^=\"/characters/\"], nav a[href^=\"/characters/\"]').getAttribute('href').match(/\\d+/)[0]")
        page = self.page(seat, f"https://beta.askdnd.ai/characters/{cid}/battle")
        page.wait_for_selector(save("Dex"), timeout=20000)
        return page

    def expect(self, what: str, check, seconds: float = 20) -> bool:
        """Waits for `check()` to be true, like a person watching the page; a miss is a result, not a crash."""
        page = next(iter(self.contexts.values())).pages[0]  # (waiting on a page, so what pages hear keeps arriving)
        start = time.time()
        for _ in range(int(seconds * 2)):
            try:
                if check():
                    took = time.time() - start
                    self.note(True, what, took)
                    print("PASS", what, f"(slow: {took:.0f} seconds)" if took > 10 else "", flush=True)
                    return True
            except Exception:
                pass
            page.wait_for_timeout(500)
        self.note(False, what, time.time() - start)
        print("FAIL", what, flush=True)
        return False

    def note(self, ok: bool, what: str, seconds: float | None = None) -> None:
        """One result: kept for the summary and Sentry, and for the history (scripts/live_results.py)."""
        self.results.append((ok, f"{self.run}: {what}" if self.run else what))
        self.checks.append({"run": self.run, "what": what, "ok": ok, "seconds": None if seconds is None else round(seconds, 1)})


def pill(page: Page) -> str:
    return " ".join(page.locator("#live-pill").inner_text(timeout=3000).split())


def reached(t: Table, page: Page) -> bool:
    """askdnd's page says the sheet can be reached: its own sheet (Connected), or through the DM with --via-dm."""
    return ("Through the DM" if t.via_dm else "Connected") in pill(page)


def connects(t: Table, *pages: Page) -> None:
    """The run's sheets can be reached the way this pass means. Through the DM, a miss means a sheet is open in some
    other browser (Nov 4: Brett testing on his MacBook), which then makes the changes: the run stops there rather than
    passing changes the DM's browser didn't make."""
    what = "both sheets connect" if len(pages) > 1 else "the sheet connects"
    if not t.expect(what, lambda: all(reached(t, x) for x in pages), 40) and t.via_dm:
        raise RuntimeError("not through the DM: the pill says " + " / ".join(repr(pill(x)) for x in pages)
                           + " (a sheet open in another browser makes the changes; close it and run again)")


def save(ability: str) -> str:
    return f'[data-roll=save][data-label="{ability} save"]:visible >> nth=0'


def askdnd_rolls(frames: list[str]) -> int:
    """How many of askdnd's own rolls have passed on these connections."""
    return sum('"source":"askdnd"' in f.replace(" ", "") for f in frames)


def roll(page: Page, ability: str) -> str:
    """Reads what the roll window says about the Game Log before rolling, then rolls a save straight away."""
    page.click(save(ability))
    page.wait_for_timeout(800)
    note = " ".join(page.locator(".roll-win").first.inner_text(timeout=4000).split())
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    page.click(save(ability), modifiers=["Shift"])
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    return note


def game_log(t: Table, seat: str = "player2", other: str = "player3") -> None:
    """A roll in askdnd reaches D&D Beyond's Game Log while your sheet is open, and says why not once it's closed."""
    mine, theirs = [], []
    sheet = t.sheet(seat, mine)
    t.sheet(other, theirs)
    page = t.battle(seat)
    watching = t.page("dm", f"{BETA}/party")
    t.expect("the sheet connects before rolling", lambda: "Connected" in pill(page), 40)
    page.wait_for_timeout(3000)
    note = roll(page, "Dex")
    print("  roll window:", note[-110:], flush=True)
    t.expect("the roll window says it goes to the Game Log", lambda: "Also goes to D&D Beyond's Game Log" in note, 1)
    t.expect("the DM sees the roll in Table rolls", lambda: "Dex save" in watching.locator("#roll-log > li").first.text_content(), 15)
    t.expect("the roll leaves on the sheet's own connection", lambda: askdnd_rolls(mine) > 0, 15)
    t.expect("another player's sheet hears it", lambda: askdnd_rolls(theirs) > 0, 15)
    heard = askdnd_rolls(theirs)
    print("  frames:", askdnd_rolls(mine), heard, "| sheet tabs open:", sum(f"/{SHEETS[seat]}" in x.url for x in t.contexts[seat].pages), flush=True)
    sheet.close()
    t.expect("the pill says the sheet closed", lambda: "Connected" not in pill(page), 15)
    note = roll(page, "Wis")
    print("  roll window:", note[-110:], flush=True)
    t.expect("the roll window says the sheet isn't open", lambda: "your sheet isn't open" in note, 1)
    t.expect("the DM still sees the roll", lambda: "Wis save" in watching.locator("#roll-log > li").first.text_content(), 15)
    page.wait_for_timeout(4000)
    t.expect("nothing reaches the Game Log with the sheet closed", lambda: askdnd_rolls(theirs) == heard, 1)
    t.sheet(seat)


def closed_sheet(t: Table, seat: str = "player2") -> None:
    """Open your sheet and the pill says connected; close it and every open page of yours says so at once."""
    askdnd = t.page(seat, f"{BETA}/party")
    sheet = t.sheet(seat)
    t.expect("an open sheet connects the pill", lambda: "Connected" in pill(askdnd), 40)
    print("  pill:", pill(askdnd), flush=True)
    sheet.close()
    t.expect("closing the sheet changes the pill at once", lambda: "Connected" not in pill(askdnd), 15)
    print("  pill:", pill(askdnd), flush=True)
    sheet = t.sheet(seat)
    t.expect("opening it again connects the pill", lambda: "Connected" in pill(askdnd), 40)


def close_after_roll(t: Table, seat: str = "player2", times: int = 5) -> None:
    """A sheet closed right after a roll: the pill follows every time, not only when the timing is kind."""
    page = t.battle(seat)
    for n in range(times):
        sheet = t.sheet(seat)
        t.expect(f"{n + 1}: the sheet connects", lambda: "Connected" in pill(page), 40)
        page.wait_for_timeout(2000 + 3000 * n)  # (a different moment against the extension's 30-second tick each time)
        page.click(save("Dex"), modifiers=["Shift"])
        page.wait_for_timeout(1500)
        page.keyboard.press("Escape")
        sheet.close()
        t.expect(f"{n + 1}: the pill follows the closed sheet", lambda: "Connected" not in pill(page), 10)
        for s in range(40):
            if "Connected" not in pill(page):
                print(f"  pill changed within {10 + s} seconds", flush=True)
                break
            page.wait_for_timeout(1000)


def hp(page: Page) -> int:
    return int(page.locator('[data-panel-url$="/vital/hp"] b').first.inner_text(timeout=3000))


def change_hp(page: Page, mode: int, amount: int) -> None:
    """Hit points' panel, then Damage or Heal in the window, as a player does it."""
    page.locator('[data-panel-url$="/vital/hp"]').first.click()
    page.locator(".hp-open button").nth(mode).click(timeout=8000)
    page.locator('.peek.open .hp-form input[name="amount"]').first.fill(str(amount), timeout=8000)
    page.locator('.peek.open .hp-form input[name="amount"]').first.press("Tab")
    page.wait_for_timeout(800)
    page.locator('.peek.open .hp-form button[type="submit"]:not([disabled])').first.click(timeout=10000)  # (once its working has caught up)
    page.wait_for_timeout(800)
    page.keyboard.press("Escape")


def settled(page: Page) -> bool:
    return page.locator('[data-panel-url$="/vital/hp"][data-sync]').count() == 0


def on_sheet_hp(sheet, n: int, down: int) -> bool:
    """The sheet shows n Hit Points (`down` taken): on its own page as a person sees it, or (--via-dm) in D&D Beyond's
    record, which keeps what's taken."""
    if isinstance(sheet, Remote):
        return record(sheet)["removedHitPoints"] == down
    return str(n) in sheet.locator("[class*=hitPointsBox]").first.inner_text(timeout=2000)


CONDITION_IDS = {"Poisoned": 11, "Prone": 12, "Blinded": 1}


def on_sheet_condition(sheet, name: str) -> bool:
    if isinstance(sheet, Remote):
        return any(c.get("id") == CONDITION_IDS[name] for c in record(sheet).get("conditions") or [])
    return name in sheet.locator(".ct-conditions-summary").first.inner_text(timeout=3000)


def hit_points(t: Table, seat: str = "player2") -> None:
    """Damage made in askdnd lands on the real sheet and comes back confirmed; healing puts it back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    start, down = hp(page), record(sheet)["removedHitPoints"]
    print("  hit points:", start, flush=True)
    change_hp(page, 0, 1)
    t.expect("the tile shows 1 less at once", lambda: hp(page) == start - 1, 10)
    t.expect("D&D Beyond confirms it", lambda: settled(page), SLOW)
    t.expect("the real sheet shows it", lambda: on_sheet_hp(sheet, start - 1, down + 1), SLOW)
    page.wait_for_timeout(1000)
    change_hp(page, 1, 1)
    t.expect("healing puts it back", lambda: hp(page) == start, 10)
    t.expect("D&D Beyond confirms the healing", lambda: settled(page), SLOW)
    t.expect("the real sheet shows it back", lambda: on_sheet_hp(sheet, start, down), SLOW)


def condition(t: Table, seat: str = "player2", name: str = "Poisoned") -> None:
    """A condition started in askdnd lands on the real sheet; ended in askdnd, it leaves it."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    page.locator("details.cond-add > summary").click(timeout=5000)
    page.locator(f'.ls-chip:has-text("{name}")').first.click(timeout=5000)
    t.expect("the condition shows on Battle", lambda: page.locator(f'.cond-pill:has-text("{name}")').count() > 0, 8)
    t.expect("it reaches the real sheet", lambda: on_sheet_condition(sheet, name), SLOW)
    page.wait_for_timeout(1500)
    page.locator(f'details.cond-pill:not(.cond-add):has-text("{name}") > summary').first.click(timeout=5000)
    page.locator(f'details.cond-pill:not(.cond-add):has-text("{name}") button:has-text("End")').first.click(timeout=5000)
    t.expect("it ends on Battle", lambda: page.locator(f'details.cond-pill:not(.cond-add):has-text("{name}")').count() == 0, 15)
    t.expect("it leaves the real sheet", lambda: not on_sheet_condition(sheet, name), SLOW)


# D&D Beyond's record read as its own sheet reads it (and the extension: ddb-page.js `character`): signed in with a
# token, custom items included. Nov 2: a read with the browser's cookies alone lagged a change by a minute or more
# (three misses in round 3, each confirmed by askdnd's own read within seconds), so it's never used.
READ = """async url => {
  const t = await fetch('https://auth-service.dndbeyond.com/v1/cobalt-token', {method: 'POST', credentials: 'include'}).then(r => r.json());
  return fetch(url, {headers: {Authorization: 'Bearer ' + t.token, Accept: 'application/json'}, cache: 'no-store'}).then(r => r.json());
}"""


def record(sheet: Page) -> dict:
    """The sheet as D&D Beyond itself keeps it, so a run never relies on a label on either page."""
    cid = sheet.url.split("/characters/")[1].split("/")[0].split("?")[0]
    return record_of(sheet, cid)


def changes(before, after, path: str = "") -> list[tuple[str, object, object]]:
    """Every value that differs between two records, leaving out what D&D Beyond works out or stamps by itself (and the
    lists of what a choice could be, which change when D&D Beyond adds content: Nov 4, a feat's spell list; what's
    chosen is still compared)."""
    if isinstance(before, dict) and isinstance(after, dict):
        return [c for k in sorted(set(before) | set(after))
                if k not in ("dateModified", "providedFrom", "readonlyUrl", "definition", "choiceDefinitions", "optionIds")
                for c in changes(before.get(k), after.get(k), f"{path}.{k}")]
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        if all(isinstance(x, dict) for x in before + after):  # (D&D Beyond's lists come in any order, ids not always unique)
            order = lambda x: (str(x.get("id")), json.dumps(x, sort_keys=True, default=str))
            before, after = sorted(before, key=order), sorted(after, key=order)
        return [c for i, (a, b) in enumerate(zip(before, after)) for c in changes(a, b, f"{path}[{i}]")]
    return [] if before == after else [(path, before, after)]


def show(diff: list) -> str:
    return "; ".join(f"{path} {str(a)[:60]} to {str(b)[:60]}" for path, a, b in diff[:8]) + (f" and {len(diff) - 8} more" if len(diff) > 8 else "") or "nothing"


def go(page: Page, opener) -> None:
    """Opens a live state window and waits for its main button."""
    opener.click(timeout=8000)
    page.wait_for_selector("[data-use-go]", timeout=8000)


def changed(t: Table, sheet: Page, before: dict, what: str, seconds: float = SLOW) -> list:
    """Waits for D&D Beyond's own record to differ from `before`."""
    t.expect(what, lambda: bool(changes(before, record(sheet))), seconds)
    diff = changes(before, record(sheet))
    print("  D&D Beyond:", show(diff), flush=True)
    return diff


def undone(t: Table, sheet: Page, before: dict, what: str, seconds: float = SLOW) -> None:
    t.expect(what, lambda: not changes(before, record(sheet)), seconds)


def undo(page: Page) -> bool:
    """The corner card's Undo, if its card is still up: a card with a button stays 20 seconds (app.js), and D&D Beyond
    can take longer than that to show the change. False when it's gone, and the run puts the change back another way."""
    button = page.locator('#cards button:has-text("Undo")')
    if not button.count():
        print("  (Undo's card had gone: put back another way)", flush=True)
        return False
    button.last.click(timeout=8000)
    return True


def spell_window(page: Page) -> None:
    """The Spell Book, then the cast window of the first spell with a slot to spend (a cantrip with Concentration has none)."""
    page.locator(".spellbook-btn").first.click(timeout=8000)
    page.wait_for_selector('.sb-actions button[data-use-url*="/cast?"]', timeout=8000)
    rows = page.locator('.sb-actions button[data-use-url*="/cast?"]')
    for i in range(rows.count()):
        go(page, rows.nth(i))
        if page.locator('select[name="way"] option').count():
            return
        page.locator(".rp-x").first.click()


def cast(t: Table, seat: str = "player3") -> None:
    """Cast spends a real slot, shown on D&D Beyond; Undo gives it back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    spell_window(page)
    print("  spell:", page.locator(".rw-title").first.inner_text(), page.locator('select[name="way"] option').all_inner_texts(), flush=True)
    level = page.locator('select[name="way"] option:checked').first.get_attribute("data-level") or "1"
    page.locator("[data-use-go]").first.click()
    changed(t, sheet, before, "the slot is spent on D&D Beyond")
    if not undo(page):
        page.goto(page.url, wait_until="domcontentloaded")  # (Battle afresh: the Spell Book closed)
        go(page, page.locator(f'[data-use-url$="/count?field=slot:{level}"]:visible').first)
        page.locator('[data-use-go][data-to="back"]').first.click(timeout=15000)
    undone(t, sheet, before, "Undo gives the slot back on D&D Beyond")


def resource(t: Table, seat: str = "player3") -> None:
    """A resource counted down in askdnd counts down on D&D Beyond, and comes back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    count = page.locator('.res-go[data-use-url*="/count"]').count()
    print("  resources:", count, flush=True)
    go(page, page.locator('.res-go[data-use-url*="/count"]').first)
    page.locator('[data-use-go][data-to="use"]').first.click()
    changed(t, sheet, before, "the use is spent on D&D Beyond")
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    go(page, page.locator('.res-go[data-use-url*="/count"]').first)
    page.locator('[data-use-go][data-to="back"]').first.click()
    undone(t, sheet, before, "giving it back restores D&D Beyond")


def coins(t: Table, seat: str = "player3") -> None:
    """Coins gained in askdnd land on D&D Beyond; spending them takes them off."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    page.goto(page.url.replace("/battle", ""), wait_until="domcontentloaded")
    for to, what in (("gain", "the coin is on D&D Beyond"), ("spend", "spending it takes it off")):  # (the window both ways:
        tab = page.locator('[data-tab="t-items"]:visible').first                                       # Undo's card is gone
        if tab.get_attribute("aria-selected") != "true":                                                # after a few seconds)
            tab.click(timeout=8000)
        for tries in (1, 2):  # (Nov 4: the window opened and was gone before Spend, with the page drawn again around it)
            go(page, page.locator('[data-use-url$="/coins"]:visible').first)
            try:
                page.locator('.roll-win input[name="amount"]:visible').first.fill("1", timeout=5000)
                page.locator(f'.roll-win [data-use-go][data-to="{to}"]:visible').first.click(timeout=5000)
                break
            except PlaywrightTimeout:
                if tries == 2:
                    raise
                print("  the coins window closed before its button: opened again", flush=True)
                page.wait_for_timeout(2000)
        if to == "gain":
            changed(t, sheet, before, what)
        else:
            undone(t, sheet, before, what)
        page.wait_for_timeout(1500)
        page.keyboard.press("Escape")
        page.wait_for_selector(".roll-win", state="detached", timeout=8000)  # (Nov 4: the next window opened while this
        page.wait_for_timeout(1000)                                         # one closed, and the page swapped under it)


def spent(data: dict) -> int:
    return sum((x.get("limitedUse") or {}).get("numberUsed") or 0 for group in data["actions"].values() for x in group or [])


def rest_window(page: Page, kind: str) -> None:
    page.locator('[data-panel-url$="/vital/hp"]').first.click()
    go(page, page.locator(f'[data-use-url$="/rest?kind={kind}"]').first)
    print(f"  {kind} rest lists:", page.locator(".rest-list li").all_inner_texts(), flush=True)


def rests(t: Table, seat: str = "player3") -> None:
    """A Short Rest spends a real Hit Point Die and heals; a Long Rest brings the die and the Hit Points back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    change_hp(page, 0, 3)
    t.expect("D&D Beyond confirms the damage", lambda: settled(page), SLOW)
    page.wait_for_timeout(1500)
    start = record(sheet)
    print("  before the rest:", start["removedHitPoints"], "down,", [c.get("hitDiceUsed") for c in start["classes"]], "Hit Point Dice used", flush=True)
    rest_window(page, "short")
    page.locator('select[name^="dice_"]').first.select_option("1")
    page.locator("[data-use-go]").first.click()
    t.expect("a Hit Point Die is spent on D&D Beyond", lambda: sum(c.get("hitDiceUsed") or 0 for c in record(sheet)["classes"]) > sum(c.get("hitDiceUsed") or 0 for c in start["classes"]), SLOW)
    print("  after the Short Rest:", show(changes(start, record(sheet))), flush=True)
    page.wait_for_timeout(2500)
    page.keyboard.press("Escape")
    page.goto(page.url, wait_until="domcontentloaded")
    name = next(x["name"] for group in start["actions"].values() for x in group or []
                if (x.get("limitedUse") or {}).get("resetType") == 2 and x["limitedUse"].get("maxUses"))  # (back on a Long Rest)
    go(page, page.locator(f'.res-go[data-use-url*="/count"]:has-text("{name}")').first)
    page.locator('[data-use-go][data-to="use"]').first.click()
    t.expect("a use is spent before the Long Rest", lambda: spent(record(sheet)) > spent(start), SLOW)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    spell_window(page)
    page.locator("[data-use-go]").first.click()
    t.expect("a slot is spent before the Long Rest", lambda: any(x["used"] for x in record(sheet)["spellSlots"]), SLOW)
    page.wait_for_timeout(2500)
    page.goto(page.url, wait_until="domcontentloaded")
    middle = record(sheet)
    print("  before the Long Rest:", middle["removedHitPoints"], "down,", spent(middle), "uses spent,", [x["used"] for x in middle["spellSlots"]], "slots used", flush=True)
    rest_window(page, "long")
    page.locator("[data-use-go]").first.click()
    t.expect("the Long Rest gives Hit Point Dice back on D&D Beyond", lambda: not any(c.get("hitDiceUsed") for c in record(sheet)["classes"]), SLOW)
    t.expect("the Long Rest gives Hit Points back on D&D Beyond", lambda: record(sheet)["removedHitPoints"] == 0, 15)
    t.expect("the Long Rest gives slots back on D&D Beyond", lambda: not any(x["used"] for x in record(sheet)["spellSlots"]), SLOW)
    t.expect("the Long Rest gives the use back on D&D Beyond", lambda: spent(record(sheet)) <= spent(start), 70)
    print("  after the Long Rest:", show(changes(middle, record(sheet))), flush=True)


def mode(page: Page, which: str) -> None:
    """Hit points' panel, then one of its windows: Damage, Heal or Temporary HP."""
    page.locator('[data-panel-url$="/vital/hp"]').first.click()
    page.locator(f'.hp-open [data-modal-url$="mode={which}"]').first.click(timeout=8000)


def hp_window(page: Page, which: str, amount: int) -> None:
    mode(page, which)
    page.locator('.peek.open .hp-form input[name="amount"]').first.fill(str(amount), timeout=8000)
    page.locator('.peek.open .hp-form input[name="amount"]').first.press("Tab")
    page.wait_for_timeout(800)
    # Temporary HP: the player's choice is to take the new ones, pressed until the window says so (before PR 148, a late
    # redraw from typing the amount could put it back on Keep)
    for _ in range(8 if which == "temp" else 0):
        if f"Set {amount} temp" in page.locator(".peek.open .hp-form button[type=submit]").first.inner_text():
            break
        page.locator('.peek.open .hp-take label:has(input[value="1"])').first.click(timeout=5000)
        page.wait_for_timeout(1000)
    page.locator('.peek.open .hp-form button[type="submit"]:not([disabled])').first.click(timeout=10000)  # (once its working has caught up)
    page.wait_for_timeout(800)
    page.keyboard.press("Escape")


def temp_hp(t: Table, seat: str = "player2") -> None:
    """Temporary Hit Points given in askdnd land on the real sheet; damage takes them first and leaves Hit Points be."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    start = record(sheet)
    hp_window(page, "temp", 5)
    t.expect("D&D Beyond has 5 Temporary Hit Points", lambda: record(sheet)["temporaryHitPoints"] == 5, SLOW)
    page.wait_for_timeout(1500)
    hp_window(page, "damage", 5)
    t.expect("damage takes the Temporary Hit Points first", lambda: record(sheet)["temporaryHitPoints"] == 0, SLOW)
    t.expect("and leaves Hit Points as they were", lambda: record(sheet)["removedHitPoints"] == start["removedHitPoints"], 5)


def unconscious(data: dict) -> bool:
    return any(c["id"] == 15 for c in data.get("conditions") or [])


def death_saves(t: Table, seat: str = "player2") -> None:
    """At 0 Hit Points: Unconscious and the marks start on the real sheet, a death save rolled in askdnd marks itself
    there, and healing clears the marks and ends Unconscious."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    start, now = record(sheet), hp(page)
    print("  hit points:", now, flush=True)
    hp_window(page, "damage", now)
    t.expect("D&D Beyond has 0 Hit Points and Unconscious", lambda: (lambda d: d["removedHitPoints"] >= start["removedHitPoints"] + now and unconscious(d))(record(sheet)), SLOW)
    t.expect("the Dying tile offers the death save", lambda: page.locator('[data-roll="death"]:visible').count() > 0, 15)
    page.wait_for_timeout(1500)
    page.locator('[data-roll="death"]:visible').first.click(modifiers=["Shift"])
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    marked = lambda d: (d["deathSaves"]["successCount"] or 0) + (d["deathSaves"]["failCount"] or 0) > 0 or d["removedHitPoints"] < start["removedHitPoints"] + now  # (a 20 is back with 1 Hit Point)
    t.expect("the death save marks the real sheet", lambda: marked(record(sheet)), SLOW)
    print("  death saves:", record(sheet)["deathSaves"], flush=True)
    page.wait_for_timeout(1500)
    page.goto(page.url, wait_until="domcontentloaded")
    back = record(sheet)["removedHitPoints"] - start["removedHitPoints"]
    hp_window(page, "heal", back)
    t.expect("healing clears the marks on D&D Beyond", lambda: not any((record(sheet)["deathSaves"][k] or 0) for k in ("successCount", "failCount")), SLOW)
    t.expect("and ends Unconscious", lambda: not unconscious(record(sheet)), 15)
    t.expect("and Hit Points are back", lambda: record(sheet)["removedHitPoints"] == start["removedHitPoints"], 15)


def inspiration(t: Table, seat: str = "player2") -> None:
    """Heroic Inspiration given in askdnd lands on the real sheet; spending it takes it off."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    had = record(sheet)["inspiration"]
    for want in (not had, had):
        go(page, page.locator('[data-use-url$="/inspiration"]:visible').first)
        page.locator("[data-use-go]").first.click()
        t.expect(f"D&D Beyond {'has' if want else 'no longer has'} it", lambda: record(sheet)["inspiration"] == want, SLOW)
        page.wait_for_timeout(1500)
        page.keyboard.press("Escape")


def exhaustion(t: Table, seat: str = "player2") -> None:
    """Exhaustion started in askdnd lands on the real sheet at its level; a new level follows, and ending it leaves."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    level = lambda: next((c.get("level") for c in record(sheet).get("conditions") or [] if c["id"] == 4), None)
    page.locator("details.cond-add > summary").click(timeout=5000)
    page.locator('.ls-chip:has-text("Exhaustion")').first.click(timeout=5000)
    t.expect("D&D Beyond has Exhaustion 1", lambda: level() == 1, 25)
    page.wait_for_timeout(1500)
    pill_ = 'details.cond-pill:not(.cond-add):has-text("Exhaustion")'
    page.locator(f"{pill_} > summary").first.click(timeout=5000)
    page.locator(f'{pill_} button[title="Exhaustion level 2"]').first.click(timeout=5000)
    t.expect("D&D Beyond has Exhaustion 2", lambda: level() == 2, 25)
    page.wait_for_timeout(1500)
    page.locator(f"{pill_} > summary").first.click(timeout=5000)
    page.locator(f'{pill_} button:has-text("End")').first.click(timeout=5000)
    t.expect("ending it takes it off D&D Beyond", lambda: level() is None, 25)


# What the inventory run needs on Cathartic's test sheet (D&D Beyond's 2024 items): added once, as its player would
STOCK = {"Potion of Healing": (8960641, 112130694, 3), "Staff of Healing": (9229097, 112130694, 1)}
STOCKING = """async ([id, want]) => {
  const t = await fetch('https://auth-service.dndbeyond.com/v1/cobalt-token', {method: 'POST', credentials: 'include'});
  const h = {'Content-Type': 'application/json', Authorization: 'Bearer ' + (await t.json()).token};
  const r = await fetch('https://character-service.dndbeyond.com/character/v5/inventory/item', {method: 'POST', headers: h,
    body: JSON.stringify({characterId: id, equipment: want.map(([e, type, n]) => ({entityId: e, entityTypeId: type, quantity: n,
      containerEntityId: id, containerEntityTypeId: 1581111423}))})});
  return r.status;
}"""


def stock(sheet: Page) -> dict:
    """The inventory rows the run uses, by name, adding any that are missing and topping up any run short first."""
    have = {i["definition"]["name"]: i for i in record(sheet)["inventory"]}
    missing = [list(v) for k, v in STOCK.items() if k not in have]
    short = [["PUT", "inventory/item/quantity", {"id": have[k]["id"], "quantity": n}] for k, (_, _, n) in STOCK.items() if k in have and have[k]["quantity"] < n]
    if missing:
        print("  adding to the test sheet:", [k for k in STOCK if k not in have], sheet.evaluate(STOCKING, [SHEETS["player2"], missing]), flush=True)
    if short:
        print("  topping up the test sheet:", sheet.evaluate(TIDYING, [SHEETS["player2"], short]), flush=True)
    if missing or short:
        have = {i["definition"]["name"]: i for i in record(sheet)["inventory"]}
    return have


def item(data: dict, iid: int) -> dict:
    return next(i for i in data["inventory"] if i["id"] == iid)


def item_panel(page: Page, cid: str, iid: int) -> None:
    """Sheet › Items, then the item's own panel."""
    page.goto(f"https://beta.askdnd.ai/characters/{cid}", wait_until="domcontentloaded")
    tab = page.locator('[data-tab="t-items"]:visible').first
    tab.wait_for(timeout=15000)
    if tab.get_attribute("aria-selected") != "true":  # (the page may open on it: it remembers your last tab)
        tab.click(timeout=8000)
    page.locator(f'[data-panel-url*="ref=item%3A{iid}"]:visible').first.click(timeout=8000)
    page.wait_for_selector(".peek.open .peek-body", timeout=8000)


def press(page: Page, cid: str, iid: int, label: str) -> None:
    """The item's panel button with exactly this label, once askdnd's copy of the sheet has caught up to show it."""
    for _ in range(10):
        item_panel(page, cid, iid)
        button = page.locator(f'.peek.open button:text-is("{label}")')
        if button.count():
            button.first.click(timeout=8000)
            return
        page.wait_for_timeout(2000)
    raise TimeoutError(f"no {label} in the item's panel")


def inventory(t: Table, seat: str = "player2") -> None:
    """Equip, attune, an item's count, its charges and a potion drunk through Use, each made in askdnd and confirmed on
    D&D Beyond's own record, then put back."""
    sheet = t.sheet(seat)
    have = stock(sheet)
    page = t.battle(seat)
    connects(t, page)
    cid = page.url.split("/characters/")[1].split("/")[0]
    staff, potion = have["Staff of Healing"]["id"], have["Potion of Healing"]["id"]
    start = record(sheet)
    for field, on, off in (("equipped", "Equip", "Unequip"), ("isAttuned", "Attune", "End attunement")):
        was = item(start, staff)[field]
        press(page, cid, staff, off if was else on)
        t.expect(f"{on}: D&D Beyond follows", lambda: item(record(sheet), staff)[field] != was, SLOW)
        press(page, cid, staff, on if was else off)
        t.expect(f"{on}: and back", lambda: item(record(sheet), staff)[field] == was, SLOW)
    item_panel(page, cid, staff)
    used = lambda d: (item(d, staff).get("limitedUse") or {}).get("numberUsed") or 0
    go(page, page.locator('.peek.open [data-use-url*="field=charges"]').first)
    page.locator('[data-use-go][data-to="use"]').first.click()
    t.expect("a charge is spent on D&D Beyond", lambda: used(record(sheet)) == used(start) + 1, SLOW)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    item_panel(page, cid, staff)
    go(page, page.locator('.peek.open [data-use-url*="field=charges"]').first)
    page.locator('[data-use-go][data-to="back"]').first.click()
    t.expect("and given back", lambda: used(record(sheet)) == used(start), SLOW)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    bolts = have["Crossbow Bolts"]["id"]
    many = lambda d: item(d, bolts)["quantity"]
    for to, n, what in (("use", -1, "one is used on D&D Beyond"), ("back", 0, "and given back")):
        item_panel(page, cid, bolts)
        go(page, page.locator('.peek.open [data-use-url*="field=item"]').first)
        page.locator(f'[data-use-go][data-to="{to}"]').first.click()
        t.expect(f"Crossbow Bolts: {what}", lambda: many(record(sheet)) == many(start) + n, SLOW)
        page.wait_for_timeout(1500)
        page.keyboard.press("Escape")
    count = lambda d: item(d, potion)["quantity"]
    hp_window(page, "damage", 5)  # (so the potion's healing shows)
    hurt = start["removedHitPoints"] + 5
    t.expect("D&D Beyond has the damage", lambda: record(sheet)["removedHitPoints"] == hurt, SLOW)
    page.goto(f"https://beta.askdnd.ai/characters/{cid}/battle", wait_until="domcontentloaded")
    page.locator('[data-panel-url$="/all/bonus?items=1"]').first.click(timeout=8000)  # (every potion is a Bonus Action)
    go(page, page.locator(f'.peek.open [data-use-url$="/use/{potion}"]').first)
    page.locator("[data-use-go]").first.click()
    t.expect("drinking a Potion of Healing takes one off D&D Beyond", lambda: count(record(sheet)) == count(start) - 1, SLOW)
    t.expect("and heals there", lambda: record(sheet)["removedHitPoints"] < hurt, SLOW)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    if undo(page):
        t.expect("Undo puts the potion back on D&D Beyond", lambda: count(record(sheet)) == count(start), SLOW)
        t.expect("and the healing", lambda: record(sheet)["removedHitPoints"] == hurt, SLOW)
    else:
        stock(sheet)
    page.wait_for_timeout(1500)
    healed = record(sheet)["removedHitPoints"] - start["removedHitPoints"]
    if healed > 0:
        hp_window(page, "heal", healed)
    t.expect("and Hit Points are back", lambda: record(sheet)["removedHitPoints"] == start["removedHitPoints"], SLOW)


def record_of(page: Page, ddb_id: int) -> dict:
    """A sheet's record read from any D&D Beyond page, for when the sheet itself is closed."""
    got = page.evaluate(READ, f"https://character-service.dndbeyond.com/character/v5/character/{ddb_id}?includeCustomItems=true")
    return got["data"]


def cid_of(page: Page) -> str:
    return page.url.split("/characters/")[1].split("/")[0]


def sheet_tab(page: Page, cid: str, tab: str) -> None:
    """The character's Sheet on one of its tabs (Spells, Items), as a player opens it."""
    page.goto(f"https://beta.askdnd.ai/characters/{cid}", wait_until="domcontentloaded")
    t = page.locator(f'[data-tab="{tab}"]:visible').first
    t.wait_for(timeout=15000)
    if t.get_attribute("aria-selected") != "true":
        t.click(timeout=8000)


def prepared(data: dict) -> set[str]:
    return {sp["definition"]["name"] for cs in data.get("classSpells") or [] for sp in cs.get("spells") or [] if sp.get("prepared")}


def prepare_these(page: Page, cid: str, names: list[str]) -> None:
    """Sheet › Spells › Prepare spells: tick or untick each of `names`, then Make these changes."""
    sheet_tab(page, cid, "t-spells")
    page.locator('[data-modal-url*="/spells/prepare"]:visible').first.click(timeout=8000)
    page.wait_for_selector(".peek.open [data-prep]", timeout=15000)
    for n in names:
        page.locator(f'.peek.open .prep-row[data-name="{n}"] [data-prep-tick]').first.click(timeout=8000)
    page.locator(".peek.open [data-prep-make]").first.click(timeout=8000)
    page.wait_for_timeout(2500)
    page.keyboard.press("Escape")


def prepare(t: Table, seat: str = "player2") -> None:
    """Prepare spells (extension 0.9.8): one spell prepared and one dropped in askdnd's window reach D&D Beyond; then both
    put back the same way."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    cid, start = cid_of(page), prepared(record(sheet))
    sheet_tab(page, cid, "t-spells")
    page.locator('[data-modal-url*="/spells/prepare"]:visible').first.click(timeout=8000)
    page.wait_for_selector(".peek.open [data-prep]", timeout=15000)
    add = page.locator('.peek.open .prep-row[data-on=""]:not([data-always])').first.get_attribute("data-name")
    drop = page.locator('.peek.open .prep-row[data-on="1"]:not([data-always])').first.get_attribute("data-name")
    page.keyboard.press("Escape")
    print(f"  prepare {add}, drop {drop}", flush=True)
    prepare_these(page, cid, [add, drop])
    t.expect(f"D&D Beyond has {add} prepared and {drop} not", lambda: (lambda p: add in p and drop not in p)(prepared(record(sheet))), SLOW)
    page.wait_for_timeout(1500)
    prepare_these(page, cid, [add, drop])
    t.expect("and both back as they were", lambda: prepared(record(sheet)) == start, SLOW)


def how_many(data: dict, name: str) -> int:
    return sum(i["quantity"] for i in data["inventory"] if i["definition"]["name"] == name)


def give_one(page: Page, cid: str, iid: int, to: str) -> None:
    """An item's panel › Give, to the character named `to`, once askdnd's copy of the sheet shows the item."""
    for _ in range(10):
        sheet_tab(page, cid, "t-items")
        link = page.locator(f'[data-panel-url*="ref=item%3A{iid}"]:visible')
        if link.count():
            break
        page.wait_for_timeout(3000)
    link.first.click(timeout=8000)
    page.wait_for_selector(".peek.open .peek-body", timeout=8000)
    page.locator('.peek.open [data-use-url$="/give"]').first.click(timeout=8000)
    page.wait_for_selector("[data-use-go]", timeout=8000)
    pick = page.locator('select[name="receiver"]').first
    label = next(o for o in pick.locator("option").all_inner_texts() if o.startswith(to))
    pick.select_option(label=label)
    page.locator("[data-use-go]").first.click()
    page.wait_for_timeout(2500)
    page.keyboard.press("Escape")


def give(t: Table, seat: str = "player2", other: str = "player3") -> None:
    """Give (extension 0.9.8): a Potion of Healing handed to another character at the table comes off one sheet and onto
    the other, and is given back the same way. D&D Beyond can't move an item, so each side gets a fresh row: the run
    puts the giver's rows back as one."""
    sheet, theirs = t.sheet(seat), t.sheet(other)
    have = stock(sheet)
    page, them = t.battle(seat), t.battle(other)
    connects(t, page, them)
    name, potion = "Potion of Healing", have["Potion of Healing"]["id"]
    mine0, theirs0 = how_many(record(sheet), name), how_many(record(theirs), name)
    name_of = lambda pg: pg.locator(".char-name h1").first.inner_text().split("\n")[0].strip()  # (askdnd's name, as the list says it)
    give_one(page, cid_of(page), potion, name_of(them))
    t.expect("one fewer on the giver's sheet", lambda: how_many(record(sheet), name) == mine0 - 1, SLOW)
    t.expect("and one more on the other", lambda: how_many(record(theirs), name) == theirs0 + 1, SLOW)
    page.wait_for_timeout(1500)
    new = max(i["id"] for i in record(theirs)["inventory"] if i["definition"]["name"] == name)
    give_one(them, cid_of(them), new, name_of(page))
    t.expect("given back: the giver has as many as before", lambda: how_many(record(sheet), name) == mine0, SLOW)
    t.expect("and the other as many as before", lambda: how_many(record(theirs), name) == theirs0, SLOW)
    rows = [i for i in record(sheet)["inventory"] if i["definition"]["name"] == name]
    extra = [i["id"] for i in rows if i["id"] != potion]
    if extra:  # (the giver's fresh row folded back into the first)
        print("  tidying the giver's rows:", sheet.evaluate(TIDYING, [SHEETS[seat], [["PUT", "inventory/item/quantity", {"id": potion, "quantity": mine0}],
                                                                                    *[["DELETE", "inventory/item", {"id": x, "removeContainerContents": False}] for x in extra]]]), flush=True)


def browse(page: Page, cid: str, search: str) -> None:
    """The item browser on a character's Sheet › Items (Add item, or the DM's Give loot), with + pressed on the one item
    the search finds."""
    sheet_tab(page, cid, "t-items")
    page.locator("button[data-modal-url*='/items/browse']:visible").first.click(timeout=8000)
    page.locator(".peek.open [data-ib] [data-ls-row]").first.wait_for(timeout=15000)
    page.fill("[data-ib] [data-ls-search]", search)
    page.locator(f'[data-ib] [data-ls-row][data-label="{search}"]').first.locator("[data-ib-add]").click()


def take_off(t: Table, seat: str, sheet: Page, start: dict, name: str) -> None:
    added = [i["id"] for i in record(sheet)["inventory"] if i["definition"]["name"] == name and i["id"] not in {x["id"] for x in start["inventory"]}]
    if added:
        print(f"  taking the {name} off:", sheet.evaluate(TIDYING, [SHEETS[seat], [["DELETE", "inventory/item", {"id": x, "removeContainerContents": False}] for x in added]]), flush=True)


def worth(d: dict) -> int:
    """A sheet's coins, in copper."""
    c = d.get("currencies") or {}
    return sum((c.get(k) or 0) * v for k, v in {"cp": 1, "sp": 10, "ep": 50, "gp": 100, "pp": 1000}.items())


def loot(t: Table, seat: str = "player2") -> None:
    """Give loot (the DM, in the item browser): a Torch from D&D Beyond's 2024 items and 1 gp land on a player's sheet;
    then taken off."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    cid, start = cid_of(page), record(sheet)
    gp = lambda d: (d.get("currencies") or {}).get("gp") or 0
    dm = t.page("dm", f"https://beta.askdnd.ai/characters/{cid}")
    browse(dm, cid, "Torch")
    dm.fill("[data-ib-amount]", "1")
    dm.click("[data-ib-go]", timeout=8000)
    t.expect("a Torch reaches the sheet", lambda: how_many(record(sheet), "Torch") == how_many(start, "Torch") + 1, SLOW)
    t.expect("and 1 gp", lambda: gp(record(sheet)) == gp(start) + 1, SLOW)
    dm.wait_for_timeout(1500)
    take_off(t, seat, sheet, start, "Torch")
    sheet_tab(page, cid, "t-items")
    go(page, page.locator('[data-use-url$="/coins"]:visible').first)
    page.locator('.roll-win input[name="amount"]').first.fill("1")
    page.locator('[data-use-go][data-to="spend"]').first.click()
    t.expect("the gp spent again", lambda: gp(record(sheet)) == gp(start), SLOW)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")


def add_item(t: Table, seat: str = "player2") -> None:
    """Add item (the player, in the item browser): a Torch bought for 1 sp from the purse lands on the sheet and the
    coins go down by 1 sp; then the Torch is taken off and the purse put back as it was."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    cid, start = cid_of(page), record(sheet)
    browse(page, cid, "Torch")
    page.fill("[data-ib-pay]", "1 sp")
    page.click("[data-ib-go]", timeout=8000)
    t.expect("a Torch reaches the sheet", lambda: how_many(record(sheet), "Torch") == how_many(start, "Torch") + 1, SLOW)
    t.expect("and 1 sp comes off the purse", lambda: worth(record(sheet)) == worth(start) - 10, SLOW)
    page.wait_for_timeout(1500)
    take_off(t, seat, sheet, start, "Torch")
    coins0 = start.get("currencies") or {}
    print("  the purse put back:", sheet.evaluate(TIDYING, [SHEETS[seat], [["PUT", f"inventory/currency/{w}", {"amount": coins0.get(k) or 0}]
                                                                         for k, w in {"cp": "copper", "sp": "silver", "ep": "electrum", "gp": "gold", "pp": "platinum"}.items()]]), flush=True)


def wild_shape(t: Table, seat: str = "player4") -> None:
    """Wild Shape (Levi, Druid 6): Shift into a form on Battle spends a Wild Shape use and gives the form's Temporary Hit
    Points on D&D Beyond, and Battle shows the form; Undo puts back the use, the Temporary Hit Points and the form."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    if page.locator(".ws-form").count():  # (left in a form by something earlier, Nov 5: the run's Undo then put that form
        go(page, page.locator('.ws-chip[data-use-url$="/wild-shape"]:visible').first)  # back, and the runs after it failed;
        page.locator('[data-use-go][data-to="leave"]').first.click(timeout=8000)  # Leave is askdnd's alone)
        page.goto(page.url, wait_until="domcontentloaded")
        print("  was in a form: left it first", flush=True)
    before = record(sheet)
    form = page.locator('.ws-chip[data-use-url*="wild-shape?form="]:visible').first
    name = form.inner_text().strip()
    print("  form:", name, flush=True)
    go(page, form)
    page.locator('[data-use-go][data-to="shift"]').first.click(timeout=8000)
    changed(t, sheet, before, "the use and the Temporary Hit Points land on D&D Beyond")
    t.expect("both of them", lambda: len(changes(before, record(sheet))) >= 2, SLOW)
    t.expect(f"Battle is drawn as the {name}", lambda: page.locator(".ws-form").count() > 0, 15)
    if not undo(page):
        page.goto(page.url, wait_until="domcontentloaded")
        go(page, page.locator('.ws-chip[data-use-url$="/wild-shape"]:visible').first)  # (Normal: Leave)
        page.locator('[data-use-go][data-to="leave"]').first.click(timeout=8000)
        print("  put back on D&D Beyond:", sheet.evaluate(TIDYING, [SHEETS[seat], [
            ["PUT", "life/hp/damage-taken", {"removedHitPoints": before.get("removedHitPoints") or 0, "temporaryHitPoints": before.get("temporaryHitPoints") or 0}]]]), flush=True)
        go(page, page.locator('.ws-label .pips-go:visible').first)
        page.locator('[data-use-go][data-to="back"]').first.click(timeout=15000)
    undone(t, sheet, before, "Undo puts the use and the Temporary Hit Points back on D&D Beyond")
    page.goto(page.url, wait_until="domcontentloaded")
    t.expect("and Battle is the druid again", lambda: page.locator(".ws-form").count() == 0, 15)


def pact_used(d: dict) -> int:
    return sum(x.get("used") or 0 for x in d.get("pactMagic") or [])


def slots_used(d: dict) -> int:
    return sum(x.get("used") or 0 for x in d.get("spellSlots") or [])


def ws_used(d: dict) -> int:
    """Wild Shape's uses spent, on D&D Beyond's sheet."""
    return sum((a.get("limitedUse") or {}).get("numberUsed") or 0 for a in (d.get("actions") or {}).get("class") or [] if a.get("name") == "Wild Shape")


def cast_as(page: Page, spell: str, kind: str) -> None:
    """The Spell Book, then `spell` cast with a slot of this kind ("pact" or "slot"), the lowest one."""
    page.locator(".spellbook-btn").first.click(timeout=8000)
    go(page, page.locator(f'.ls-row[data-ref="spell:{spell}"] [data-use-url*="/cast?"]').first)
    ways = page.locator('select[name="way"] option')
    values = [ways.nth(i).get_attribute("value") for i in range(ways.count())]
    print(f"  {spell} can be cast:", page.locator('select[name="way"] option').all_inner_texts(), flush=True)
    page.locator('select[name="way"]').first.select_option(next(v for v in values if v.startswith(kind + ":")))
    page.locator("[data-use-go]").first.click(timeout=8000)


def give_back(page: Page, field: str) -> None:
    """A slot or a use given back from its count window (Use one and Give one back): "pact", "slot", or "ws" for Wild
    Shape's pips."""
    page.goto(page.url, wait_until="domcontentloaded")
    go(page, page.locator(".ws-label .pips-go:visible" if field == "ws" else f'[data-use-url*="field={field}"]:visible').first)
    page.locator('[data-use-go][data-to="back"]').first.click(timeout=15000)
    page.wait_for_timeout(1500)


def pact_cast(t: Table, seat: str = "player4") -> None:
    """Pact Magic (Levi, Warlock 2): Hex cast with a Pact slot spends the Pact slot on D&D Beyond, not a Druid slot; Undo
    gives it back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    cast_as(page, "Hex", "pact")
    t.expect("a Pact slot is spent on D&D Beyond", lambda: pact_used(record(sheet)) == pact_used(before) + 1, SLOW)
    t.expect("and no Druid slot", lambda: slots_used(record(sheet)) == slots_used(before), 5)
    if not undo(page):
        give_back(page, "pact")
    undone(t, sheet, before, "Undo gives the Pact slot back on D&D Beyond")


def cross_cast(t: Table, seat: str = "player4") -> None:
    """Two kinds of spellcasting (2024 multiclassing): Levi's Druid spell Entangle cast with a Pact slot spends the Pact
    slot, and the Warlock's Hex cast with a Druid slot spends the Druid slot; both put back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    cast_as(page, "Entangle", "pact")
    t.expect("Entangle spends a Pact slot on D&D Beyond", lambda: pact_used(record(sheet)) == pact_used(before) + 1, SLOW)
    t.expect("and no Druid slot", lambda: slots_used(record(sheet)) == slots_used(before), 5)
    if not undo(page):
        give_back(page, "pact")
    undone(t, sheet, before, "and Undo gives it back", SLOW)
    page.goto(page.url, wait_until="domcontentloaded")
    cast_as(page, "Hex", "slot")
    t.expect("Hex spends a Druid slot on D&D Beyond", lambda: slots_used(record(sheet)) == slots_used(before) + 1, SLOW)
    t.expect("and no Pact slot", lambda: pact_used(record(sheet)) == pact_used(before), 5)
    if not undo(page):
        give_back(page, "slot")
    undone(t, sheet, before, "and Undo gives it back", SLOW)


def short_rest(t: Table, seat: str = "player4") -> None:
    """A Short Rest for a Druid / Warlock: the Pact slot and one Wild Shape use come back on D&D Beyond, a Druid slot
    doesn't (2024 rules). The Druid slot is then given back by hand."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    cast_as(page, "Hex", "pact")
    t.expect("a Pact slot spent", lambda: pact_used(record(sheet)) == pact_used(before) + 1, SLOW)
    page.wait_for_timeout(1500)
    page.goto(page.url, wait_until="domcontentloaded")
    cast_as(page, "Entangle", "slot")
    t.expect("a Druid slot spent", lambda: slots_used(record(sheet)) == slots_used(before) + 1, SLOW)
    page.wait_for_timeout(1500)
    page.goto(page.url, wait_until="domcontentloaded")
    go(page, page.locator(".ws-label .pips-go:visible").first)
    page.locator('[data-use-go][data-to="use"]').first.click(timeout=8000)
    t.expect("a Wild Shape use spent", lambda: ws_used(record(sheet)) == ws_used(before) + 1, SLOW)
    page.wait_for_timeout(1500)
    page.goto(page.url, wait_until="domcontentloaded")
    rest_window(page, "short")
    page.locator("[data-use-go]").first.click(timeout=8000)
    t.expect("the Short Rest gives the Pact slot back on D&D Beyond", lambda: pact_used(record(sheet)) == pact_used(before), SLOW)
    t.expect("and the Wild Shape use", lambda: ws_used(record(sheet)) == ws_used(before), 15)
    t.expect("but not the Druid slot", lambda: slots_used(record(sheet)) == slots_used(before) + 1, 5)
    page.wait_for_timeout(2500)
    page.keyboard.press("Escape")
    give_back(page, "slot")
    undone(t, sheet, before, "the Druid slot given back: the sheet as it was", SLOW)


def in_form(t: Table, seat: str = "player4") -> None:
    """In a form (Levi, Druid 6, no Beast Spells): Cast says the form can't cast spells, and Leave ends the form and keeps
    the leftover Temporary Hit Points on D&D Beyond. Then the use and the Temporary Hit Points are put back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    go(page, page.locator('.ws-chip[data-use-url*="wild-shape?form="]:visible').first)
    page.locator('[data-use-go][data-to="shift"]').first.click(timeout=8000)
    t.expect("the form's Temporary Hit Points on D&D Beyond", lambda: (record(sheet).get("temporaryHitPoints") or 0) > (before.get("temporaryHitPoints") or 0), SLOW)
    page.wait_for_timeout(2500)
    page.goto(page.url, wait_until="domcontentloaded")
    temp = record(sheet).get("temporaryHitPoints")
    page.locator(".spellbook-btn").first.click(timeout=8000)
    go(page, page.locator('.ls-row[data-ref="spell:Entangle"] [data-use-url*="/cast?"]').first)
    t.expect("Cast says the form can't cast spells", lambda: "can't cast spells" in page.locator(".roll-win .shift-warn").first.inner_text(), 10)
    page.locator(".rp-x").first.click()
    page.goto(page.url, wait_until="domcontentloaded")
    go(page, page.locator('.ws-chip[data-use-url$="/wild-shape"]:visible').first)
    page.locator('[data-use-go][data-to="leave"]').first.click(timeout=8000)
    page.wait_for_timeout(2500)
    page.goto(page.url, wait_until="domcontentloaded")
    t.expect("Leave ends the form", lambda: page.locator(".ws-form").count() == 0, 15)
    t.expect("and the Temporary Hit Points stay on D&D Beyond", lambda: record(sheet).get("temporaryHitPoints") == temp, 10)
    print("  put back on D&D Beyond:", sheet.evaluate(TIDYING, [SHEETS[seat], [
        ["PUT", "life/hp/damage-taken", {"removedHitPoints": before.get("removedHitPoints") or 0, "temporaryHitPoints": before.get("temporaryHitPoints") or 0}]]]), flush=True)
    give_back(page, "ws")
    undone(t, sheet, before, "the use and the Temporary Hit Points put back", SLOW)


def creature_hp(t: Table, seat: str = "player3") -> None:
    """Your creatures, slice 2 (extension 0.10.0): Vi's Homunculus. Set D&D Beyond's maximum to the rule's, then damage
    and healing from askdnd land on its Extras; then its damage and maximum are put back as they were."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    c = next(x for x in before["creatures"] if x.get("groupId") == 12)
    mine = lambda d: next(x for x in d["creatures"] if x["id"] == c["id"])
    most = lambda d: next((v["value"] for v in d.get("characterValues") or [] if v.get("typeId") == 43 and str(v.get("valueId")) == str(c["id"])), None)
    page.goto(page.url.split("?")[0] + f"?creature={c['id']}", wait_until="domcontentloaded")
    fix = page.locator('button[hx-post$="/max"]')
    if fix.count():
        fix.first.click(timeout=8000)
        t.expect("D&D Beyond's maximum is set to the rule's", lambda: (most(record(sheet)) or 0) > 1, SLOW)
        page.wait_for_timeout(1500)
        page.goto(page.url, wait_until="domcontentloaded")
    waiting = page.locator(".cr-fix b")
    if waiting.count() >= 2:  # (Nov 5: askdnd sets the rule's maximum on D&D Beyond once; one taken off since, it leaves,
        rule = int(waiting.nth(1).inner_text())  # and − and + wait: the run starts with it there, as askdnd keeps it)
        key = {"typeId": 43, "valueId": str(c["id"]), "valueTypeId": str(c["entityTypeId"]), "contextId": None, "contextTypeId": None}
        print("  its maximum set to the rule's first:", sheet.evaluate(TIDYING, [SHEETS[seat], [["PUT", "custom/value", {**key, "value": rule, "notes": None}]]]), flush=True)
        t.expect("D&D Beyond's maximum is the rule's", lambda: most(record(sheet)) == rule, SLOW)
        sheet.reload(wait_until="domcontentloaded")  # (askdnd reads the sheet as it opens: its copy has the maximum then)
        t.expect("askdnd's copy has it: − and + are back", lambda: page.goto(page.url, wait_until="domcontentloaded") and page.locator(".cr-fix").count() == 0, SLOW)
        before = record(sheet)
    for to, want in (("damage", (c.get("removedHitPoints") or 0) + 3), ("heal", c.get("removedHitPoints") or 0)):
        page.locator(".cr-hp-pop > summary").first.click(timeout=8000)
        page.fill(".cr-hp-form input[name=amount]", "3")
        page.locator(f'.cr-hp-form button[value="{to}"]').click(timeout=8000)
        t.expect(f"its {to} lands on D&D Beyond", lambda w=want: (mine(record(sheet)).get("removedHitPoints") or 0) == w, SLOW)
        page.wait_for_timeout(1500)
        page.goto(page.url, wait_until="domcontentloaded")
    if most(before) != most(record(sheet)):
        key = {"typeId": 43, "valueId": str(c["id"]), "valueTypeId": str(c["entityTypeId"]), "contextId": None, "contextTypeId": None}
        print("  its maximum put back:", sheet.evaluate(TIDYING, [SHEETS[seat], [["DELETE", "custom/value", key]] if not most(before)
                                                                 else [["PUT", "custom/value", {**key, "value": most(before), "notes": None}]]]), flush=True)


def creature_of(d: dict, cid: int) -> dict:
    return next(c for c in d["creatures"] if c["id"] == cid)


def familiar(t: Table, seat: str = "player4") -> None:
    """A familiar kept in step (Nov 4, extension 0.11.0; Levi's Owl): Find Familiar cast in askdnd as a Ritual, named Pip
    and made Fey, switches the Owl on on D&D Beyond with its creature type and name; sent to the pocket dimension it's
    switched off, brought back it's on, dismissed it's off; then D&D Beyond is put back as found. askdnd keeps the Owl
    as dismissed, which the next cast brings back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    owl = next(c for c in before["creatures"] if c["groupId"] == 2)
    oid = owl["id"]
    page.locator(".spellbook-btn").first.click(timeout=8000)
    go(page, page.locator('.ls-row[data-ref="spell:Find Familiar"] [data-use-url*="/cast?"]').first)
    page.locator('select[name="way"]').first.select_option("ritual")
    page.locator(f'input[name="familiar"][value="{oid}"]').check()
    page.locator('input[name="kind"][value="Fey"]').check()
    page.locator('input[name="familiar_name"]').fill("Pip")
    page.locator("[data-use-go]").first.click(timeout=8000)
    t.expect("the Owl is switched on on D&D Beyond", lambda: creature_of(record(sheet), oid)["isActive"], SLOW)
    t.expect("as Fey (its creature type)", lambda: any(v.get("typeId") == 44 and str(v.get("valueId")) == str(oid) and v.get("value") == 8
                                                        for v in record(sheet).get("characterValues") or []), SLOW)
    t.expect("named Pip", lambda: creature_of(record(sheet), oid)["name"] == "Pip", SLOW)
    page.wait_for_timeout(1500)
    page.goto(f"{page.url.split('?')[0]}?creature={oid}", wait_until="domcontentloaded")
    page.locator('button:has-text("Send to the pocket dimension")').first.click(timeout=8000)
    t.expect("sent to the pocket dimension, it's switched off", lambda: not creature_of(record(sheet), oid)["isActive"], SLOW)
    page.wait_for_timeout(1500)
    page.locator('button:has-text("Bring it back")').first.click(timeout=8000)
    t.expect("brought back, it's on again", lambda: creature_of(record(sheet), oid)["isActive"], SLOW)
    page.wait_for_timeout(1500)
    page.locator('.cr-forever > summary').first.click(timeout=8000)
    page.locator('.cr-forever-pop button').first.click(timeout=8000)
    t.expect("dismissed, it's switched off", lambda: not creature_of(record(sheet), oid)["isActive"], SLOW)
    key = {"typeId": 44, "valueId": str(oid), "valueTypeId": str(owl["entityTypeId"]), "contextId": None, "contextTypeId": None}
    print("  put back on D&D Beyond:", sheet.evaluate(TIDYING, [SHEETS[seat], [
        ["DELETE", "custom/value", key], ["PUT", "creature", {"id": oid, "name": owl["name"], "description": owl["description"], "groupId": owl["groupId"]}],
        ["PUT", "creature/status", {"id": oid, "isActive": owl["isActive"]}]]]), flush=True)


def wild_companion(t: Table, seat: str = "player4") -> None:
    """Wild Companion (Nov 5, Your creatures' last live run; Levi is a Druid): Find Familiar cast from a Wild Shape use
    spends the use on D&D Beyond and switches the Owl on, always Fey; Undo gives the use back and switches it off; then
    D&D Beyond is put back as found."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    connects(t, page)
    before = record(sheet)
    owl = next(c for c in before["creatures"] if c["groupId"] == 2)
    oid, used = owl["id"], ws_used(before)
    page.locator(".spellbook-btn").first.click(timeout=8000)
    go(page, page.locator('.ls-row[data-ref="spell:Find Familiar"] [data-use-url*="/cast?"]').first)
    page.locator('select[name="way"]').first.select_option("wild")
    page.locator(f'input[name="familiar"][value="{oid}"]').check()
    page.locator("[data-use-go]").first.click(timeout=8000)
    t.expect("a Wild Shape use is spent on D&D Beyond", lambda: ws_used(record(sheet)) == used + 1, SLOW)
    t.expect("and the Owl is switched on, as Fey", lambda: creature_of(record(sheet), oid)["isActive"] and any(
        v.get("typeId") == 44 and str(v.get("valueId")) == str(oid) and v.get("value") == 8 for v in record(sheet).get("characterValues") or []), SLOW)
    page.wait_for_timeout(1500)
    if undo(page):
        t.expect("Undo gives the Wild Shape use back", lambda: ws_used(record(sheet)) == used, SLOW)
    key = {"typeId": 44, "valueId": str(oid), "valueTypeId": str(owl["entityTypeId"]), "contextId": None, "contextTypeId": None}
    tidy = [["PUT", "creature", {"id": oid, "name": owl["name"], "description": owl["description"], "groupId": owl["groupId"]}],
            ["PUT", "creature/status", {"id": oid, "isActive": owl["isActive"]}]]  # (the familiar's name goes with it to a new form)
    if not any(v.get("typeId") == 44 and str(v.get("valueId")) == str(oid) for v in before.get("characterValues") or []):
        tidy.append(["DELETE", "custom/value", key])
    print("  put back on D&D Beyond:", sheet.evaluate(TIDYING, [SHEETS[seat], tidy]), flush=True)


def dm_backup(t: Table, seat: str = "player2") -> None:
    """DM Backup (extension 0.9.8): with a player's sheet closed, the DM's browser with a D&D Beyond page open makes
    askdnd's change on it; the pill says so, then Connected again once the sheet is back."""
    page = t.battle(seat)
    for x in [p for p in t.contexts[seat].pages if "dndbeyond.com/characters/" in p.url]:
        x.close()
    ddb = t.page("dm", "https://www.dndbeyond.com/campaigns/8224496")
    t.expect("the player's pill says through the DM", lambda: "Through the DM" in pill(page), 60)
    start = record_of(ddb, SHEETS[seat])["removedHitPoints"]
    change_hp(page, 0, 1)
    t.expect("the DM's browser makes the hit on D&D Beyond", lambda: record_of(ddb, SHEETS[seat])["removedHitPoints"] == start + 1, SLOW)
    page.wait_for_timeout(1500)
    change_hp(page, 1, 1)
    t.expect("and the healing", lambda: record_of(ddb, SHEETS[seat])["removedHitPoints"] == start, SLOW)
    t.sheet(seat)
    t.expect("the sheet open again: Connected", lambda: "Connected" in pill(page), 40)


CANT = "can't be reached"


def unreachable(t: Table, seat: str = "player2") -> None:
    """What you shouldn't be able to do (Brett, Nov 5): with no browser able to reach the sheet (its own closed, the DM's
    D&D Beyond pages closed), each change for D&D Beyond says so where it starts and offers no button that would be
    refused; one sent anyway is refused, and nothing reaches D&D Beyond. askdnd's own parts (effects) still work."""
    page = t.battle(seat)
    for ctx in (t.contexts[seat], t.contexts["dm"]):
        for x in [x for x in ctx.pages if "dndbeyond.com/" in x.url]:
            x.close()
    ddb = t.page(seat, "https://www.dndbeyond.com/my-characters")  # (reads the record; a player's page carries nothing)
    start = record_of(ddb, SHEETS[seat])
    cid = cid_of(page)
    if not t.expect("nothing can reach the sheet", lambda: not any(x in pill(page) for x in ("Connected", "Through the DM")), 150):
        raise RuntimeError("the sheet can still be reached: the pill says " + repr(pill(page)) + " (a sheet or the DM's D&D Beyond open in another browser?)")
    print("  pill:", pill(page), flush=True)
    page.goto(f"https://beta.askdnd.ai/characters/{cid}/battle", wait_until="domcontentloaded")
    page.locator("details.cond-add > summary").click(timeout=8000)
    t.expect("+ Condition says so at the top", lambda: CANT in page.locator("details.cond-add .unreached").first.inner_text(timeout=3000), 8)
    chips = page.locator("details.cond-add .ls-chip")
    t.expect("D&D Beyond's conditions can't be pressed, askdnd's effects can",
             lambda: chips.first.is_disabled() and page.locator("details.cond-add .ls-chip:not([disabled])").count() > 0, 5)
    page.goto(f"https://beta.askdnd.ai/characters/{cid}/battle", wait_until="domcontentloaded")
    mode(page, "damage")
    t.expect("the Damage window says so, and its button is off",
             lambda: CANT in page.locator(".peek.open .hp-blocked").first.inner_text(timeout=3000)
             and page.locator('.peek.open .hp-form button[type="submit"]').first.is_disabled(), 10)
    page.keyboard.press("Escape")
    page.goto(f"https://beta.askdnd.ai/characters/{cid}/battle", wait_until="domcontentloaded")
    page.locator('[data-panel-url$="/vital/hp"]').first.click()
    page.locator('[data-use-url$="/rest?kind=short"]').first.click(timeout=8000)  # (no Take a Short Rest to wait for: that's the point)
    page.wait_for_selector(".use-said:visible", timeout=8000)
    t.expect("the Rest window says so, with no Take a Short Rest",
             lambda: CANT in page.locator(".use-said:visible").first.inner_text(timeout=3000) and page.locator("[data-use-go]:visible").count() == 0, 10)
    page.keyboard.press("Escape")
    sheet_tab(page, cid, "t-items")
    page.locator('[data-panel-url*="ref=item%3A"]:visible').first.click(timeout=8000)
    t.expect("an item's panel says so instead of Equip and the rest",
             lambda: CANT in page.locator(".peek.open .unreached").first.inner_text(timeout=3000)
             and page.locator('.peek.open button:text-is("Equip"), .peek.open button:text-is("Unequip")').count() == 0, 10)
    page.keyboard.press("Escape")
    for what, url, top in (("the item browser", "items/browse", "data-ib-said"), ("Prepare spells", "spells/prepare", 'class="use-said"')):
        html = unescape(page.evaluate("u => fetch(u).then(r => r.text())", f"/characters/{cid}/{url}"))  # (its "can&#39;t")
        t.expect(f"{what} says so at the top", lambda: CANT in html and html.index('class="unreached"') < html.index(top), 1)
    status = page.evaluate("""cid => fetch(`/characters/${cid}/conditions`, {method: 'POST', headers: {'HX-Request': 'true'},
        body: new URLSearchParams({name: 'Poisoned', level: '1'})}).then(r => r.status)""", cid)
    t.expect("a condition sent anyway is refused", lambda: status == 409, 1)
    page.wait_for_timeout(5000)
    after = record_of(ddb, SHEETS[seat])
    t.expect("and nothing reached D&D Beyond", lambda: after["conditions"] == start["conditions"] and after["removedHitPoints"] == start["removedHitPoints"], 1)
    t.sheet(seat)
    t.expect("the sheet open again: Connected", lambda: "Connected" in pill(page), 40)
    page.goto(f"https://beta.askdnd.ai/characters/{cid}/battle", wait_until="domcontentloaded")
    page.locator("details.cond-add > summary").click(timeout=8000)
    t.expect("and + Condition offers them again", lambda: page.locator("details.cond-add .unreached").count() == 0 and not chips.first.is_disabled(), 10)


# The twins and the classes nobody at the table plays (Brett, Nov 5; docs/testing-setup.md): each on its seat's D&D
# Beyond account, in VTT test, played there by its seat's account. run name: (seat, D&D Beyond id, its name in askdnd,
# what it spends: a resource on Battle's Resources row, "" for none). No Name's and Trah's twins are one line each.
TWINS = {
    "cole-twin": ("player2", 173216268, "Cole (twin)", "Focus"),
    "test-ranger": ("player2", 173222995, "Test Ranger", "Hunter"),  # (Favored Enemy's free casts: "Hunter's Mark" on Battle)
    "test-bard": ("player3", 173222716, "Test Bard", "Bardic Inspiration"),
    "test-rogue": ("player3", 173222824, "Test Rogue", ""),
    "big-c-twin": ("player4", 173220725, "Big C (twin)", "Channel Divinity"),
    "test-barbarian": ("player4", 173222366, "Test Barbarian", "Rage"),
    "test-fighter": ("player4", 173222510, "Test Fighter", "Second Wind"),
}


# Each twin's real character at Brett's table (its public D&D Beyond copy, read as askdnd reads it; never driven)
REAL = {"cole-twin": 75423618, "big-c-twin": 76415207}


def build(ddb: int) -> list[str]:
    """A character's classes, levels and subclasses from D&D Beyond's public copy: ["Druid 6 (Circle of the Moon)", …]."""
    import urllib.request

    req = urllib.request.Request(f"https://character-service.dndbeyond.com/character/v5/character/{ddb}", headers={"User-Agent": "askdnd-live-test"})
    with urllib.request.urlopen(req, timeout=20) as r:
        d = json.load(r)["data"]
    return sorted(f"{c['definition']['name']} {c['level']}" + (f" ({c['subclassDefinition']['name']})" if c.get("subclassDefinition") else "")
                  for c in d.get("classes") or [])


def twins_level(t: Table) -> None:
    """Each twin still matches its real character's classes and levels (Brett, Nov 5: a nightly check that says when a
    twin needs a level-up). A miss names what to change on the twin's D&D Beyond sheet."""
    for key, real in REAL.items():
        name = TWINS[key][2]
        mine, theirs = build(TWINS[key][1]), build(real)
        if not t.expect(f"{name} matches its real character", lambda: mine == theirs, 1):
            print(f"   {name} is {', '.join(mine)}; the real one is {', '.join(theirs)}: level up the twin on D&D Beyond", flush=True)


def twin(t: Table, key: str) -> None:
    """One of the twins or class sheets, as its player plays it: Battle names its classes as D&D Beyond does; its own
    resource (Rage, Second Wind, Bardic Inspiration…) spent in askdnd is spent on D&D Beyond and given back; and a
    spellcaster's slot is spent by Cast and given back by Undo."""
    seat, ddb, name, res = TWINS[key]
    sheet = t.sheet(seat, ddb=ddb)
    page = t.battle_of(seat, name)
    connects(t, page)
    before = record(sheet)
    classes = [c["definition"]["name"] for c in before.get("classes") or []]
    print("  ", name, "·", ", ".join(f"{c['definition']['name']} {c['level']}" for c in before.get("classes") or []), flush=True)
    t.expect("Battle names its classes as D&D Beyond does", lambda: all(c in page.locator("#char-sub").inner_text() for c in classes), 8)
    if res:
        button = page.locator(f'.res-go[data-use-url*="/count"]:has-text("{res}")')
        if not t.expect(f"{res} is on Battle's Resources row", lambda: button.count() > 0, 8):
            print("   resources:", page.locator('.res-go[data-use-url*="/count"]').all_inner_texts(), flush=True)
        else:
            go(page, button.first)
            page.locator('[data-use-go][data-to="use"]').first.click()
            changed(t, sheet, before, f"{res}: one is spent on D&D Beyond")
            page.wait_for_timeout(1500)
            page.keyboard.press("Escape")
            go(page, button.first)
            page.locator('[data-use-go][data-to="back"]').first.click()
            undone(t, sheet, before, f"{res}: given back on D&D Beyond")
            page.wait_for_timeout(1500)
            page.keyboard.press("Escape")
    page.goto(page.url, wait_until="domcontentloaded")
    if page.locator(".spellbook-btn").count():  # (a spellcaster: the first spell with a slot to spend)
        spell_window(page)
        if not page.locator('select[name="way"] option').count():
            print("   no spell with a slot to spend", flush=True)
            return
        print("   spell:", page.locator(".rw-title").first.inner_text(), flush=True)
        page.locator("[data-use-go]").first.click()
        changed(t, sheet, before, "Cast: the slot is spent on D&D Beyond")
        if undo(page):
            undone(t, sheet, before, "Undo gives the slot back on D&D Beyond")


VTT = "https://www.dndbeyond.com/games/8224496"
EXTENSION = "obpgemimnhngpcckodjkcihiahoaefpl"  # (the askdnd bridge from the Chrome Web Store, in every seat)


def open_tracker(vtt: Page) -> None:
    """The DM's VTT combat sidebar, opened by the button at the top left when it's closed."""
    if not vtt.locator("[data-testid=initiative-input]").count() or not vtt.locator("[data-testid=initiative-input]").first.is_visible():
        i = vtt.evaluate("""[...document.querySelectorAll('button')].findIndex(b => { const r = b.getBoundingClientRect(); return r.y < 60 && r.x < 120; })""")
        if i >= 0 and "Close Sidebar" not in (vtt.locator("button").nth(i).get_attribute("aria-label") or ""):
            vtt.locator("button").nth(i).click()
            vtt.wait_for_timeout(1200)


def end_combat(vtt: Page) -> None:
    """The tracker's ^ shows End Combat; a Confirm, where D&D Beyond asks one, is pressed too."""
    vtt.get_by_test_id("show-end-combat-button").click()
    vtt.get_by_role("button", name="End Combat", exact=False).last.click()
    try:
        vtt.get_by_role("button", name="Confirm").click(timeout=3000)
    except Exception:
        pass
    vtt.wait_for_timeout(2000)


def sidebar(vtt: Page) -> dict[str, float]:
    """The DM's VTT combat sidebar: each one's first name and its initiative number."""
    open_tracker(vtt)
    rows = vtt.evaluate("""[...document.querySelectorAll('[data-testid=initiative-input]')].map(e => {
        let r = e; for (let k = 0; k < 10 && r; k++) { r = r.parentElement; if (r.querySelector('img[alt]')) break; }
        const a = r && r.querySelector('img[alt]'); return [a ? a.alt.split(' ')[0] : '?', e.value]; })""")
    return {name: float(v) for name, v in rows if v not in ("", None)}


def initiative(t: Table, seat: str = "player4") -> None:
    """Initiative from askdnd (Nov 4, extension 0.12.0; Levi, VTT test with the Labs switch on): the DM's Add all
    tokens, then Levi's Initiative rolled in askdnd fills in his number in the VTT's sidebar (through the Game Log, as a
    roll from the sheet does); the DM's change in askdnd reaches the VTT through the DM's open VTT page; after Start
    Combat a roll changes nothing. The encounter is left as found (in combat or not).
    It starts as after Chrome restarts (extension 0.12.1, Nov 5): the extension's memory of askdnd cleared and the VTT
    opened before askdnd, which 0.12.0 never heard until the VTT was reloaded."""
    ctx = t.contexts["dm"]
    for page in [x for x in ctx.pages if x.url.startswith(("https://beta.askdnd.ai", VTT))]:
        page.close()
    for worker in [w for w in ctx.service_workers if EXTENSION in w.url]:
        worker.evaluate("chrome.storage.session.clear()")  # (where askdnd is and its key: kept only until Chrome restarts)
    vtt = t.page("dm", VTT)
    vtt.wait_for_timeout(15000)
    party = t.page("dm", f"{BETA}/party")  # (askdnd second: once it connects, the extension tells the open VTT)
    for sel in ('[aria-label="Close"]', 'button:has-text("Hide until next update")'):
        try:
            vtt.locator(sel).first.click(timeout=2000)
        except Exception:
            pass
    open_tracker(vtt)  # (End Combat is on the page while the tracker is closed, but can't be pressed)
    end = vtt.get_by_test_id("show-end-combat-button")
    fighting = end.count() > 0 and end.first.is_visible()
    if fighting:
        end_combat(vtt)
    add = vtt.get_by_role("button", name="Add all tokens")
    if add.count():  # (gone once every token is in the encounter)
        add.click()
    t.expect("the DM's VTT lists Levi waiting", lambda: "Levi" in sidebar(vtt), 20)
    party.reload()
    t.expect("askdnd hears who's waiting: Roll for Initiative", lambda: "Roll for Initiative" in " ".join(party.locator(".fight-band").all_text_contents()), 30)
    page = t.battle(seat)
    connects(t, page)
    page.click('[data-roll="check"][data-label="Initiative"]', modifiers=["Shift"])
    page.wait_for_timeout(2500)
    page.keyboard.press("Escape")
    total = float(page.locator("#roll-log > li .roll-total").first.text_content())
    t.expect(f"Levi's {total:g} fills in the VTT's sidebar", lambda: sidebar(vtt).get("Levi") == total, SLOW)
    party.goto(party.url, wait_until="domcontentloaded")
    key = party.locator('tr[data-ft-name^="Levi"]').first.get_attribute("data-ft-key")
    party.evaluate("k => fetch('/fight/initiative', {method: 'POST', body: new URLSearchParams({key: k, to: '17.5'}), headers: {'X-Requested-With': 'fetch'}})", key)
    t.expect("the DM's change in askdnd reaches the VTT", lambda: sidebar(vtt).get("Levi") == 17.5, SLOW)
    vtt.get_by_role("button", name="Start Combat").click()
    vtt.wait_for_timeout(2000)
    page.click('[data-roll="check"][data-label="Initiative"]', modifiers=["Shift"])
    page.wait_for_timeout(8000)
    page.keyboard.press("Escape")
    t.expect("after Start Combat a roll changes nothing", lambda: sidebar(vtt).get("Levi") == 17.5, 1)
    if not fighting:  # (as found)
        end_combat(vtt)


RUNS = {"closed-sheet": closed_sheet, "game-log": game_log, "close-after-roll": close_after_roll, "hit-points": hit_points, "condition": condition,
        "cast": cast, "resource": resource, "coins": coins, "rests": rests, "temp-hp": temp_hp, "death-saves": death_saves,
        "inspiration": inspiration, "exhaustion": exhaustion, "inventory": inventory, "prepare": prepare, "give": give,
        "loot": loot, "add-item": add_item, "dm-backup": dm_backup, "wild-shape": wild_shape,
        "pact-cast": pact_cast, "cross-cast": cross_cast, "short-rest": short_rest, "in-form": in_form, "creature-hp": creature_hp,
        "familiar": familiar, "initiative": initiative, "unreachable": unreachable,
        "wild-companion": wild_companion}


def _twin_run(key: str):
    def run(t: Table, seat: str = TWINS[key][0]) -> None:  # (its seat, for the setup check and tidying)
        twin(t, key)
    run.__doc__ = f"{TWINS[key][2]}: " + (twin.__doc__ or "")
    return run


RUNS |= {key: _twin_run(key) for key in TWINS} | {"twins-level": twins_level}
# Runs about the player's own open sheet itself (its pill, its Game Log, the DM stepping in when it closes): --via-dm leaves them out
SHEET_ONLY = {"closed-sheet", "game-log", "close-after-roll", "dm-backup", "initiative", "unreachable"}  # (unreachable closes every way in; initiative: a roll reaches the VTT through the sheet's own Game Log)
# What a run may leave changed on a sheet: D&D Beyond's own bookkeeping, and the inventory run's stock once it's there
# Runs left out of part 1 (and the nightly) until the seats have what they need: named, they run
WAITING: set[str] = set()
KEPT = ("dateModified", "providedFrom", "readonlyUrl", "definition", "inventory", "campaign", "decorations")


def as_found(t: Table, before: dict) -> None:
    """Each test sheet is back as part 1 found it: what a run changes, it puts back (a miss here is a run that didn't)."""
    for seat, was in before.items():
        sheet = t.sheet(seat)
        left = lambda: changes({k: v for k, v in was.items() if k not in KEPT}, {k: v for k, v in record(sheet).items() if k not in KEPT})
        if not t.expect(f"{seat}'s sheet is back as found", lambda: not left(), 20):  # (D&D Beyond can serve an older copy for a moment)
            print("  still changed:", show(left()), flush=True)


def report(missed: list[str], ran: list[str], log: str, via_dm: bool = False, flaky: list[str] = (), deployed: str = "") -> None:
    """To Sentry (askdnd-v2), where the app's own errors go and alert Brett: one issue for the live test's misses (an
    error), and one for checks that passed only on a second try (a warning: its count of events says how often)."""
    import os

    import sentry_sdk

    sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], environment="live-test", server_name="mac-mini", default_integrations=False)
    part = f"Live test after deploying {deployed}" if deployed else f"Live test part 1{' through the DM' if via_dm else ''}"
    for whats, kind, level, title in ((missed, "", "error", "missed"), (flaky, "-second-try", "warning", "passed only on a second try")):
        if not whats:
            continue
        with sentry_sdk.new_scope() as scope:
            scope.fingerprint = ["live-test", ("after-deploy" if deployed else "part-1-via-dm" if via_dm else "part-1") + kind]
            scope.set_tag("source", "live-test")
            scope.set_context("live test", {"runs": ", ".join(ran), title: list(whats)[:40], "log": log[-6000:]})
            sentry_sdk.capture_message(f"{part}: {len(whats)} {title} ({whats[0][:120]})", level=level)
    sentry_sdk.flush(10)


class Kept:
    """What a run prints, kept for the report as well as shown."""

    def __init__(self, out):
        self.out, self.text = out, []

    def write(self, text: str) -> int:
        self.text.append(text)
        return self.out.write(text)

    def flush(self) -> None:
        self.out.flush()


# Each test sheet between runs: nothing taken, marked or spent. A run leaves it so, since it puts back what it changes.
TIDYING = """async ([id, ops]) => {
  const t = await fetch('https://auth-service.dndbeyond.com/v1/cobalt-token', {method: 'POST', credentials: 'include'});
  const h = {'Content-Type': 'application/json', Authorization: 'Bearer ' + (await t.json()).token};
  const out = [];
  for (const [method, path, body] of ops)
    out.push((await fetch('https://character-service.dndbeyond.com/character/v5/' + path, {method, headers: h, body: JSON.stringify({characterId: id, ...body})})).status);
  return out;
}"""


def left_over(d: dict) -> list[str]:
    ds = d.get("deathSaves") or {}
    return ([f"{d['removedHitPoints']} Hit Points down"] if d.get("removedHitPoints") else []) + (
        [f"{d['temporaryHitPoints']} Temporary Hit Points"] if d.get("temporaryHitPoints") else []) + (
        ["death save marks"] if ds.get("successCount") or ds.get("failCount") else []) + (
        [f"conditions {[c['id'] for c in d['conditions']]}"] if d.get("conditions") else []) + (
        ["Hit Point Dice spent"] if any(c.get("hitDiceUsed") for c in d["classes"]) else []) + (
        ["spell slots spent"] if any(x.get("used") for x in d.get("spellSlots") or []) else []) + (
        ["Pact slots spent"] if any(x.get("used") for x in d.get("pactMagic") or []) else []) + (
        ["limited uses spent"] if spent(d) else [])


def tidy(t: Table, seat: str, ddb: int | None = None) -> list[str]:
    """What's left over on a seat's sheet, put right on D&D Beyond as the seat's player could on the sheet: hit points,
    death saves, conditions, and (Nov 5: a night's misses spent Levi's Pact slots and Wild Shape uses, and the next
    night's runs failed on them) slots and limited uses. Returns what was left over."""
    sheet = t.sheet(seat, ddb=ddb)
    d = record(sheet)
    found = left_over(d)
    ops = ([["PUT", "life/hp/damage-taken", {"removedHitPoints": 0, "temporaryHitPoints": 0}]] if d.get("removedHitPoints") or d.get("temporaryHitPoints") else []) + (
        [["PUT", "life/death-saves", {"failCount": 0, "successCount": 0}]] if (d.get("deathSaves") or {}).get("failCount") or (d.get("deathSaves") or {}).get("successCount") else []) + [
        ["DELETE", "condition", {"id": c["id"]}] for c in d.get("conditions") or []] + [
        ["PUT", "spell/slots", {f"level{x['level']}": 0}] for x in d.get("spellSlots") or [] if x.get("used")] + [
        ["PUT", "spell/pact-magic", {f"level{x['level']}": 0}] for x in d.get("pactMagic") or [] if x.get("used")] + [
        ["PUT", "action/limited-use", {"id": str(x["id"]), "entityTypeId": str(x.get("entityTypeId")), "uses": 0}]
        for g in d["actions"].values() for x in g or [] if (x.get("limitedUse") or {}).get("numberUsed")]
    if ops:
        print("  put right on D&D Beyond:", "; ".join(found), sheet.evaluate(TIDYING, [ddb or SHEETS[seat], ops]), flush=True)
    return found


def clean_start(t: Table, seat: str) -> None:
    """Part 1 starts on clean sheets. Anything left over (a run before this one that didn't put it back) is a miss, and
    is put right so the runs can start."""
    found = tidy(t, seat)
    t.note(not found, f"{seat}'s sheet starts clean")
    print("PASS" if not found else "FAIL", f"{seat}'s sheet starts clean", "; ".join(found), flush=True)


def seated(t: Table, seats: set[str]) -> tuple[set[str], dict[str, str]]:
    """Setup, before any run (Nov 3: player2's seat had been changed to play another character, and every run on it
    missed): each player's seat plays its test sheet on beta, and every seat has the same extension. A seat that isn't
    set up is a setup miss, said once, and the runs on it are left out instead of each missing for the same reason.
    Returns (the seats that are set up, each seat's extension version)."""
    ready, versions = set(), {}
    for seat in sorted(seats):
        try:
            page = t.battle(seat)
            href = page.get_attribute(".char-name .sheet-open", "href", timeout=10000) or ""
            page.wait_for_function("document.body.dataset.bridgeVersion", timeout=10000)
            versions[seat] = page.evaluate("document.body.dataset.bridgeVersion")
        except Exception as e:
            t.note(False, f"setup: {seat}'s seat opens its character on beta ({type(e).__name__})")
            continue
        if str(SHEETS[seat]) not in href:
            t.note(False, f"setup: {seat}'s seat plays its test sheet {SHEETS[seat]} (it plays {href.rsplit('/', 1)[-1] or 'none'})")
            continue
        ready.add(seat)
    try:  # (the DM's seat makes changes too: through the DM, the loot and the VTT)
        page = t.page("dm", f"{BETA}/party")
        page.wait_for_function("document.body.dataset.bridgeVersion", timeout=10000)
        versions["dm"] = page.evaluate("document.body.dataset.bridgeVersion")
    except Exception as e:
        t.note(False, f"setup: the DM's seat has the extension ({type(e).__name__})")
    if len(set(versions.values())) > 1:
        t.note(False, f"setup: every seat has the same extension ({', '.join(f'{k} {v}' for k, v in sorted(versions.items()))})")
    print("  seats ready:", ", ".join(sorted(ready)) or "none", "· extension", ", ".join(sorted(set(versions.values()))) or "unknown", flush=True)
    return ready, versions


def attempt(t: Table, name: str) -> list[str]:
    """One run, then its sheets tidied: a run that left something behind misses here, and the next run starts clean
    whatever this one did (Nov 5: one run's leftovers made four more miss). Returns its misses."""
    start = len(t.results)
    try:
        RUNS[name](t)
    except Exception as e:  # one run going wrong is a result, and the rest still run
        lines = str(e).splitlines()
        at = next((x.strip() for x in lines if "waiting for" in x), "")  # (what it was waiting for)
        t.note(False, f"stopped with {type(e).__name__}: {lines[0][:120] if lines else ''} {at[:160]}")
        print("FAIL", t.results[-1][1], flush=True)
        try:
            shot = f"logs/stopped-{time.strftime('%Y-%m-%d-%H%M')}-{name}.png"
            t.last.screenshot(path=shot)
            print("  what it was looking at:", shot, flush=True)
        except Exception:
            pass
    for seat, ddb in [(s, None) for s in sorted(used([name]))] + ([(TWINS[name][0], TWINS[name][1])] if name in TWINS else []):
        try:
            left = tidy(t, seat, ddb)
        except Exception as e:
            left = [f"couldn't be read ({type(e).__name__})"]
        if left:
            t.note(False, f"put back {TWINS[name][2] if ddb else seat}'s sheet ({'; '.join(left)})")
    return [what for ok, what in t.results[start:] if ok is False]


def history(t: Table, names: list[str], versions: dict, via_dm: bool, deployed: str = "") -> None:
    """The night's results, one line in logs/results.jsonl on the Mini (scripts/live_results.py reads them): which
    checks pass every night, which only sometimes, and which are getting slower."""
    import os
    from datetime import datetime

    os.makedirs("logs", exist_ok=True)
    with open("logs/results.jsonl", "a") as f:
        f.write(json.dumps({"at": datetime.now().isoformat(timespec="seconds"), "via_dm": via_dm, "after_deploy": deployed or None, "runs": names,
                            "extension": versions, "checks": t.checks}) + "\n")


def used(names: list[str]) -> set[str]:
    """The sheets these runs act on (each run names its seats as defaults)."""
    import inspect

    return {p.default for n in names for p in inspect.signature(RUNS[n]).parameters.values() if p.default in SHEETS}


def main() -> int:
    args = sys.argv[1:]
    to_sentry = "--sentry" in args
    via_dm = "--via-dm" in args
    deployed = next((a.split("=", 1)[1] for a in args if a.startswith("--after-deploy=")), "")  # (real_table_after_deploy.sh)
    names = [a for a in args if not a.startswith("--")] or [n for n in RUNS if n not in WAITING and (not via_dm or n not in SHEET_ONLY)]
    if via_dm and set(names) & SHEET_ONLY:
        print("Not through the DM (they're about the player's own sheet):", ", ".join(sorted(set(names) & SHEET_ONLY)))
        names = [n for n in names if n not in SHEET_ONLY]
    sys.stdout = out = Kept(sys.stdout)
    with sync_playwright() as p:
        t = Table(p, via_dm=via_dm)
        if via_dm:
            print("== through the DM: every sheet closed, the DM's seat on the campaign page", flush=True)
        if "--try-alert" in args:  # (a deliberate miss: checks the way to Sentry, real_table_nightly.sh --try-alert)
            t.note(False, "a deliberate miss, to try the alert (--try-alert)")
        versions: dict = {}
        opened = True
        try:
            ready, versions = seated(t, used(names)) if used(names) else (set(), {})
            names = [n for n in names if used([n]) <= ready]  # (a run on no seat, twins-level, always runs)
            if "inventory" in names:
                stock(t.sheet("player2"))  # (before the sheets are noted: stocking is setting up, not a run's change)
            for seat in sorted(used(names)):
                clean_start(t, seat)
            before = {seat: record(t.sheet(seat)) for seat in SHEETS if seat in used(names)}
        except Exception as e:  # (the seats aren't open, or D&D Beyond can't be reached)
            t.note(False, f"the seats open: {type(e).__name__}: {str(e)[:200]}")
            before, opened = {}, False
        for name in names if opened else []:
            print("==", name, flush=True)
            t.run = name
            first = attempt(t, name)
            if first and "--once" not in args:
                # A second try, on tidied sheets: missed twice is askdnd's (or D&D Beyond changed); passed the second
                # time, the first try's misses are kept as passed only on a second try, which is still worth knowing
                # (timing bugs so far only showed in some runs), but isn't an alarm
                print("  missed: trying it once more", flush=True)
                t.run = f"{name} (again)"
                if not attempt(t, name):
                    t.results = [(None if ok is False and what.startswith(f"{name}: ") else ok, what) for ok, what in t.results]
        if before:
            t.run = "after"
            as_found(t, before)
        history(t, names, versions, via_dm, deployed)
    missed = [what for ok, what in t.results if ok is False]
    flaky = [what for ok, what in t.results if ok is None]
    print(f"{sum(1 for ok, _ in t.results if ok)} of {len(t.results)} as expected", flush=True)
    if flaky:
        print("Passed only on a second try:", *flaky, sep="\n  ", flush=True)
    if (missed or flaky) and to_sentry:
        report(missed, names, "".join(out.text), via_dm, flaky, deployed)
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
