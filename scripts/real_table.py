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


RUNS = {"closed-sheet": closed_sheet, "game-log": game_log, "close-after-roll": close_after_roll}


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
