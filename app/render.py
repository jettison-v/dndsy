"""Render stored Markdown (with our HTML tables) to safe HTML for display."""

import re
from collections.abc import Callable

import nh3
from markdown_it import MarkdownIt
from markupsafe import Markup, escape

_md = MarkdownIt("commonmark", {"html": True, "breaks": False, "linkify": True}).enable(["table", "linkify"])

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
        set_tag_attribute_values={"a": {"target": "_blank"}},
    )

    def swap(m):
        url = image_url(m.group(1))
        return f'<img src="{url}" alt="">' if url else '<span class="muted">(image not available)</span>'

    return IMAGE.sub(swap, html)


def word_diff(old: str, new: str) -> Markup:
    """A marked-up edit: `new` shown against `old`, word by word, with <del> for removed words and <ins> for added
    ones. Used wherever Claude proposes a change to text someone wrote (content workflows step 3)."""
    import difflib

    token = re.compile(r"\s+|[\w'’-]+|[^\w\s]")  # spaces, words, and each punctuation mark on its own
    a, b = token.findall(old or ""), token.findall(new or "")
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(escape("".join(a[i1:i2])))
            continue
        gone, added = "".join(a[i1:i2]), "".join(b[j1:j2])
        if gone.strip():
            space = " " if not added and gone[:1].isspace() else ""  # keep words apart where only a deletion is
            out.append(Markup("{}<del>{}</del>").format(space, gone.strip()))
        if added.strip():  # spaces around a change stay outside the mark
            lead, core = added[: len(added) - len(added.lstrip())], added.strip()
            out.append(escape(lead) + Markup("<ins>{}</ins>").format(core) + escape(added[len(lead) + len(core):]))
        elif added:
            out.append(escape(added))
    return Markup("").join(out)
