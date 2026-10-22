"""The design system's guardrail (roadmap step 9, Brett 2026-10-22): the stylesheet uses the tokens in
app.css's :root for text sizes, colors and screen widths, so the app doesn't drift again.

The visual passes are still moving the older rules onto the tokens, so for now this is a ratchet: each
count must match its baseline exactly. When you move rules onto tokens, lower the baseline in the same
commit; a new one-off value fails the test. The baselines reach 0 at the end of step 9. When something
truly needs a new value, add a token to :root (and DESIGN.md) on purpose.
"""

import re
from pathlib import Path

CSS = (Path(__file__).parent.parent / "app" / "static" / "app.css").read_text()
SCREEN_WIDTHS = {640, 900, 1100, 1099}  # phone, tablet, wide (and just below wide)

BASELINE = {"text sizes": 215, "colors": 68, "screen widths": 24}


def _without_tokens(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.sub(r":root\s*\{[^}]*\}", "", css)  # the token blocks are where values belong


def offenders() -> dict[str, list[str]]:
    css = _without_tokens(CSS)
    sizes = [v.strip() for v in re.findall(r"font-size:\s*([^;}]+)", css)
             if not re.match(r"(var\(--fs-|inherit|calc\(var\(--fs-)", v.strip())]
    colors = re.findall(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\([^)]*\)", css)
    widths = [w for w in re.findall(r"\((?:max|min)-width:\s*(\d+)px\)", css) if int(w) not in SCREEN_WIDTHS]
    return {"text sizes": sizes, "colors": colors, "screen widths": widths}


def test_stylesheet_uses_the_tokens():
    found = offenders()
    for kind, values in found.items():
        n, base = len(values), BASELINE[kind]
        assert n <= base, (f"{n - base} new one-off {kind} in app.css (e.g. {values[-1]}). Use a token from :root "
                           f"(docs/DESIGN.md › Visual system), or add one on purpose.")
        assert n == base, f"Fewer one-off {kind} now ({n}): lower BASELINE['{kind}'] to {n} in this test."


def test_tokens_are_defined_once():
    root = re.search(r":root\s*\{([^}]*)\}", CSS).group(1)
    names = re.findall(r"(--[\w-]+)\s*:", root)
    assert len(names) == len(set(names))
    for t in ("--fs-xs", "--fs-sm", "--fs-md", "--fs-lg", "--fs-xl", "--fs-2xl", "--sp-1", "--r-md", "--control-h"):
        assert t in names
