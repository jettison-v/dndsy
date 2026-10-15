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


# --- Docs API (primary): every tab, exact bullet nesting, all regular images ---

DOCS_URL = "https://docs.googleapis.com/v1/documents/{id}?includeTabsContent=true"
MAX_IMAGE_SIDE = 1568  # larger images cost more for Claude to read without helping


def _runs_text(elements: list[dict], placeholder) -> str:
    out = []
    for el in elements:
        if "textRun" in el:
            out.append(el["textRun"].get("content", ""))
        elif "inlineObjectElement" in el:
            out.append(placeholder(el["inlineObjectElement"]["inlineObjectId"]))
    return "".join(out).replace("\x0b", " ").rstrip("\n")


def docs_json_to_text(doc: dict) -> tuple[str, list[dict]]:
    """Docs API document (with tabs) -> (text, objects in document order).

    Images become "[image: obj-N]"; each object is
    {"name": "obj-N", "kind": "image" | "drawing", "uri": contentUri or None}.
    """
    lines: list[str] = []
    objects: list[dict] = []

    def walk(tabs: list[dict], depth: int):
        for tab in tabs:
            dtab = tab.get("documentTab", {})
            inline = dtab.get("inlineObjects", {})
            positioned = dtab.get("positionedObjects", {})

            def placeholder(obj_id, table=inline, key="inlineObjectProperties"):
                props = table.get(obj_id, {}).get(key, {}).get("embeddedObject", {})
                name = f"obj-{len(objects) + 1}"
                uri = props.get("imageProperties", {}).get("contentUri")
                objects.append({"name": name, "kind": "image" if uri else "drawing", "uri": uri})
                return f" [image: {name}] "

            lines.append(f"\n{'#' * (1 + depth)} {tab.get('tabProperties', {}).get('title', '')}")
            for block in dtab.get("body", {}).get("content", []):
                if "paragraph" in block:
                    p = block["paragraph"]
                    text = _runs_text(p.get("elements", []), placeholder)
                    for pid in p.get("positionedObjectIds", []):
                        text += placeholder(pid, positioned, "positionedObjectProperties")
                    if not text.strip():
                        continue
                    style = p.get("paragraphStyle", {}).get("namedStyleType", "")
                    if style.startswith("HEADING_"):
                        text = "#" * min(6, 1 + depth + int(style[-1])) + " " + text.strip()
                    elif style == "TITLE":
                        text = "#" * (1 + depth) + " " + text.strip()
                    elif "bullet" in p:
                        text = "  " * p["bullet"].get("nestingLevel", 0) + "- " + text.strip()
                    lines.append(text)
                elif "table" in block:
                    for row in block["table"].get("tableRows", []):
                        cells = []
                        for cell in row.get("tableCells", []):
                            parts = [
                                _runs_text(c["paragraph"].get("elements", []), placeholder).strip()
                                for c in cell.get("content", [])
                                if "paragraph" in c
                            ]
                            cells.append(" ".join(x for x in parts if x))
                        lines.append("| " + " | ".join(cells) + " |")
            walk(tab.get("childTabs", []), depth + 1)

    walk(doc.get("tabs", []), 0)
    return "\n".join(lines).strip() + "\n", objects


def shrink_image(content_type: str, data: bytes) -> tuple[str, bytes]:
    """Resize to at most MAX_IMAGE_SIDE px; keep whichever encoding is smaller."""
    from PIL import Image

    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return content_type, data
    if max(img.size) > MAX_IMAGE_SIDE:
        img.thumbnail((MAX_IMAGE_SIDE, MAX_IMAGE_SIDE))
    has_alpha = img.mode in ("RGBA", "LA") or "transparency" in img.info
    buf = io.BytesIO()
    if has_alpha or content_type == "image/png":
        img.save(buf, "PNG", optimize=True)
        candidate = ("image/png", buf.getvalue())
        if not has_alpha:
            jbuf = io.BytesIO()
            img.convert("RGB").save(jbuf, "JPEG", quality=85)
            if len(jbuf.getvalue()) < len(candidate[1]) * 0.6:  # photos: JPEG wins big
                candidate = ("image/jpeg", jbuf.getvalue())
    else:
        img.convert("RGB").save(buf, "JPEG", quality=85)
        candidate = ("image/jpeg", buf.getvalue())
    return candidate if len(candidate[1]) < len(data) else (content_type, data)


def export_image_order(export: "ExportedDoc") -> list[str]:
    """Image file names in the order they appear in an export's text."""
    return re.findall(r"\[image: ([^\]]+)\]", export.text)
