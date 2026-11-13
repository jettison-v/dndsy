"""The design system's guardrail (roadmap step 9, Brett 2026-10-22): the stylesheet uses the tokens in
app.css's :root for text sizes, colors and screen widths, so the app doesn't drift again.

Every text size, color and screen width outside :root fails the test. When something truly needs a new
value, add a token to :root (and DESIGN.md › Visual system) on purpose. Sizes in em are allowed: they
scale a parent that already uses a token.
"""

import re
from pathlib import Path

CSS = (Path(__file__).parent.parent / "app" / "static" / "app.css").read_text()
SCREEN_WIDTHS = {640, 641, 900, 901, 999, 1000, 1099, 1100, 1200, 1240, 1360}  # phone, tablet, wide (and the pixel either side); the menu bar's
# collapse order (docs/DESIGN.md › Navigation: 1360 the word askdnd, 1200 your character's name, 1100 the Live pill's short words, 1000 the campaign's name)



def _without_tokens(css: str) -> str:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return re.sub(r":root\s*\{[^}]*\}", "", css)  # the token blocks are where values belong


def offenders() -> dict[str, list[str]]:
    css = _without_tokens(CSS)
    sizes = [v.strip() for v in re.findall(r"font-size:\s*([^;}]+)", css)
             if not re.match(r"(var\(--fs-|inherit|calc\(var\(--fs-|max\(var\(--fs-|[\d.]+em$)", v.strip())]  # em: relative to a token; max: a floor at one
    colors = re.findall(r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?)\([^)]*\)", css)
    # Screen widths in media queries; a list's own width in a container query is its columns' need, not a screen size
    widths = [w for w in re.findall(r"@media[^{]*\((?:max|min)-width:\s*(\d+)px\)", css) if int(w) not in SCREEN_WIDTHS]
    corners = [v.strip() for v in re.findall(r"border-radius:\s*([^;}]+)", css) if re.search(r"\d+px", re.sub(r"\b0(px)?\b", "", v))]
    lifts = [v.strip() for v in re.findall(r"box-shadow:\s*([^;}]+)", css) if re.fullmatch(r"\s*0 \d{2}px \d{2}px var\(--shadow\)\s*", v)]
    return {"text sizes": sizes, "colors": colors, "screen widths": widths, "corners": corners, "shadows": lifts}


def test_every_kind_of_field_is_styled():
    """Oct 31: a number box and a file picker were the browser's own, grey and square, on Manage's pages."""
    types = set()
    for p in (Path(__file__).parent.parent / "app" / "templates").rglob("*.html"):
        types.update(re.findall(r'<input[^>]*\stype="(\w+)"', p.read_text()))
    for t in types - {"hidden", "checkbox", "radio", "range", "submit"}:
        assert f"input[type={t}]" in CSS, f'<input type="{t}"> has no style in app.css'


def test_stylesheet_uses_the_tokens():
    for kind, values in offenders().items():
        assert not values, f"One-off {kind} in app.css: {sorted(set(values))}. Use a token from :root (docs/DESIGN.md › Visual system), or add one on purpose."


def test_tokens_are_defined_once():
    root = re.search(r":root\s*\{([^}]*)\}", CSS).group(1)
    names = re.findall(r"(--[\w-]+)\s*:", root)
    assert len(names) == len(set(names))
    for t in ("--fs-xs", "--fs-sm", "--fs-md", "--fs-lg", "--fs-xl", "--fs-2xl", "--sp-1", "--r-md", "--control-h"):
        assert t in names


def test_pages_use_the_components_not_inline_styles():
    """DESIGN.md › Rules for every page: no inline spacing. Brett, 2026-10-23, for Manage pages; every page since
    2026-10-27 (the spacing helpers in app.css instead). Allowed: a value worked out per item (a diagram's positions,
    its size), and the Design system page, whose samples draw each token."""
    from pathlib import Path

    templates = Path(__file__).resolve().parent.parent / "app" / "templates"
    found = {}
    for p in templates.glob("*.html"):
        if p.name == "design.html":
            continue
        fixed = [v for v in re.findall(r'\sstyle="([^"]*)"', p.read_text()) if "{{" not in v]
        if fixed:
            found[p.name] = fixed
    assert not found, f"Inline styles (use a component or a spacing helper, DESIGN.md › Space): {found}"


def test_every_table_scrolls_in_its_own_frame():
    """A table can be wider than a phone; it scrolls inside .table-scroll, never the whole page (DESIGN.md › Narrow screens)."""
    import re

    templates = Path(__file__).parent.parent / "app" / "templates"
    for f in templates.glob("*.html"):
        for m in re.finditer(r"<table\b", f.read_text()):
            before = f.read_text()[max(0, m.start() - 120):m.start()]
            assert 'class="table-scroll' in before, f"{f.name}: a <table> outside <div class=\"table-scroll\">"


FONTS = {"--sans": "Inter", "--cond": "Roboto Condensed", "--tale-cap": "Cormorant Garamond"}


def test_only_askdnds_three_fonts():
    """A standing rule (Brett, Nov 13, on the design grade's mockup: "limit the number of fonts used to the ones we
    have selected"; docs/DESIGN.md › Fonts): Inter for everything, Roboto Condensed for the logo and small uppercase
    labels, Cormorant Garamond for the tale's flourishes. The serif that quoted answers used was hard to read and is
    gone. A font is set only through these three tokens, and the pages load only these three."""
    root = re.search(r":root\s*\{([^}]*)\}", CSS).group(1)
    families = dict(re.findall(r"(--[\w-]+)\s*:\s*\"?([A-Z][\w ]+?)\"?,", root))
    assert {k: v for k, v in families.items() if k in FONTS or re.search(r"serif|Inter|Garamond|Palatino", v)} == FONTS
    css = _without_tokens(CSS)
    stray = [v.strip() for v in re.findall(r"font-family:\s*([^;}]+)", css) if not re.fullmatch(r"(var\((--sans|--cond|--tale-cap)(, inherit)?\)|inherit)", v.strip())]
    stray += [v.strip() for v in re.findall(r"(?<![-\w])font:\s*([^;}]+)", css)
              if not re.search(r"(var\((--sans|--cond|--tale-cap)\)|inherit)\s*$", v.strip())]
    assert not stray, f"A font outside askdnd's three in app.css: {stray}. Use var(--sans), var(--cond) or var(--tale-cap)."
    app = Path(__file__).parent.parent / "app"
    for p in [*(app / "templates").rglob("*.html"), app / "static" / "app.js"]:
        if "email" in p.parts:
            continue  # an email can't load web fonts: it names Inter with the system's own after it
        text = p.read_text()
        assert not re.search(r"font-family\s*:|(?<![-\w.])font\s*:\s*[^;\"']*\b(serif|sans-serif|monospace)\b", text), f"{p.name} sets a font itself: use the tokens in app.css"
        for link in re.findall(r"fonts\.googleapis\.com/css2\?([^\"']+)", text):
            loaded = {f.replace("+", " ").split(":")[0] for f in re.findall(r"family=([^&]+)", link)}
            assert loaded == set(FONTS.values()), f"{p.name} loads {sorted(loaded)}"
