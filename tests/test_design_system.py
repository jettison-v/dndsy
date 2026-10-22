"""The design system's guardrail (roadmap step 9, Brett 2026-10-22): the stylesheet uses the tokens in
app.css's :root for text sizes, colors and screen widths, so the app doesn't drift again.

Every text size, color and screen width outside :root fails the test. When something truly needs a new
value, add a token to :root (and DESIGN.md › Visual system) on purpose. Sizes in em are allowed: they
scale a parent that already uses a token.
"""

import re
from pathlib import Path

CSS = (Path(__file__).parent.parent / "app" / "static" / "app.css").read_text()
SCREEN_WIDTHS = {640, 641, 900, 901, 1099, 1100}  # phone, tablet, wide (and the pixel either side)



def _without_tokens(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.sub(r":root\s*\{[^}]*\}", "", css)  # the token blocks are where values belong


def offenders() -> dict[str, list[str]]:
    css = _without_tokens(CSS)
    sizes = [v.strip() for v in re.findall(r"font-size:\s*([^;}]+)", css)
             if not re.match(r"(var\(--fs-|inherit|calc\(var\(--fs-|[\d.]+em$)", v.strip())]  # em: relative to a token
    colors = re.findall(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\([^)]*\)", css)
    widths = [w for w in re.findall(r"\((?:max|min)-width:\s*(\d+)px\)", css) if int(w) not in SCREEN_WIDTHS]
    return {"text sizes": sizes, "colors": colors, "screen widths": widths}


def test_stylesheet_uses_the_tokens():
    for kind, values in offenders().items():
        assert not values, f"One-off {kind} in app.css: {sorted(set(values))}. Use a token from :root (docs/DESIGN.md › Visual system), or add one on purpose."


def test_tokens_are_defined_once():
    root = re.search(r":root\s*\{([^}]*)\}", CSS).group(1)
    names = re.findall(r"(--[\w-]+)\s*:", root)
    assert len(names) == len(set(names))
    for t in ("--fs-xs", "--fs-sm", "--fs-md", "--fs-lg", "--fs-xl", "--fs-2xl", "--sp-1", "--r-md", "--control-h"):
        assert t in names
