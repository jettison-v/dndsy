"""Receive pages of Brett's own D&D Beyond books and save them under private/books/.

private/ is git-ignored: the copies stay on this Mac and never go to GitHub,
Railway or the database. Listens on 127.0.0.1 only. Started by hand while saving:

    uv run python scripts/book_receiver.py

then, in the in-app browser (signed in to D&D Beyond), pages are sent here. The
in-app browser only lets a website reach this Mac by opening an address, so a
batch arrives as GET /save?z=<base64url of gzipped JSON>, the JSON being a list of
{"book": "phb-2024", "slug": "rules-glossary", "title": "...", "text": "..."} or
{"book": "mm-2024", "slug": "monsters", "json": [...]}. POST with the same JSON also works.
"""

import base64
import gzip
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent / "private" / "books"
PORT = 8799
SAFE = re.compile(r"^[a-z0-9-]{1,80}$")


class Handler(BaseHTTPRequestHandler):
    def handle_one_request(self):
        """As the standard one, but allowing the long addresses a batch arrives in."""
        self.raw_requestline = self.rfile.readline(4_000_000)
        if not self.raw_requestline:
            self.close_connection = True
            return
        if not self.parse_request():
            return
        method = getattr(self, "do_" + self.command, None)
        if method is None:
            self.send_error(501)
            return
        method()
        self.wfile.flush()

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "https://www.dndbeyond.com")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def _save(self, body: dict) -> dict:
        book, slug = body["book"], body["slug"]
        if not (SAFE.match(book) and SAFE.match(slug)):
            raise ValueError("bad name")
        folder = ROOT / book
        folder.mkdir(parents=True, exist_ok=True)
        if "json" in body:
            path = folder / f"{slug}.json"
            path.write_text(json.dumps(body["json"], ensure_ascii=False, indent=1), encoding="utf-8")
        else:
            path = folder / f"{slug}.md"
            path.write_text(f"# {body.get('title', slug)}\n\nSource: {body.get('url', '')}\n\n{body['text']}\n", encoding="utf-8")
        return {"saved": str(path.relative_to(ROOT)), "bytes": path.stat().st_size}

    def do_GET(self):  # noqa: N802
        try:
            q = parse_qs(urlparse(self.path).query)
            z = q["z"][0]
            items = json.loads(gzip.decompress(base64.urlsafe_b64decode(z + "=" * (-len(z) % 4))))
            saved = [self._save(b) for b in (items if isinstance(items, list) else [items])]
            page = "<!doctype html><title>Saved</title><pre id=saved>" + json.dumps(saved, indent=1) + "</pre>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode())
            print("saved", len(saved), "pages")
        except Exception as e:  # noqa: BLE001
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"<pre id=error>{e}</pre>".encode())

    def do_POST(self):  # noqa: N802
        try:
            raw = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
                raw = parse_qs(raw.decode("utf-8"))["data"][0]  # sent by a form, which the browser allows
            body = json.loads(raw)
            result = self._save(body)
            self.send_response(200)
            self._cors()
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())
        except Exception as e:  # noqa: BLE001
            self.send_response(400)
            self._cors()
            self.end_headers()
            self.wfile.write(str(e).encode())

    def log_message(self, fmt, *args):
        print(getattr(self, "command", ""), getattr(self, "path", "")[:40], args[-2] if len(args) >= 2 else "")  # never the book text


if __name__ == "__main__":
    print(f"Saving to {ROOT} on http://127.0.0.1:{PORT}")
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
