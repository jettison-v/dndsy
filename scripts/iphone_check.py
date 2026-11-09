"""askdnd in real iPhone and iPad Safari, on the Mac Mini (Brett, Nov 8: the layout tests run WebKit sized like an
iPhone, which isn't Safari on one; docs/live-test-plan.md › iPhone Safari).

Apple's iOS Simulator (part of Xcode) runs the real Mobile Safari, and Appium (open source, its XCUITest driver) drives
it over WebDriver. (Safari's own `safaridriver` can't start a simulator with Xcode 27.2, which replaced the Simulator
app with DeviceHub; Nov 8.) For a small iPhone, a large one and an iPad mini, one at a time, each test seat's pages are opened signed in as that
seat (its askdnd sign-in copied from the seat's Chrome, never typed or printed) and checked for:
- what the layout tests check (tests/browser/layout_check.js, copied beside this script): scrolling sideways, text
  spilling out of its box, a one-line control wrapping, overlaps, a box you type in under 16px;
- tapping the page's first box you type in, as a finger does: the page mustn't zoom, and the box must stay in sight above
  the keyboard;
- the end of the page reachable above the bottom bar.
A screenshot of each page, Safari's own bars included, goes to logs/iphone/ (the newest run only: the Mini's disk is
small). `--sentry` reports misses like the nightly's part 1 (environment live-test, its own issue).

On the Mini, in ~/askdnd-tests, with the seats open (real_table_seats.sh open): `.venv/bin/python iphone_check.py`.
Read-only: it changes nothing on askdnd or D&D Beyond.
  iphone_check.py                  every device, every seat
  iphone_check.py --devices ipad   one device (small, large, ipad)
  iphone_check.py --seats dm       one seat (dm, player2)
One-time setup on the Mini (docs/live-test-plan.md › iPhone Safari): Xcode (App Store, its license accepted, its
simulator: `xcodebuild -downloadPlatform iOS`), Node.js in ~/askdnd-tests/node, and Appium with its XCUITest driver in
~/askdnd-tests/appium-pkg (APPIUM_HOME ~/askdnd-tests/appium-home). The first session on each simulator builds Appium's
helper app (WebDriverAgent) there, a few minutes; later ones start in seconds.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
BASE = "https://beta.askdnd.ai"
CAMPAIGN = "/c/vtt-test"
SEATS = {"dm": 9231, "player2": 9232}  # (the seats' Chrome, real_table.SEATS: only their askdnd sign-in is read)
SHOTS = HERE / "logs" / "iphone"
PORT = 4723  # Appium's
APPIUM = HERE / "appium-pkg" / "node_modules" / ".bin" / "appium"

# Each kind of device by the simulator names that would do, best first (the newest iOS the Mini has decides which exist)
DEVICES = {
    "small": ("iPhone SE", "iPhone 16e", "iPhone 17e", "mini"),
    "large": ("Pro Max", "Plus", "iPhone Air"),
    "ipad": ("iPad mini",),
}
PAGES = {
    "player2": ("/", "/?tab=sessions", "/campaign", "@/battle", "@", "@/plan", "!/party", "!/help", "!/your-notes"),
    "dm": ("/manage", "/manage/inbox", "/manage/sessions", "/manage/table", "/manage/settings"),
}

TYPED = ('textarea, select, [contenteditable=""], [contenteditable=true], input:not([type=checkbox]):not([type=radio]):not([type=range])'
         ':not([type=button]):not([type=submit]):not([type=reset]):not([type=file]):not([type=color]):not([type=hidden]):not([type=image])')
# The first box you type in on the page itself (not in a closed window or fold), by its place among TYPED
FIRST_FIELD = """const all = [...document.querySelectorAll(arguments[0])];
  const i = all.findIndex(el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && !el.disabled && !el.readOnly
    && getComputedStyle(el).visibility !== 'hidden' && !el.closest('[hidden], details:not([open]), .menu, .peek:not(.open)'); });
  if (i >= 0) all[i].scrollIntoView({block: 'center'});
  return i;"""
# After the tap: zoomed, and is the box in sight (the visual viewport is what's left above the keyboard)
AFTER_TAP = """const v = visualViewport, el = document.activeElement, r = el.getBoundingClientRect();
  // (a list, not an object: Appium's answer drops an object's "scale")
  const out = [v.scale, el.matches(arguments[0]), r.top >= v.offsetTop - 1 && r.bottom <= v.offsetTop + v.height + 1,
               (el.closest('[id]') ? '#' + el.closest('[id]').id + ' ' : '') + el.tagName.toLowerCase() + (el.name ? '[name=' + el.name + ']' : '')];
  el.blur();
  return out;"""
# The end of the page above the fixed bottom bar, scrolled all the way down
BOTTOM = """scrollTo(0, document.documentElement.scrollHeight);
  const bar = [...document.querySelectorAll('.bottom-nav, .mobile-bar')].find(b => b.getBoundingClientRect().height > 0 && getComputedStyle(b).position === 'fixed');
  const main = document.querySelector('main');
  if (!bar || !main) return null;
  // (text on the page itself: not cut off by a box that scrolls or clips (it isn't shown there), in a closed fold, or in
  // something placed on top)
  const own = el => { const b = el.getBoundingClientRect().bottom;
    if (el.checkVisibility && !el.checkVisibility({contentVisibilityAuto: true, visibilityProperty: true})) return false;  // (a closed fold's text still has a place)
    for (let e = el.parentElement; e && e !== main; e = e.parentElement) { const cs = getComputedStyle(e);
      if (/fixed|absolute|sticky/.test(cs.position) || e.matches('details:not([open])')) return false;
      if (/auto|scroll|hidden|clip/.test(cs.overflowY) && b > e.getBoundingClientRect().bottom + 1) return false; }
    return true; };
  const leaves = [...main.querySelectorAll('*')].filter(el => !el.children.length && el.getBoundingClientRect().height > 0 && el.textContent.trim() && own(el));
  const last = leaves.sort((a, b) => b.getBoundingClientRect().bottom - a.getBoundingClientRect().bottom)[0];
  const covered = last && last.getBoundingClientRect().bottom > bar.getBoundingClientRect().top + 2;
  scrollTo(0, 0);
  return covered ? last.textContent.trim().slice(0, 60) : null;"""
TABS = "return [...document.querySelectorAll('main [role=tab]')].filter(t => t.getBoundingClientRect().width > 0).map(t => t.textContent.trim().split('\\n')[0])"
CLICK_TAB = "[...document.querySelectorAll('main [role=tab]')].filter(t => t.getBoundingClientRect().width > 0)[arguments[0]].click()"
MY_CHARACTER = """const a = [...document.querySelectorAll('a[href^="/characters/"]')].map(a => a.getAttribute('href').match(/^\\/characters\\/(\\d+)/)).find(Boolean);
  return a && a[1];"""


def sh(*args: str, check: bool = True) -> str:
    return subprocess.run(args, capture_output=True, text=True, check=check).stdout


def simulators() -> dict[str, dict]:
    """Each kind of device: the simulator of the newest iOS the Mini has that matches it."""
    listed = json.loads(sh("xcrun", "simctl", "list", "devices", "available", "-j"))["devices"]
    import re

    # (plain runtimes only: "iOS-27-2", not one made for a single device, "iOS-27-2-iPhone19-4")
    ios = sorted((k for k in listed if re.search(r"\.iOS-[\d-]+$", k)), key=lambda k: [int(n) for n in k.rsplit(".iOS-", 1)[1].split("-")])
    found = {}
    for kind, hints in DEVICES.items():
        for runtime in reversed(ios):
            pick = next((d for h in hints for d in listed[runtime] if h in d["name"] and d["name"].startswith("iPad" if kind == "ipad" else "iPhone")), None)
            if pick:
                found[kind] = pick
                break
    return found


class Safari:
    """Mobile Safari in one simulator, through Appium's WebDriver (the W3C protocol, plain HTTP)."""

    def __init__(self, udid: str):
        self.base = f"http://127.0.0.1:{PORT}"
        caps = {"browserName": "Safari", "platformName": "iOS", "appium:automationName": "XCUITest", "appium:udid": udid,
                "appium:nativeWebTap": True,  # (a tap is a finger's on the screen, not a script's click)
                "appium:wdaLaunchTimeout": 480_000, "appium:newCommandTimeout": 300,
                "appium:webviewConnectTimeout": 30_000}  # (Safari's page reaching the debugger: 5 seconds wasn't always enough)
        for attempt in range(3):
            try:
                self.sid = self.call("POST", "/session", {"capabilities": {"alwaysMatch": caps}})["sessionId"]
                return
            except (RuntimeError, TimeoutError):
                if attempt == 2:
                    raise
                time.sleep(5)

    def call(self, method: str, path: str, body: dict | None = None):
        if path != "/session":
            path = f"/session/{self.sid}{path}"
        data = json.dumps(body or {}).encode() if method == "POST" else None
        req = urllib.request.Request(self.base + path, data=data, method=method, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=600 if path == "/session" else 120) as r:  # (a new simulator's first session installs Appium's helper app: minutes)
                return json.load(r)["value"]
        except urllib.error.HTTPError as e:
            raise RuntimeError(json.load(e)["value"].get("message", str(e))) from None

    def go(self, url: str) -> None:
        self.call("POST", "/url", {"url": url})
        for _ in range(40):  # (and the page's own scripts have run)
            if self.js("return document.readyState") == "complete":
                break
            time.sleep(0.25)
        time.sleep(1)

    def js(self, script: str, *args):
        return self.call("POST", "/execute/sync", {"script": script, "args": list(args)})

    def tap(self, css: str, index: int) -> None:
        """A real tap (Appium's native tap at the element), not a script's click: only a finger's makes Safari zoom or the keyboard rise."""
        els = self.call("POST", "/elements", {"using": "css selector", "value": css})
        self.call("POST", f"/element/{next(iter(els[index].values()))}/click")

    def quit(self) -> None:
        try:
            self.call("DELETE", "")
        except Exception:  # noqa: BLE001 - closing anyway
            pass


def sign_in(safari: Safari, seat: str, playwright) -> None:
    """The seat's askdnd sign-in, copied from its Chrome into Safari (the cookie only; never shown)."""
    ctx = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{SEATS[seat]}").contexts[0]
    got = [c for c in ctx.cookies(BASE) if c["name"] == "askdnd_session"]
    if not got:
        raise RuntimeError(f"{seat}'s Chrome isn't signed in to askdnd")
    safari.go(BASE + "/health")
    safari.call("DELETE", "/cookie")  # (a page of askdnd's own, so the cookie is askdnd's)
    c = got[0]
    safari.call("POST", "/cookie", {"cookie": {"name": c["name"], "value": c["value"], "path": "/", "secure": True, "httpOnly": True}})


def address(page: str, character: str | None) -> str:
    if page.startswith("!"):
        return page[1:]
    if page.startswith("@"):
        return f"/characters/{character}{page[1:]}"
    return CAMPAIGN + page


def check_page(safari: Safari, udid: str, device: str, seat: str, path: str, shot: str, layout: str) -> list[str]:
    found = [f"{p['kind']}: {p['where']} ({p['detail']})" for p in safari.js(f"return ({layout})({{}})")]
    for k, tab in enumerate(safari.js(TABS)[1:], start=1):  # each of main's tabs (the first is the page itself)
        safari.js(CLICK_TAB, k)
        time.sleep(0.6)
        found += [f"› {tab} · {p['kind']}: {p['where']} ({p['detail']})" for p in safari.js(f"return ({layout})({{}})")]
    if safari.js(TABS):
        safari.js(CLICK_TAB, 0)
    under = safari.js(BOTTOM)
    if under:
        found.append(f"under the bottom bar: the page's end (\"{under}\") can't be scrolled into sight")
    sh("xcrun", "simctl", "io", udid, "screenshot", "--type=png", str(SHOTS / f"{shot}.png"), check=False)
    field = safari.js(FIRST_FIELD, TYPED)
    if field >= 0:
        time.sleep(0.5)
        safari.tap(TYPED, field)
        time.sleep(1.5)  # (the keyboard rising, Safari zooming)
        sh("xcrun", "simctl", "io", udid, "screenshot", "--type=png", str(SHOTS / f"{shot}-typing.png"), check=False)
        scale, focused, seen, where = safari.js(AFTER_TAP, TYPED)
        if focused and scale > 1.01:
            found.append(f"zooms: tapping {where} zoomed the page to {scale:.2f}×")
        if focused and not seen:
            found.append(f"hidden by the keyboard: {where} is out of sight once tapped")
    return [f"{device} · {seat} · {path} · {f}" for f in found]


def run(devices: list[str], seats: list[str]) -> list[str]:
    from playwright.sync_api import sync_playwright

    layout = (HERE / "layout_check.js").read_text()
    shutil.rmtree(SHOTS, ignore_errors=True)
    SHOTS.mkdir(parents=True)
    found_devices = simulators()
    missing = [d for d in devices if d not in found_devices]
    problems = [f"{d} · no simulator for it on the Mini (xcrun simctl list devices)" for d in missing]
    env = {**os.environ, "PATH": f"{HERE / 'node' / 'bin'}:{os.environ.get('PATH', '')}", "APPIUM_HOME": str(HERE / "appium-home")}
    with open(HERE / "logs" / "appium.log", "w") as log:
        driver = subprocess.Popen([str(APPIUM), "-p", str(PORT)], stdout=log, stderr=subprocess.STDOUT, env=env)
    try:
        for _ in range(60):  # (Appium answering)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/status", timeout=2)
                break
            except OSError:
                time.sleep(1)
        with sync_playwright() as p:
            for kind in (d for d in devices if d in found_devices):
                sim = found_devices[kind]
                name = f"{kind} ({sim['name']})"
                print(f"== {name}", flush=True)
                sh("xcrun", "simctl", "boot", sim["udid"], check=False)  # (already booted is fine)
                sh("xcrun", "simctl", "bootstatus", sim["udid"], "-b", check=False)
                safari = None
                try:
                    safari = Safari(sim["udid"])
                    for seat in seats:
                        sign_in(safari, seat, p)
                        safari.go(BASE + CAMPAIGN + "/")
                        character = safari.js(MY_CHARACTER)
                        for page in PAGES[seat]:
                            if page.startswith("@") and not character:
                                continue
                            path = address(page, character)
                            safari.go(BASE + path)
                            shot = f"{kind}-{seat}-{path.strip('/').replace('/', '_').replace('?', '_') or 'story'}"
                            got = check_page(safari, sim["udid"], name, seat, path, shot, layout)
                            print(f"  {seat} {path}: {len(got) or 'ok'}", flush=True)
                            problems += got
                except Exception as e:  # noqa: BLE001 - one device failing says so and the next one runs
                    problems.append(f"{name} · couldn't run: {type(e).__name__}: {str(e)[:200]}")
                finally:
                    if safari:
                        safari.quit()
                    sh("xcrun", "simctl", "shutdown", sim["udid"], check=False)
    finally:
        driver.terminate()
    return problems


def report(problems: list[str]) -> None:
    """To Sentry (askdnd-v2, environment live-test), one issue of its own like the nightly's parts."""
    import sentry_sdk

    sentry_sdk.init(dsn=os.environ["SENTRY_DSN"], environment="live-test", server_name="mac-mini", default_integrations=False)
    with sentry_sdk.new_scope() as scope:
        scope.fingerprint = ["live-test", "iphone-safari"]
        scope.set_tag("source", "live-test")
        scope.set_context("iPhone Safari", {"problems": problems[:60]})
        sentry_sdk.capture_message(f"iPhone Safari: {len(problems)} found ({problems[0][:120]})", level="error")
    sentry_sdk.flush(10)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--devices", default=",".join(DEVICES), help="small, large, ipad")
    ap.add_argument("--seats", default=",".join(PAGES), help="dm, player2")
    ap.add_argument("--sentry", action="store_true", help="report what's found to Sentry")
    args = ap.parse_args()
    if subprocess.run(["xcrun", "--find", "simctl"], capture_output=True).returncode or not APPIUM.exists():
        print("Not set up here: Xcode with its iOS simulator and Appium (docs/live-test-plan.md › iPhone Safari).")
        return 2
    problems = run(args.devices.split(","), args.seats.split(","))
    print("\n".join(problems) or "Everything holds together in iPhone and iPad Safari.")
    print(f"Screenshots: {SHOTS}")
    if problems and args.sentry:
        report(problems)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
