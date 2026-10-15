"""Render stored Markdown (with our HTML tables) to safe HTML for display."""

import re
from collections.abc import Callable

import nh3
from markdown_it import MarkdownIt

_md = MarkdownIt("commonmark", {"html": True, "breaks": False}).enable("table")

ALLOWED_TAGS = {
    "p", "br", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em", "b", "i",
    "code", "pre", "blockquote", "hr", "table", "thead", "tbody", "tr", "th", "td", "img", "a",
}
ALLOWED_ATTRS = {"td": {"colspan", "rowspan"}, "th": {"colspan", "rowspan"}, "img": {"src", "alt"}, "a": {"href"}}
IMAGE = re.compile(r"\[image: ([^\]]+)\]")


def markdown_to_html(text: str, image_url: Callable[[str], str | None]) -> str:
    """Markdown -> sanitized HTML. `image_url(name)` maps placeholders to URLs."""
    html = nh3.clean(
        _md.render(text),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        url_schemes={"http", "https"},
        link_rel="noopener noreferrer",
    )

    def swap(m):
        url = image_url(m.group(1))
        return f'<img src="{url}" alt="">' if url else '<span class="muted">(image not available)</span>'

    return IMAGE.sub(swap, html)
