"""The design system's guardrail (roadmap step 9, Brett 2026-10-22): the stylesheet uses the tokens in
app.css's :root for text sizes, colors and screen widths, so the app doesn't drift again.

Every text size, color and screen width outside :root fails the test. When something truly needs a new
value, add a token to :root (and DESIGN.md › Visual system) on purpose. Sizes in em are allowed: they
scale a parent that already uses a token.
"""

import re
from pathlib import Path

CSS = (Path(__file__).parent.parent / "app" / "static" / "app.css").read_text()
TEMPLATES = Path(__file__).parent.parent / "app" / "templates"
SCREEN_WIDTHS = {640, 641, 900, 901, 999, 1000, 1099, 1100, 1200, 1240, 1241, 1360}  # phone, tablet, wide (and the pixel either side); the menu bar's
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


def test_every_count_is_the_one_count():
    """One way for each thing (CLAUDE.md): a number beside a tab, heading or See all link is `count_pill` (_lists.html),
    never a hand-made `<span class="count">`, so the Count's look changes in one place (Battle and Sheet, Brett's note
    84, Nov 17). A count a script keeps current keeps the class and says so here."""
    live = {"your_notes.html", "_lists.html", "design.html"}  # (Your notes' tabs, the Filters fold, the design page's samples)
    made = [f"{p.name}:{n}" for p in (Path(__file__).parent.parent / "app" / "templates").rglob("*.html") if p.name not in live
            for n, line in enumerate(p.read_text().splitlines(), 1) if re.search(r'class="count[" ]', line)]
    assert not made, f"Use count_pill(n) from _lists.html: {made}"


def test_the_design_system_draws_either_mode_and_finds_a_piece(admin):
    """Brett's pick DS1 (docs/mockups/backstage-round-4/, Nov 25): a Table · Backstage switch, sizes read from the page as
    drawn, a search, and every section in the jump row."""
    import re

    page = admin.get("/manage/design").text
    assert 'data-ds-mode="table"' in page and 'data-ds-mode="backstage"' in page and "data-ds-px" in page
    assert 'class="ds-find"' in page
    jump = page.split("data-ds-jump")[1].split("</nav>")[0]
    sections = set(re.findall(r'<section class="section" id="([a-z-]+)"', page))
    assert sections <= set(re.findall(r'href="#([a-z-]+)"', jump))


# Windows still to move onto the one window (Roadmap item 47, Brett's pick W1 A, Nov 25): the work left, which may only
# shrink. A window that moves leaves this list; a new window is built from _window.html from its first day.
WINDOWS_TO_MOVE = {
    "_brief.html",
    "_check_numbers.html",
    "_dice_picker.html",
    "_email_settings.html",
    "_hp_window.html",
    "_item_browser.html",
    "_note_panel.html",
    "_panel_detail.html",
    "_panel_options.html",
    "_panel_vital.html",
    "_peek.html",
    "_picture_window.html",
    "_roll_checks.html",
    "_scene_panel.html",
    "_token_panel.html",
    "_trophy_view.html",
}


def test_every_window_is_the_one_window():
    """Roadmap item 47 (Brett, Nov 25: "fix these holistically"): a window's head, body and foot come from _window.html,
    so Save sits in its foot and the window fits what's in it, everywhere. Those still to move are listed above."""
    hand_made = {p.name for p in TEMPLATES.glob("*.html") if 'class="peek-head"' in p.read_text() and p.name != "_window.html"}
    assert not hand_made - WINDOWS_TO_MOVE, f"A window built by hand: build it from _window.html's window(): {sorted(hand_made - WINDOWS_TO_MOVE)}"
    assert not WINDOWS_TO_MOVE - hand_made, f"Moved onto the one window: take it off WINDOWS_TO_MOVE: {sorted(WINDOWS_TO_MOVE - hand_made)}"


def test_a_window_on_the_one_window_opens_and_closes_its_own_boxes():
    """The review of #530: a window moved onto window() kept a stray </div> and an unclosed foot inside its body (the
    design system's sample panel), which drew the rest of its page inside the window. Each one's boxes balance."""
    for p in TEMPLATES.glob("*.html"):
        text = p.read_text()
        if 'import window %}' in text and "{% call window(" in text:
            assert text.count("<div") == text.count("</div>"), f"{p.name}: its <div>s don't close"
