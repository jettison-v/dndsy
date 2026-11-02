"""Real fights on the real D&D Beyond: named runs on the Mac Mini's test seats (docs/testing-setup.md).

On the Mini, never on GitHub: `.venv/bin/python real_table.py [run …]` after `real_table_seats.sh open` (every run when
none is named), and every night at 4:00 through real_table_nightly.sh, which adds `--sentry` (a miss goes to Sentry).
Each run does what a person would do, then says what happened and what it expected, and puts back what it changed;
part 1 starts by checking the test sheets are clean. It only ever touches the test seats in VTT test on beta: Brett's
primary account is not a seat here, and it never signs in to anything.
"""

import json
import sys
import time

from playwright.sync_api import Page, sync_playwright

BETA = "https://beta.askdnd.ai/c/vtt-test"
SEATS = {"dm": 9231, "player2": 9232, "player3": 9233}
SHEETS = {"player2": 172986165, "player3": 172992073}  # Cathartic and the new Vi, never the first Vi or Spurt


class Seats(dict):
    """Each seat's Chrome, reached the first time a run needs it."""

    def __init__(self, p):
        super().__init__()
        self.p = p

    def __missing__(self, seat: str):
        self[seat] = self.p.chromium.connect_over_cdp(f"http://127.0.0.1:{SEATS[seat]}").contexts[0]
        return self[seat]


class Table:
    def __init__(self, p):
        self.contexts = Seats(p)
        self.results: list[tuple[bool, str]] = []
        self.run = ""
        self.last: Page | None = None

    def page(self, seat: str, url: str) -> Page:
        page = next((x for x in self.contexts[seat].pages if x.url.startswith(url)), None) or self.contexts[seat].new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
        self.last = page  # (what a run that stops was looking at)
        return page

    def sheet(self, seat: str, frames: list[str] | None = None) -> Page:
        """A seat's sheet; `frames` collects what passes on its connections, so a run can see the Game Log itself."""
        url = f"https://www.dndbeyond.com/characters/{SHEETS[seat]}"
        page = next((x for x in self.contexts[seat].pages if x.url.startswith(url)), None) or self.contexts[seat].new_page()
        if frames is not None:
            def listen(ws):
                ws.on("framesent", lambda text: frames.append(str(text)))
                ws.on("framereceived", lambda text: frames.append(str(text)))
            page.on("websocket", listen)
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
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
        for _ in range(int(seconds * 2)):
            try:
                if check():
                    self.results.append((True, f"{self.run}: {what}"))
                    print("PASS", what, flush=True)
                    return True
            except Exception:
                pass
            page.wait_for_timeout(500)
        self.results.append((False, f"{self.run}: {what}"))
        print("FAIL", what, flush=True)
        return False


def pill(page: Page) -> str:
    return " ".join(page.locator("#live-pill").inner_text(timeout=3000).split())


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


def hit_points(t: Table, seat: str = "player2") -> None:
    """Damage made in askdnd lands on the real sheet and comes back confirmed; healing puts it back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    start = hp(page)
    print("  hit points:", start, flush=True)
    change_hp(page, 0, 1)
    t.expect("the tile shows 1 less at once", lambda: hp(page) == start - 1, 6)
    t.expect("D&D Beyond confirms it", lambda: settled(page), 25)
    t.expect("the real sheet shows it", lambda: str(start - 1) in sheet.locator("[class*=hitPointsBox]").first.inner_text(timeout=2000), 15)
    page.wait_for_timeout(1000)
    change_hp(page, 1, 1)
    t.expect("healing puts it back", lambda: hp(page) == start, 6)
    t.expect("D&D Beyond confirms the healing", lambda: settled(page), 25)
    t.expect("the real sheet shows it back", lambda: str(start) in sheet.locator("[class*=hitPointsBox]").first.inner_text(timeout=2000), 15)


def condition(t: Table, seat: str = "player2", name: str = "Poisoned") -> None:
    """A condition started in askdnd lands on the real sheet; ended in askdnd, it leaves it."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    page.locator("details.cond-add > summary").click(timeout=5000)
    page.locator(f'.ls-chip:has-text("{name}")').first.click(timeout=5000)
    t.expect("the condition shows on Battle", lambda: page.locator(f'.cond-pill:has-text("{name}")').count() > 0, 8)
    t.expect("it reaches the real sheet", lambda: name in sheet.locator(".ct-conditions-summary").first.inner_text(timeout=3000), 25)
    page.wait_for_timeout(1500)
    page.locator(f'details.cond-pill:not(.cond-add):has-text("{name}") > summary').first.click(timeout=5000)
    page.locator(f'details.cond-pill:not(.cond-add):has-text("{name}") button:has-text("End")').first.click(timeout=5000)
    t.expect("it ends on Battle", lambda: page.locator(f'details.cond-pill:not(.cond-add):has-text("{name}")').count() == 0, 15)
    t.expect("it leaves the real sheet", lambda: name not in sheet.locator(".ct-conditions-summary").first.inner_text(timeout=3000), 25)


def record(sheet: Page) -> dict:
    """The sheet as D&D Beyond itself keeps it, so a run never relies on a label on either page."""
    cid = sheet.url.split("/characters/")[1].split("/")[0].split("?")[0]
    got = sheet.evaluate("""url => fetch(url, {credentials: 'include'}).then(r => r.json())""", f"https://character-service.dndbeyond.com/character/v5/character/{cid}")
    return got["data"]


def changes(before, after, path: str = "") -> list[tuple[str, object, object]]:
    """Every value that differs between two records, leaving out what D&D Beyond works out or stamps by itself."""
    if isinstance(before, dict) and isinstance(after, dict):
        return [c for k in sorted(set(before) | set(after)) if k not in ("dateModified", "providedFrom", "readonlyUrl", "definition")
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


def changed(t: Table, sheet: Page, before: dict, what: str, seconds: float = 25) -> list:
    """Waits for D&D Beyond's own record to differ from `before`."""
    t.expect(what, lambda: bool(changes(before, record(sheet))), seconds)
    diff = changes(before, record(sheet))
    print("  D&D Beyond:", show(diff), flush=True)
    return diff


def undone(t: Table, sheet: Page, before: dict, what: str, seconds: float = 25) -> None:
    t.expect(what, lambda: not changes(before, record(sheet)), seconds)


def undo(page: Page) -> None:
    page.locator('#cards button:has-text("Undo")').last.click(timeout=8000)


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
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    before = record(sheet)
    spell_window(page)
    print("  spell:", page.locator(".rw-title").first.inner_text(), page.locator('select[name="way"] option').all_inner_texts(), flush=True)
    page.locator("[data-use-go]").first.click()
    changed(t, sheet, before, "the slot is spent on D&D Beyond")
    undo(page)
    undone(t, sheet, before, "Undo gives the slot back on D&D Beyond")


def resource(t: Table, seat: str = "player3") -> None:
    """A resource counted down in askdnd counts down on D&D Beyond, and comes back."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
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
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    before = record(sheet)
    page.goto(page.url.replace("/battle", ""), wait_until="domcontentloaded")
    for to, what in (("gain", "the coin is on D&D Beyond"), ("spend", "spending it takes it off")):  # (the window both ways:
        tab = page.locator('[data-tab="t-items"]:visible').first                                       # Undo's card is gone
        if tab.get_attribute("aria-selected") != "true":                                                # after a few seconds)
            tab.click(timeout=8000)
        go(page, page.locator('[data-use-url$="/coins"]:visible').first)
        page.locator('.roll-win input[name="amount"]').first.fill("1")
        page.locator(f'[data-use-go][data-to="{to}"]').first.click()
        if to == "gain":
            changed(t, sheet, before, what)
        else:
            undone(t, sheet, before, what)
        page.wait_for_timeout(1500)
        page.keyboard.press("Escape")


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
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    change_hp(page, 0, 3)
    t.expect("D&D Beyond confirms the damage", lambda: settled(page), 25)
    page.wait_for_timeout(1500)
    start = record(sheet)
    print("  before the rest:", start["removedHitPoints"], "down,", [c.get("hitDiceUsed") for c in start["classes"]], "Hit Point Dice used", flush=True)
    rest_window(page, "short")
    page.locator('select[name^="dice_"]').first.select_option("1")
    page.locator("[data-use-go]").first.click()
    t.expect("a Hit Point Die is spent on D&D Beyond", lambda: sum(c.get("hitDiceUsed") or 0 for c in record(sheet)["classes"]) > sum(c.get("hitDiceUsed") or 0 for c in start["classes"]), 30)
    print("  after the Short Rest:", show(changes(start, record(sheet))), flush=True)
    page.wait_for_timeout(2500)
    page.keyboard.press("Escape")
    page.goto(page.url, wait_until="domcontentloaded")
    name = next(x["name"] for group in start["actions"].values() for x in group or []
                if (x.get("limitedUse") or {}).get("resetType") == 2 and x["limitedUse"].get("maxUses"))  # (back on a Long Rest)
    go(page, page.locator(f'.res-go[data-use-url*="/count"]:has-text("{name}")').first)
    page.locator('[data-use-go][data-to="use"]').first.click()
    t.expect("a use is spent before the Long Rest", lambda: spent(record(sheet)) > spent(start), 25)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    spell_window(page)
    page.locator("[data-use-go]").first.click()
    t.expect("a slot is spent before the Long Rest", lambda: any(x["used"] for x in record(sheet)["spellSlots"]), 25)
    page.wait_for_timeout(2500)
    page.goto(page.url, wait_until="domcontentloaded")
    middle = record(sheet)
    print("  before the Long Rest:", middle["removedHitPoints"], "down,", spent(middle), "uses spent,", [x["used"] for x in middle["spellSlots"]], "slots used", flush=True)
    rest_window(page, "long")
    page.locator("[data-use-go]").first.click()
    t.expect("the Long Rest gives Hit Point Dice back on D&D Beyond", lambda: not any(c.get("hitDiceUsed") for c in record(sheet)["classes"]), 40)
    t.expect("the Long Rest gives Hit Points back on D&D Beyond", lambda: record(sheet)["removedHitPoints"] == 0, 15)
    t.expect("the Long Rest gives slots back on D&D Beyond", lambda: not any(x["used"] for x in record(sheet)["spellSlots"]), 25)
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
    if which == "temp":  # (the player's choice: take the new ones)
        page.locator('.peek.open .hp-take label:has(input[value="1"])').first.click(timeout=5000)
        page.wait_for_timeout(800)
    page.locator('.peek.open .hp-form button[type="submit"]:not([disabled])').first.click(timeout=10000)  # (once its working has caught up)
    page.wait_for_timeout(800)
    page.keyboard.press("Escape")


def temp_hp(t: Table, seat: str = "player2") -> None:
    """Temporary Hit Points given in askdnd land on the real sheet; damage takes them first and leaves Hit Points be."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    start = record(sheet)
    hp_window(page, "temp", 5)
    t.expect("D&D Beyond has 5 Temporary Hit Points", lambda: record(sheet)["temporaryHitPoints"] == 5, 25)
    page.wait_for_timeout(1500)
    hp_window(page, "damage", 5)
    t.expect("damage takes the Temporary Hit Points first", lambda: record(sheet)["temporaryHitPoints"] == 0, 25)
    t.expect("and leaves Hit Points as they were", lambda: record(sheet)["removedHitPoints"] == start["removedHitPoints"], 5)


def unconscious(data: dict) -> bool:
    return any(c["id"] == 15 for c in data.get("conditions") or [])


def death_saves(t: Table, seat: str = "player2") -> None:
    """At 0 Hit Points: Unconscious and the marks start on the real sheet, a death save rolled in askdnd marks itself
    there, and healing clears the marks and ends Unconscious."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    start, now = record(sheet), hp(page)
    print("  hit points:", now, flush=True)
    hp_window(page, "damage", now)
    t.expect("D&D Beyond has 0 Hit Points and Unconscious", lambda: (lambda d: d["removedHitPoints"] >= start["removedHitPoints"] + now and unconscious(d))(record(sheet)), 30)
    t.expect("the Dying tile offers the death save", lambda: page.locator('[data-roll="death"]:visible').count() > 0, 15)
    page.wait_for_timeout(1500)
    page.locator('[data-roll="death"]:visible').first.click(modifiers=["Shift"])
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    marked = lambda d: (d["deathSaves"]["successCount"] or 0) + (d["deathSaves"]["failCount"] or 0) > 0 or d["removedHitPoints"] < start["removedHitPoints"] + now  # (a 20 is back with 1 Hit Point)
    t.expect("the death save marks the real sheet", lambda: marked(record(sheet)), 30)
    print("  death saves:", record(sheet)["deathSaves"], flush=True)
    page.wait_for_timeout(1500)
    page.goto(page.url, wait_until="domcontentloaded")
    back = record(sheet)["removedHitPoints"] - start["removedHitPoints"]
    hp_window(page, "heal", back)
    t.expect("healing clears the marks on D&D Beyond", lambda: not any((record(sheet)["deathSaves"][k] or 0) for k in ("successCount", "failCount")), 30)
    t.expect("and ends Unconscious", lambda: not unconscious(record(sheet)), 15)
    t.expect("and Hit Points are back", lambda: record(sheet)["removedHitPoints"] == start["removedHitPoints"], 15)


def inspiration(t: Table, seat: str = "player2") -> None:
    """Heroic Inspiration given in askdnd lands on the real sheet; spending it takes it off."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    had = record(sheet)["inspiration"]
    for want in (not had, had):
        go(page, page.locator('[data-use-url$="/inspiration"]:visible').first)
        page.locator("[data-use-go]").first.click()
        t.expect(f"D&D Beyond {'has' if want else 'no longer has'} it", lambda: record(sheet)["inspiration"] == want, 25)
        page.wait_for_timeout(1500)
        page.keyboard.press("Escape")


def exhaustion(t: Table, seat: str = "player2") -> None:
    """Exhaustion started in askdnd lands on the real sheet at its level; a new level follows, and ending it leaves."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
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
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    cid = page.url.split("/characters/")[1].split("/")[0]
    staff, potion = have["Staff of Healing"]["id"], have["Potion of Healing"]["id"]
    start = record(sheet)
    for field, on, off in (("equipped", "Equip", "Unequip"), ("isAttuned", "Attune", "End attunement")):
        was = item(start, staff)[field]
        press(page, cid, staff, off if was else on)
        t.expect(f"{on}: D&D Beyond follows", lambda: item(record(sheet), staff)[field] != was, 25)
        press(page, cid, staff, on if was else off)
        t.expect(f"{on}: and back", lambda: item(record(sheet), staff)[field] == was, 25)
    item_panel(page, cid, staff)
    used = lambda d: (item(d, staff).get("limitedUse") or {}).get("numberUsed") or 0
    go(page, page.locator('.peek.open [data-use-url*="field=charges"]').first)
    page.locator('[data-use-go][data-to="use"]').first.click()
    t.expect("a charge is spent on D&D Beyond", lambda: used(record(sheet)) == used(start) + 1, 25)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    item_panel(page, cid, staff)
    go(page, page.locator('.peek.open [data-use-url*="field=charges"]').first)
    page.locator('[data-use-go][data-to="back"]').first.click()
    t.expect("and given back", lambda: used(record(sheet)) == used(start), 25)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    bolts = have["Crossbow Bolts"]["id"]
    many = lambda d: item(d, bolts)["quantity"]
    for to, n, what in (("use", -1, "one is used on D&D Beyond"), ("back", 0, "and given back")):
        item_panel(page, cid, bolts)
        go(page, page.locator('.peek.open [data-use-url*="field=item"]').first)
        page.locator(f'[data-use-go][data-to="{to}"]').first.click()
        t.expect(f"Crossbow Bolts: {what}", lambda: many(record(sheet)) == many(start) + n, 25)
        page.wait_for_timeout(1500)
        page.keyboard.press("Escape")
    count = lambda d: item(d, potion)["quantity"]
    hp_window(page, "damage", 5)  # (so the potion's healing shows)
    hurt = start["removedHitPoints"] + 5
    t.expect("D&D Beyond has the damage", lambda: record(sheet)["removedHitPoints"] == hurt, 25)
    page.goto(f"https://beta.askdnd.ai/characters/{cid}/battle", wait_until="domcontentloaded")
    page.locator('[data-panel-url$="/all/bonus?items=1"]').first.click(timeout=8000)  # (every potion is a Bonus Action)
    go(page, page.locator(f'.peek.open [data-use-url$="/use/{potion}"]').first)
    page.locator("[data-use-go]").first.click()
    t.expect("drinking a Potion of Healing takes one off D&D Beyond", lambda: count(record(sheet)) == count(start) - 1, 25)
    t.expect("and heals there", lambda: record(sheet)["removedHitPoints"] < hurt, 25)
    page.wait_for_timeout(1500)
    page.keyboard.press("Escape")
    undo(page)
    t.expect("Undo puts the potion back on D&D Beyond", lambda: count(record(sheet)) == count(start), 25)
    t.expect("and the healing", lambda: record(sheet)["removedHitPoints"] == hurt, 25)
    page.wait_for_timeout(1500)
    healed = record(sheet)["removedHitPoints"] - start["removedHitPoints"]
    if healed > 0:
        hp_window(page, "heal", healed)
    t.expect("and Hit Points are back", lambda: record(sheet)["removedHitPoints"] == start["removedHitPoints"], 25)


RUNS = {"closed-sheet": closed_sheet, "game-log": game_log, "close-after-roll": close_after_roll, "hit-points": hit_points, "condition": condition,
        "cast": cast, "resource": resource, "coins": coins, "rests": rests, "temp-hp": temp_hp, "death-saves": death_saves,
        "inspiration": inspiration, "exhaustion": exhaustion, "inventory": inventory}
# What a run may leave changed on a sheet: D&D Beyond's own bookkeeping, and the inventory run's stock once it's there
KEPT = ("dateModified", "providedFrom", "readonlyUrl", "definition", "inventory", "campaign", "decorations")


def as_found(t: Table, before: dict) -> None:
    """Each test sheet is back as part 1 found it: what a run changes, it puts back (a miss here is a run that didn't)."""
    for seat, was in before.items():
        sheet = t.sheet(seat)
        left = lambda: changes({k: v for k, v in was.items() if k not in KEPT}, {k: v for k, v in record(sheet).items() if k not in KEPT})
        if not t.expect(f"{seat}'s sheet is back as found", lambda: not left(), 20):  # (D&D Beyond can serve an older copy for a moment)
            print("  still changed:", show(left()), flush=True)


def report(missed: list[str], ran: list[str], log: str) -> None:
    """To Sentry (askdnd-v2), where the app's own errors go and alert Brett: one issue for the live test, whatever missed."""
    import os

    import sentry_sdk

    sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], environment="live-test", server_name="mac-mini", default_integrations=False)
    with sentry_sdk.new_scope() as scope:
        scope.fingerprint = ["live-test", "part-1"]
        scope.set_tag("source", "live-test")
        scope.set_context("live test", {"runs": ", ".join(ran), "missed": missed[:40], "log": log[-6000:]})
        sentry_sdk.capture_message(f"Live test part 1: {len(missed)} missed ({missed[0][:120]})", level="error")
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
        ["limited uses spent"] if spent(d) else [])


def clean_start(t: Table, seat: str) -> None:
    """Part 1 starts on clean sheets. Anything left over (a run before this one that didn't put it back) is a miss, and
    hit points, death saves and conditions are put right on D&D Beyond, as the seat's player could on the sheet."""
    sheet = t.sheet(seat)
    d = record(sheet)
    found = left_over(d)
    t.results.append((not found, f"{seat}'s sheet starts clean"))
    print("PASS" if not found else "FAIL", f"{seat}'s sheet starts clean", "; ".join(found), flush=True)
    ops = ([["PUT", "life/hp/damage-taken", {"removedHitPoints": 0, "temporaryHitPoints": 0}]] if d.get("removedHitPoints") or d.get("temporaryHitPoints") else []) + (
        [["PUT", "life/death-saves", {"failCount": 0, "successCount": 0}]] if (d.get("deathSaves") or {}).get("failCount") or (d.get("deathSaves") or {}).get("successCount") else []) + [
        ["DELETE", "condition", {"id": c["id"]}] for c in d.get("conditions") or []]
    if ops:
        print("  put right on D&D Beyond:", sheet.evaluate(TIDYING, [SHEETS[seat], ops]), flush=True)


def used(names: list[str]) -> set[str]:
    """The sheets these runs act on (each run names its seats as defaults)."""
    import inspect

    return {p.default for n in names for p in inspect.signature(RUNS[n]).parameters.values() if p.default in SHEETS}


def main() -> int:
    args = sys.argv[1:]
    to_sentry = "--sentry" in args
    names = [a for a in args if not a.startswith("--")] or list(RUNS)
    sys.stdout = out = Kept(sys.stdout)
    with sync_playwright() as p:
        t = Table(p)
        if "--try-alert" in args:  # (a deliberate miss: checks the way to Sentry, real_table_nightly.sh --try-alert)
            t.results.append((False, "a deliberate miss, to try the alert (--try-alert)"))
        try:
            if "inventory" in names:
                stock(t.sheet("player2"))  # (before the sheets are noted: stocking is setting up, not a run's change)
            for seat in sorted(used(names)):
                clean_start(t, seat)
            before = {seat: record(t.sheet(seat)) for seat in SHEETS if seat in used(names)}
        except Exception as e:  # (the seats aren't open, or D&D Beyond can't be reached)
            t.results.append((False, f"the seats open: {type(e).__name__}: {str(e)[:200]}"))
            before = {}
        for name in names if before else []:
            print("==", name, flush=True)
            t.run = name
            try:
                RUNS[name](t)
            except Exception as e:  # one run going wrong is a result, and the rest still run
                lines = str(e).splitlines()
                at = next((x.strip() for x in lines if "waiting for" in x), "")  # (what it was waiting for)
                t.results.append((False, f"{name}: stopped with {type(e).__name__}: {lines[0][:120]} {at[:160]}"))
                print("FAIL", t.results[-1][1], flush=True)
                try:
                    shot = f"logs/stopped-{time.strftime('%Y-%m-%d-%H%M')}-{name}.png"
                    t.last.screenshot(path=shot)
                    print("  what it was looking at:", shot, flush=True)
                except Exception:
                    pass
        if before:
            t.run = "after"
            as_found(t, before)
    missed = [what for ok, what in t.results if not ok]
    print(f"{len(t.results) - len(missed)} of {len(t.results)} as expected", flush=True)
    if missed and to_sentry:
        report(missed, names, "".join(out.text))
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
