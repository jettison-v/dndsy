"""The Chrome Web Store screenshot (1280×800): the extension's own panel (ddb.js) with made-up numbers for the test
character, beside a caption. No real page and nothing of D&D Beyond's own.

    uv run python -m scripts.extension_screenshot

Writes private/extension/listing-screenshot.png.
"""

from pathlib import Path
from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent.parent
ddb_js = (root / "extension/askdnd-bridge/ddb.js").read_text()
out = root / "private/extension/listing-screenshot.png"
html = """<!doctype html><html><head><meta charset=utf-8><style>
body{margin:0;width:1280px;height:800px;background:#0f1113;font-family:Inter,system-ui,sans-serif;color:#ebe7df;overflow:hidden}
.cap{position:absolute;left:400px;top:0;right:0;bottom:0;display:flex;flex-direction:column;justify-content:center;padding:0 90px;gap:22px}
.cap h1{font:600 54px/1.1 Georgia,serif;color:#fff;margin:0}
.cap p{font-size:24px;line-height:1.5;color:#a29d93;margin:0;max-width:640px}
.cap b{color:#5bbf7f}
</style></head><body><div class=cap><h1>Your D&amp;D Beyond sheet and askdnd, in step.</h1>
<p>Change hit points or drink a potion in askdnd and it's made on your sheet, as you. Change your sheet and askdnd shows it within seconds.</p>
<p><b>&#9679;</b> askdnd counts a change only once D&amp;D Beyond has it.</p></div></body></html>"""
stub = """window.chrome = {runtime: {getURL: () => 'about:blank', sendMessage: () => {}, onMessage: {addListener: f => { window.__listen = f; }}}};"""
state = {"character": {"name": "Vi", "id": 12}, "hp": {"current": 61, "max": 73}, "to_make": [],
         "changes": [],
         "log": [{"state": "live", "text": "Vi: drank a Potion of Healing (+7 hit points)"},
                 {"state": "seen", "text": "Vi (on D&D Beyond): 1st-level slots 1 used → 2 used"},
                 {"state": "live", "text": "Vi: Heroic Inspiration on"},
                 {"state": "seen", "text": "Vi (on D&D Beyond): hit points 73 → 54"}]}

def main() -> None:
    (root / "private/extension").mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_page(viewport={"width": 1280, "height": 800})
        page.route('https://shot.example/', lambda r: r.fulfill(body=html, content_type='text/html'))
        page.goto('https://shot.example/')
        page.add_script_tag(content=stub)
        page.add_script_tag(content=ddb_js)
        page.evaluate("s => window.__listen({type: 'panel-state', state: s, askdnd: 'https://beta.askdnd.ai'}, {}, () => {})", state)
        page.wait_for_timeout(300)
        page.screenshot(path=str(out))
        b.close()
    print(out)


if __name__ == "__main__":
    main()
