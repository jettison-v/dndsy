"""A UI and UX scan (docs/DESIGN.md; Brett, 2026-11-02: before the VTT, everything checked for consistency): every page
askdnd links to, as each person given, at a phone's width and a desktop's, with every kind of window, modal and side
panel opened once. For each it keeps a screenshot (private/ui-scan/, gitignored) and what the layout check finds, plus
an inventory of how the parts that should look and work the same are built: filter chips (their order and which one
starts selected), notes and their toggles, marks of changes on their way to D&D Beyond, and buttons inside tiles.

Against the local server on the local copy of beta (the dev login), nothing is changed: it only opens things.
    uv run python scripts/ui_scan.py                      # admin, dm, player at 375 and 1280
    uv run python scripts/ui_scan.py --as player --width 375
The inventory goes to private/ui-scan/inventory.json; scripts/layout_sweep.py stays the quicker check of pages alone."""

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parent))
from layout_sweep import CHECK, ROOT, pages_from

OUT = ROOT / "private" / "ui-scan"
OPENERS = "[data-modal-url]:visible, [data-use-url]:visible, [data-panel-url]:visible"

# How each part is built on the page as it stands (read, never clicked)
INVENTORY = r"""() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'; };
  const text = el => (el.textContent || '').trim().replace(/\s+/g, ' ');
  const where = el => { const bits = []; for (let e = el; e && e !== document.body && bits.length < 4; e = e.parentElement) {
      const t = e.getAttribute('data-tour') || e.id || (e.classList[0] || ''); if (t) bits.unshift(t); } return bits.join(' › '); };
  const out = {filters: [], toggles: [], notes: [], sync: [], tiles: [], windows: []};
  for (const g of document.querySelectorAll('.chips, [role=tablist], .seg, .row.tight')) {
    if (!vis(g)) continue;
    const bs = [...g.querySelectorAll(':scope > button, :scope > a, :scope > label')].filter(vis);
    if (bs.length < 2) continue;
    const on = bs.map(b => b.classList.contains('on') || ['aria-pressed', 'aria-selected', 'aria-current'].some(a => ['true', 'page'].includes(b.getAttribute(a))) || !!b.querySelector('input:checked'));
    out.filters.push({kind: g.getAttribute('role') || g.className, where: where(g), labels: bs.map(b => text(b).slice(0, 28)), on});
  }
  for (const l of document.querySelectorAll('label')) {
    const box = l.querySelector('input[type=checkbox]');
    if (box && vis(l) && /note|full|detail|more|all/i.test(text(l))) out.toggles.push({where: where(l), text: text(l).slice(0, 40), checked: box.checked});
  }
  const notes = {};
  for (const n of document.querySelectorAll('.ls-note, .note-full, [class*=note]')) if (vis(n)) { const k = n.className.split(' ')[0] + ' in ' + where(n.parentElement).split(' › ').slice(-2).join(' › '); notes[k] = (notes[k] || 0) + 1; }
  out.notes = Object.entries(notes).map(([k, n]) => ({kind: k, count: n}));
  const sync = {};
  for (const s of document.querySelectorAll('[data-sync], .sync, [class*=sync], [title*="D&D Beyond"]')) if (vis(s)) {
    const k = `${s.tagName.toLowerCase()}.${[...s.classList].join('.')}[data-sync=${s.getAttribute('data-sync') || ''}] "${text(s).slice(0, 12)}" title="${(s.getAttribute('title') || '').slice(0, 50)}"`;
    sync[k] = (sync[k] || 0) + 1; }
  out.sync = Object.entries(sync).map(([k, n]) => ({kind: k, count: n}));
  for (const t of document.querySelectorAll('[class*=tile], .stat, .num')) {
    if (!vis(t)) continue;
    const bs = [...t.querySelectorAll('button, a.btn')].filter(vis);
    if (!bs.length) continue;
    const tr = t.getBoundingClientRect();
    const lines = new Set(bs.map(b => Math.round(b.getBoundingClientRect().top))).size;
    const out_of = bs.some(b => { const r = b.getBoundingClientRect(); return r.right > tr.right + 1 || r.left < tr.left - 1 || r.bottom > tr.bottom + 1; });
    const wrapped = bs.some(b => b.getBoundingClientRect().height > 2 * parseFloat(getComputedStyle(b).lineHeight || '20') + 8);
    out.tiles.push({where: where(t), cls: t.className, buttons: bs.map(b => text(b).slice(0, 14)), rows: lines, spills: out_of, wrapped, width: Math.round(tr.width)});
  }
  for (const w of document.querySelectorAll('.peek.open, .roll-win, dialog[open], .modal.open')) if (vis(w)) {
    const r = w.getBoundingClientRect();
    out.windows.push({cls: w.className, title: text(w.querySelector('h2, h3, .rw-title') || w).slice(0, 40), width: Math.round(r.width), height: Math.round(r.height)});
  }
  return out;
}"""


def kind_of(url: str) -> str:
    """One opener per kind: ids and values collapsed, so 40 spells' panels count once."""
    path, _, query = url.partition("?")
    keys = ",".join(sorted(k.split("=")[0] for k in query.split("&") if k)) if query else ""
    return re.sub(r"\d+", "N", path) + (f"?{keys}" if keys else "")


def shot(page, folder: Path, name: str) -> str:
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{re.sub(r'[^\w]+', '_', name).strip('_')[:90] or 'home'}.png"
    page.screenshot(path=str(f), full_page=False)
    return str(f.relative_to(OUT))


def close_windows(page) -> None:
    for _ in range(3):
        if not page.locator(".peek.open, .roll-win:visible, dialog[open]").count():
            return
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)


def scan(base: str, people: list[str], widths: list[int], limit: int, only: list[str] | None = None) -> dict:
    found = {"pages": [], "windows": [], "layout": defaultdict(list)}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for who in people:
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, timezone_id="America/Los_Angeles")
            ctx.add_init_script("localStorage.setItem('askdnd.rollsAnim', 'off')")
            page = ctx.new_page()
            page.goto(f"{base}/dev/login" + ("" if who == "admin" else f"?as={who}"))
            paths = only or pages_from(page, base, "/", limit)
            print(f"{who}: {len(paths)} pages", flush=True)
            for width in widths:
                page.set_viewport_size({"width": width, "height": 900 if width > 640 else 812})
                opened, folder = set(), OUT / who / str(width)
                for path in paths:
                    try:
                        page.goto(base + path, wait_until="domcontentloaded")
                        page.wait_for_timeout(500)
                    except Exception:
                        continue
                    found["pages"].append({"who": who, "width": width, "path": path, "shot": shot(page, folder, path),
                                           **page.evaluate(INVENTORY)})
                    for p in page.evaluate(CHECK, {"rows": True}):
                        found["layout"][f"{p['kind']}: {p['where']}"].append(f"{who} {width} {path}: {p['detail'][:120]}")
                    tabs = page.locator("main [role=tab]:visible")
                    for k in range(1, tabs.count()):  # (the first is the page as it opened)
                        try:
                            label = tabs.nth(k).inner_text().split("\n")[0].strip()
                            tabs.nth(k).click(timeout=3000)
                            page.wait_for_timeout(300)
                            found["pages"].append({"who": who, "width": width, "path": f"{path} › {label}",
                                                   "shot": shot(page, folder, f"{path} {label}"), **page.evaluate(INVENTORY)})
                        except Exception:
                            pass
                    if tabs.count() > 1:
                        tabs.first.click(timeout=3000)
                    openers = page.locator(OPENERS)
                    todo = []
                    for k in range(min(openers.count(), 200)):
                        el = openers.nth(k)
                        url = el.get_attribute("data-modal-url") or el.get_attribute("data-use-url") or el.get_attribute("data-panel-url") or ""
                        kind = kind_of(url)
                        if kind not in opened:
                            opened.add(kind)
                            todo.append((url, kind))
                    for url, kind in todo:
                        try:
                            sel = f'[data-modal-url="{url}"], [data-use-url="{url}"], [data-panel-url="{url}"]'
                            el = page.locator(sel).locator("visible=true").first
                            label = (el.inner_text(timeout=1500) or el.get_attribute("aria-label") or el.get_attribute("title") or "").strip()[:30]
                            el.click(timeout=3000)
                            page.wait_for_timeout(900)
                            name = f"{path} -- {kind}"
                            found["windows"].append({"who": who, "width": width, "from": path, "kind": kind, "label": label,
                                                     "shot": shot(page, folder, name), **page.evaluate(INVENTORY)})
                            for p in page.evaluate(CHECK, {"rows": True}):
                                found["layout"][f"{p['kind']}: {p['where']}"].append(f"{who} {width} {name}: {p['detail'][:120]}")
                        except Exception as e:
                            print(f"  couldn't open {kind} on {path}: {type(e).__name__}", flush=True)
                        close_windows(page)
                print(f"  {width}px: {len(opened)} kinds of window", flush=True)
            ctx.close()
        browser.close()
    found["layout"] = dict(found["layout"])
    return found


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--as", dest="people", action="append", help="admin, dm, player or an email the dev login accepts (repeat)")
    ap.add_argument("--width", dest="widths", action="append", type=int, help="repeat; 375 and 1280 when none")
    ap.add_argument("--limit", type=int, default=80, help="pages per person")
    ap.add_argument("--path", dest="paths", action="append", help="only these pages (repeat), e.g. a test campaign's character")
    ap.add_argument("--out", default="inventory.json")
    args = ap.parse_args()
    found = scan(args.base, args.people or ["admin", "dm", "player"], args.widths or [375, 1280], args.limit, args.paths)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / args.out).write_text(json.dumps(found, indent=1))
    print(f"{len(found['pages'])} pages, {len(found['windows'])} windows, {len(found['layout'])} layout findings: {OUT / args.out}")


if __name__ == "__main__":
    main()
