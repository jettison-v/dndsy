"""Real fights on the real D&D Beyond: named runs on the Mac Mini's test seats (docs/testing-setup.md).

Run by hand on the Mini, never on GitHub: `.venv/bin/python real_table.py <run>` after `seats.sh <seat>` has opened each
seat in real Chrome. Each run does what a person would do, then says what happened and what it expected. It only ever
touches the test seats in VTT test on beta: Brett's primary account is not a seat here, and it never signs in to anything.
"""

import sys

from playwright.sync_api import Page, sync_playwright

BETA = "https://beta.askdnd.ai/c/vtt-test"
SEATS = {"dm": 9231, "player2": 9232, "player3": 9233}
SHEETS = {"player2": 172986165, "player3": 172992073}  # Cathartic and the new Vi, never the first Vi or Spurt


class Table:
    def __init__(self, p):
        self.contexts = {seat: p.chromium.connect_over_cdp(f"http://127.0.0.1:{port}").contexts[0] for seat, port in SEATS.items()}
        self.results: list[tuple[bool, str]] = []

    def page(self, seat: str, url: str) -> Page:
        page = next((x for x in self.contexts[seat].pages if x.url.startswith(url)), None) or self.contexts[seat].new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=45000)
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
        page = next(iter(self.contexts.values())).pages[0]
        for _ in range(int(seconds * 2)):
            try:
                if check():
                    self.results.append((True, what))
                    print("PASS", what, flush=True)
                    return True
            except Exception:
                pass
            page.wait_for_timeout(500)
        self.results.append((False, what))
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
    page.locator('.hp-form input[name="amount"]').first.fill(str(amount), timeout=8000)
    page.locator('.hp-form input[name="amount"]').first.press("Tab")
    page.wait_for_timeout(800)
    page.locator('.hp-form button[type="submit"]').first.click(timeout=5000)
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
    t.expect("it ends on Battle", lambda: page.locator(f'details.cond-pill:not(.cond-add):has-text("{name}")').count() == 0, 8)
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
        if all(isinstance(x, dict) and "id" in x for x in before + after):  # (D&D Beyond's lists come in any order)
            before, after = sorted(before, key=lambda x: str(x["id"])), sorted(after, key=lambda x: str(x["id"]))
        return [c for i, (a, b) in enumerate(zip(before, after)) for c in changes(a, b, f"{path}[{i}]")]
    return [] if before == after else [(path, before, after)]


def show(diff: list) -> str:
    return "; ".join(f"{path} {a} to {b}" for path, a, b in diff[:8]) + (f" and {len(diff) - 8} more" if len(diff) > 8 else "") or "nothing"


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
    """Coins gained in askdnd land on D&D Beyond; Undo takes them off."""
    sheet = t.sheet(seat)
    page = t.battle(seat)
    t.expect("the sheet connects", lambda: "Connected" in pill(page), 40)
    before = record(sheet)
    page.goto(page.url.replace("/battle", ""), wait_until="domcontentloaded")
    page.locator('[data-tab="t-items"]').first.click(timeout=8000)
    go(page, page.locator('[data-use-url$="/coins"]').first)
    page.locator('input[name="amount"]').first.fill("1")
    page.locator('[data-use-go][data-to="gain"]').first.click()
    changed(t, sheet, before, "the coin is on D&D Beyond")
    undo(page)
    undone(t, sheet, before, "Undo takes the coin off")


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
    t.expect("the Long Rest gives the use back on D&D Beyond", lambda: spent(record(sheet)) <= spent(start), 25)
    print("  after the Long Rest:", show(changes(middle, record(sheet))), flush=True)


RUNS = {"closed-sheet": closed_sheet, "game-log": game_log, "close-after-roll": close_after_roll, "hit-points": hit_points, "condition": condition,
        "cast": cast, "resource": resource, "coins": coins, "rests": rests}


def main() -> int:
    names = sys.argv[1:] or list(RUNS)
    with sync_playwright() as p:
        t = Table(p)
        for name in names:
            print("==", name, flush=True)
            RUNS[name](t)
    missed = [what for ok, what in t.results if not ok]
    print(f"{len(t.results) - len(missed)} of {len(t.results)} as expected", flush=True)
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
