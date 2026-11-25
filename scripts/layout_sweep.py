"""A layout sweep (docs/DESIGN.md › Narrow screens): open every page askdnd links to, as the people given, at several
widths, with each of its tabs, the menu bar's menus and Battle's side panel, and list what scrolls sideways, spills,
wraps, overlaps or doesn't line up (tests/browser/layout_check.js). A screenshot of each page at each width goes to
private/layout-sweep/ (gitignored) for the look-over the checks can't do.

Against a local server with the dev login (DEV_LOGIN_EMAIL set in .env), on a copy of real data:
    uv run python scripts/layout_sweep.py --as brett@example.com --as dm@example.com
Run it at the end of each roadmap phase (docs/plans/2026-10-22-vtt-roadmap.md › How we build). The weekly phone sweep
(Brett, Nov 19: phone polish once a week, not on every change) runs it at phone and tablet widths only:
    uv run python scripts/layout_sweep.py --as brett@example.com --as dm@example.com --widths 375,768 --base http://localhost:8004"""

import argparse
import re
from collections import defaultdict
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
CHECK = (ROOT / "tests" / "browser" / "layout_check.js").read_text()
WIDTHS = (375, 768, 1000, 1280, 1440)
SKIP = ("/static/", "/logout", "/auth/", "/dev/", "/view-as", "/live/", "/errors/", "/tour", "/files/")
NOT_PAGES = re.compile(r"/(images|picture|thumb)/|\.(png|jpe?g|webp|json|csv|zip)$")


def pages_from(page, base: str, start: str, limit: int) -> list[str]:
    """The pages reachable from `start` (links on each page), at most two of each kind (ids collapsed)."""
    seen, kinds, todo, out = set(), defaultdict(int), [start], []
    while todo and len(out) < limit:
        path = todo.pop(0)
        if path in seen:
            continue
        seen.add(path)
        kind = re.sub(r"\d+", "N", urlsplit(path).path) + ("?" + urlsplit(path).query if urlsplit(path).query.startswith("tab=") else "")
        if kinds[kind] >= 2:
            continue
        try:
            r = page.goto(base + path, wait_until="domcontentloaded")
        except Exception:  # (the Map waits on an outside site; a page that hangs is skipped, not the sweep)
            continue
        if not r or r.status >= 400 or "text/html" not in (r.headers.get("content-type") or ""):
            continue
        kinds[kind] += 1
        out.append(urlsplit(page.url).path + (("?" + urlsplit(page.url).query) if urlsplit(page.url).query else ""))
        for href in page.eval_on_selector_all("a[href]", "els => els.map(e => e.getAttribute('href'))"):
            u = urlsplit(urljoin(base + path, href))
            if u.netloc != urlsplit(base).netloc or any(u.path.startswith(s) for s in SKIP) or NOT_PAGES.search(u.path):
                continue
            todo.append(u.path + ("?" + u.query if u.query else ""))
    return out


def scan(page, found, who, width, where):
    for p in page.evaluate(CHECK, {"rows": True}):
        found[(p["kind"], p["where"])].append((who, width, where, p["detail"]))


def open_windows(page, found, who, width, path, opened: set, shots: Path) -> None:
    """Every window this page opens (data-modal-url), each kind once per person and width (ids collapsed): opened,
    checked and pictured, then closed (Brett, Nov 25: the windows Backstage's rounds made were never opened by a check).
    A window that only shows after a press inside another isn't reached."""
    urls = page.eval_on_selector_all("main [data-modal-url]", "els => els.filter(e => e.checkVisibility()).map(e => e.dataset.modalUrl)")
    for url in dict.fromkeys(urls):
        kind = (who, width, re.sub(r"\d+", "N", url.split("?")[0]))
        if kind in opened:
            continue
        opened.add(kind)
        try:
            page.locator(f'main [data-modal-url="{url}"]').first.click(timeout=3000)
            page.wait_for_selector(".peek.open", timeout=5000)
            page.wait_for_timeout(500)
        except Exception:
            print(f"  window {url} on {path} at {width}px didn't open")
            page.keyboard.press("Escape")
            continue
        scan(page, found, who, width, f"{path} › window {url}")
        name = re.sub(r"[^\w]+", "_", url.strip("/"))
        (shots / who.split("@")[0] / str(width) / "windows").mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(shots / who.split("@")[0] / str(width) / "windows" / f"{name}.png"))
        page.keyboard.press("Escape")
        page.wait_for_timeout(250)


def sweep(base: str, people: list[str], limit: int, widths: tuple = WIDTHS, windows: bool = False) -> dict:
    found = defaultdict(list)
    shots = ROOT / "private" / "layout-sweep"
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for who in people:
            ctx = browser.new_context(viewport={"width": 1440, "height": 900})
            page = ctx.new_page()
            page.goto(f"{base}/dev/login?as={who}")
            paths = pages_from(page, base, "/", limit)
            print(f"{who}: {len(paths)} pages")
            opened = set() if windows else None  # (each kind of window once per person and width)
            for width in widths:
                page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
                for i, path in enumerate(paths):
                    try:
                        page.goto(base + path, wait_until="domcontentloaded")
                    except Exception:
                        print(f"  skipped {path} at {width}px (didn't load)")
                        continue
                    page.wait_for_timeout(400)
                    scan(page, found, who, width, path)
                    name = re.sub(r"[^\w]+", "_", path.strip("/")) or "home"
                    (shots / who.split("@")[0] / str(width)).mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(shots / who.split("@")[0] / str(width) / f"{name}.png"), full_page=True)
                    tabs = page.locator("main [role=tab]:visible")
                    for k in range(tabs.count()):
                        tab = tabs.nth(k)
                        label = tab.inner_text().split("\n")[0].strip()
                        tab.click(timeout=3000)
                        page.wait_for_timeout(150)
                        scan(page, found, who, width, f"{path} › {label}")
                    if i == 0:  # the menu bar's menus, once per width
                        for opener in page.locator(".topbar [data-menu]:visible").all():
                            opener.click()
                            page.wait_for_timeout(600)
                            scan(page, found, who, width, f"menu {opener.get_attribute('data-menu')}")
                            page.mouse.click(5, 300)
                    if opened is not None:
                        open_windows(page, found, who, width, path, opened, shots)
                    if path.endswith("/battle") and page.locator(".head-add:visible").count():
                        page.locator(".head-add:visible").first.click()
                        page.wait_for_selector(".peek.open", timeout=4000)
                        page.wait_for_timeout(400)
                        scan(page, found, who, width, f"{path} › + Add panel")
                        page.keyboard.press("Escape")
            ctx.close()
        browser.close()
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--as", dest="people", action="append", required=True, help="an email the dev login accepts (repeat)")
    ap.add_argument("--limit", type=int, default=80, help="pages per person")
    ap.add_argument("--windows", action="store_true", help="also open every window each page opens (data-modal-url)")
    ap.add_argument("--widths", default=",".join(map(str, WIDTHS)), help="comma-separated, e.g. 375,768 for the weekly phone sweep")
    args = ap.parse_args()
    found = sweep(args.base, args.people, args.limit, tuple(int(w) for w in args.widths.split(",") if w.strip()),
                  args.windows)
    if not found:
        print("Nothing scrolls sideways, spills, wraps, overlaps or is covered.")
        return
    for (kind, where), hits in sorted(found.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        widths = sorted({w for _, w, _, _ in hits})
        pages = sorted({p for _, _, p, _ in hits})
        print(f"\n{kind}: {where}\n  widths {widths} · {len(pages)} page(s): {', '.join(pages[:4])}{' …' if len(pages) > 4 else ''}\n  {hits[0][3]}")


if __name__ == "__main__":
    main()
