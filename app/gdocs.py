"""Turn a Google Docs HTML export (zip with images) into text + images.

Drive's "export as zipped HTML" renders drawings (e.g. a family tree) as
images too, which the Docs API alone does not.
"""

import hashlib
import html
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
    """Docs API document (with tabs) -> (Markdown, objects in document order).

    Headings, nested bullet lists and paragraphs become Markdown. Tables become
    HTML <table> blocks so merged cells and bullets inside cells survive.
    Images become "[image: obj-N]"; each object is
    {"name": "obj-N", "kind": "image" | "drawing", "uri": contentUri or None}.
    """
    blocks: list[tuple[str, str]] = []  # (kind, markdown); kind "li" blocks join tightly
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

            def para_text(p: dict) -> str:
                text = _runs_text(p.get("elements", []), placeholder)
                for pid in p.get("positionedObjectIds", []):
                    text += placeholder(pid, positioned, "positionedObjectProperties")
                return " ".join(text.split())

            title = tab.get("tabProperties", {}).get("title", "")
            blocks.append(("h", f"{'#' * min(6, 1 + depth)} {title}"))
            for block in dtab.get("body", {}).get("content", []):
                if "paragraph" in block:
                    p = block["paragraph"]
                    text = para_text(p)
                    if not text:
                        continue
                    style = p.get("paragraphStyle", {}).get("namedStyleType", "")
                    if style.startswith("HEADING_") or style == "TITLE":
                        level = 1 + depth + (int(style[-1]) if style.startswith("HEADING_") else 0)
                        blocks.append(("h", f"{'#' * min(6, level)} {text}"))
                    elif "bullet" in p:
                        blocks.append(("li", "  " * p["bullet"].get("nestingLevel", 0) + "- " + text))
                    else:
                        blocks.append(("p", text))
                elif "table" in block:
                    blocks.append(("table", table_html(block["table"], para_text)))
            walk(tab.get("childTabs", []), depth + 1)

    walk(doc.get("tabs", []), 0)
    out = []
    for i, (kind, md) in enumerate(blocks):
        if i:
            out.append("\n" if kind == "li" and blocks[i - 1][0] == "li" else "\n\n")
        out.append(md)
    return "".join(out).strip() + "\n", objects


def table_html(table: dict, para_text) -> str:
    """A Docs table as a compact HTML table, honoring merged cells."""
    rows_html = []
    covered: dict[tuple[int, int], bool] = {}  # (row, col) hidden by a rowSpan above
    for r, row in enumerate(table.get("tableRows", [])):
        cells_html, skip = [], 0
        for c, cell in enumerate(row.get("tableCells", [])):
            if skip:  # placeholder cells after a merged (column-spanning) cell
                skip -= 1
                continue
            if covered.get((r, c)):
                continue
            style = cell.get("tableCellStyle", {})
            colspan, rowspan = style.get("columnSpan", 1) or 1, style.get("rowSpan", 1) or 1
            skip = colspan - 1
            for dr in range(1, rowspan):
                for dc in range(colspan):
                    covered[(r + dr, c + dc)] = True
            parts = []
            for item in cell.get("content", []):
                if "paragraph" not in item:
                    continue
                p = item["paragraph"]
                text = para_text(p)
                if not text:
                    continue
                if "bullet" in p:
                    text = "&nbsp;&nbsp;" * p["bullet"].get("nestingLevel", 0) + "• " + html.escape(text)
                else:
                    text = html.escape(text)
                parts.append(text)
            attrs = (f' colspan="{colspan}"' if colspan > 1 else "") + (f' rowspan="{rowspan}"' if rowspan > 1 else "")
            content = "<br>".join(parts)
            # Short label cells ("When", "Pros", "Cons") read best as headers.
            is_label = len(parts) == 1 and len(content.split()) <= 2 and not re.search(r"[\d•:]", content)
            tag = "th" if is_label else "td"
            cells_html.append(f"<{tag}{attrs}>{content}</{tag}>")
        rows_html.append("<tr>" + "".join(cells_html) + "</tr>")
    return "<table>\n" + "\n".join(rows_html) + "\n</table>"


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
