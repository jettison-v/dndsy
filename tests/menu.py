"""Reading the menu bar from a page's HTML by what things are, not by their words or classes (Nov 13, the test
foundations): a door's menu is `[data-door="account" | "manage" | "admin" | "help" | "more" | "party" | "campaign"]`, each
of its items `[data-item="<key>"]` (a Manage page's key from app/manage.py PAGES, else notes, dice, email, feedback, help,
tour, signout, dm-tools…), and the Live pill says how it stands in `data-tone` (step, via, bad, warn, none). A menu's
wording or order can change without touching the tests that only ask what's in it.

    door(html, "account")   the account menu's HTML ("" when the page has none)
    items(html, "manage")   its item keys, in order
    tone(html)              the Live pill's tone
    topbar(html)            the menu bar's HTML
"""

from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Find(HTMLParser):
    """The first element with `attr` = `value`: its inner HTML, and the data-item keys inside it in order."""

    def __init__(self, attr: str, value: str):
        super().__init__(convert_charrefs=False)
        self.attr, self.value = attr, value
        self.depth, self.found, self.done = 0, False, False
        self.parts: list[str] = []
        self.keys: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.done:
            return
        if not self.found:
            if a.get(self.attr) == self.value:
                self.found, self.depth = True, (0 if tag in VOID else 1)
            return
        self.parts.append(self.get_starttag_text() or "")
        if "data-item" in a:
            self.keys.append(a["data-item"] or "")
        if tag not in VOID:
            self.depth += 1

    def handle_startendtag(self, tag, attrs):
        if self.found and not self.done:
            self.parts.append(self.get_starttag_text() or "")
            if "data-item" in dict(attrs):
                self.keys.append(dict(attrs)["data-item"] or "")

    def handle_endtag(self, tag):
        if not self.found or self.done or tag in VOID:
            return
        self.depth -= 1
        if self.depth <= 0:
            self.done = True
        else:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self.found and not self.done:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def _find(html: str, attr: str, value: str) -> _Find:
    f = _Find(attr, value)
    f.feed(html)
    return f


def door(html: str, key: str) -> str:
    """A door's menu, its inner HTML; "" when the page doesn't offer it."""
    return "".join(_find(html, "data-door", key).parts)


def has_door(html: str, key: str) -> bool:
    return _find(html, "data-door", key).found


def items(html: str, key: str) -> list[str]:
    """The item keys in a door's menu, in order."""
    return _find(html, "data-door", key).keys


def tone(html: str) -> str:
    """The Live pill's tone: step (its own sheet), via (through the DM), bad, warn, none."""
    import re

    m = re.search(r'id="live-pill"[^>]*?data-tone="([a-z]+)"', html) or re.search(r'data-tone="([a-z]+)"', html)
    return m.group(1) if m else ""  # (also from the pill's own HTML, or what follows its id)


def topbar(html: str) -> str:
    return html.split('class="topbar"')[1].split("</header>")[0]
