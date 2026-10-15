"""Turn a Google Docs HTML export (zip with images) into text + images.

Drive's "export as zipped HTML" renders drawings (e.g. a family tree) as
images too, which the Docs API alone does not.
"""

import hashlib
import io
import mimetypes
import re
import zipfile
from dataclasses import dataclass, field
from html.parser import HTMLParser

DOC_ID = re.compile(r"/document/d/([A-Za-z0-9_-]{20,})")
EXPORT_URL = "https://www.googleapis.com/drive/v3/files/{id}/export?mimeType=application/zip"
META_URL = "https://www.googleapis.com/drive/v3/files/{id}?fields=name"
MAX_EXPORT_BYTES = 40_000_000


def doc_id_from_url(url_or_id: str) -> str | None:
    s = url_or_id.strip()
    m = DOC_ID.search(s)
    if m:
        return m.group(1)
    return s if re.fullmatch(r"[A-Za-z0-9_-]{20,}", s) else None


@dataclass
class ExportedDoc:
    text: str
    images: dict[str, tuple[str, bytes]] = field(default_factory=dict)  # name -> (type, data)

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256(self.text.encode())
        for name in sorted(self.images):
            h.update(name.encode())
            h.update(hashlib.sha256(self.images[name][1]).digest())
        return h.hexdigest()


class _ToText(HTMLParser):
    BLOCK = {"p", "div", "br", "tr", "table", "ul", "ol"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.line = ""
        self.skip = 0
        self.list_depth = 0
        self.prefix = ""

    def _flush(self):
        text = " ".join(self.line.split())
        if text:
            self.out.append(self.prefix + text)
        self.line, self.prefix = "", ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("style", "script", "head", "title"):
            self.skip += 1
        elif re.fullmatch(r"h[1-6]", tag):
            self._flush()
            self.prefix = "#" * int(tag[1]) + " "
        elif tag in ("ul", "ol"):
            self._flush()
            self.list_depth += 1
        elif tag == "li":
            self._flush()
            self.prefix = "  " * (self.list_depth - 1) + "- "
        elif tag in ("td", "th"):
            self.line += " | "
        elif tag == "img" and a.get("src"):
            self.line += f" [image: {a['src']}] "
        elif tag in self.BLOCK:
            self._flush()

    def handle_endtag(self, tag):
        if tag in ("style", "script", "head", "title"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("ul", "ol"):
            self._flush()
            self.list_depth = max(0, self.list_depth - 1)
        elif tag in ("p", "li", "tr") or re.fullmatch(r"h[1-6]", tag):
            self._flush()

    def handle_data(self, data):
        if not self.skip:
            self.line += data

    def close(self):
        super().close()
        self._flush()


def html_to_text(html: str) -> str:
    parser = _ToText()
    parser.feed(html)
    parser.close()
    return "\n".join(parser.out) + "\n"


def parse_export(zip_bytes: bytes) -> ExportedDoc:
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        names = z.namelist()
        html_name = next((n for n in names if n.lower().endswith(".html")), None)
        if html_name is None:
            raise ValueError("export has no HTML file")
        text = html_to_text(z.read(html_name).decode("utf-8", "replace"))
        images = {}
        for n in names:
            ctype = mimetypes.guess_type(n)[0] or ""
            if ctype.startswith("image/"):
                images[n] = (ctype, z.read(n))
    return ExportedDoc(text=text, images=images)
