"""Backstage › Global › Documents (Brett, Nov 6): every page made for askdnd (guides, plans, designs, earlier ones) in one
place, for admins, read from the repo's own copies, so nothing depends on claude.ai to be found or kept.

The list is docs/library.json, the one source (the Roadmap page's table of documents was written from it until the
Roadmap moved into askdnd, Nov 20). A plan (Markdown) is shown in the page; an HTML page or a design's boards open in a sealed
frame: served with a Content-Security-Policy sandbox, so their scripts run without askdnd's origin (no sign-in, no
storage, no requests as you), from an address that carries a signed key good for an hour (the frame's own requests
for a page's pictures and styles can't carry the sign-in), and with no referrer, so the key never leaves askdnd.
"""

import json
import mimetypes
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from markupsafe import Markup

from app import config, web
from app.auth import is_admin
from app.db import get_db
from app.render import markdown_to_html
from app.templating import _static, templates

router = APIRouter()

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
LIBRARY = DOCS / "library.json"
KEY_SECONDS = 3600
# The groups, in order, and what each holds
KINDS = (
    ("guide", "Guides you use", "Kept current: how things work and how to do them"),
    ("plan", "Plans", "What's being built and why, in the order it happens"),
    ("design", "Designs", "Mockups and proposals, with what was chosen and whether it's built"),
    ("earlier", "Earlier and superseded", "Kept for the record; a newer page took over"),
)
# (allow-forms so a mockup's form reaches its own script, its Save my picks; form-action 'none' so no form sends anywhere:
# Brett's round, Nov 18)
SANDBOX = ("sandbox allow-scripts allow-forms allow-popups allow-popups-to-escape-sandbox; form-action 'none'; "
           "default-src 'self' 'unsafe-inline' data: blob:; "
           "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; "
           "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; "
           "img-src 'self' data: blob: https:")


def doc_id(source: str) -> str:
    """A document's address in askdnd: its repo path, as a word (docs/artifacts/recording-to-recap.html → artifacts-recording-to-recap)."""
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"\.(html|md)$", "", source.removeprefix("docs/")).lower()).strip("-")


@cache
def _library(mtime: float) -> tuple[dict, ...]:
    return tuple({**e, "id": doc_id(e["source"])} for e in json.loads(LIBRARY.read_text()))


# Pages Claude sends before their repo copy lands (item 39, scope v7, Nov 24: a page is data, not code, so it reaches
# Brett in seconds, not after a pull request and a deploy; rules.send_page keeps them). The newer copy is the one shown:
# the repo's is as new as this server (a deploy starts a new one), a sent one as new as when it was sent.
BOOT = datetime.now(UTC)
CACHE_SECONDS = 10


def _sent_from_db() -> dict:
    from app.db import SessionLocal, engine

    if engine is None:
        return {"docs": {}, "files": {}}
    with SessionLocal() as db:
        return sent_from(db)


def sent_from(db) -> dict:
    """{"docs": {source: (entry, sent_at)}, "files": {path: sent_at}}: what Claude sent, without the files' bodies."""
    from sqlalchemy import select

    from app.fft.models import FftSentDoc, FftSentFile

    return {"docs": {d.source: (dict(d.entry or {}), d.sent_at) for d in db.scalars(select(FftSentDoc))},
            "files": dict(db.execute(select(FftSentFile.path, FftSentFile.sent_at)).all())}


loader: Callable[[], dict] = _sent_from_db
_cache: dict = {"rows": {"docs": {}, "files": {}}, "at": 0.0}


def invalidate() -> None:
    _cache["at"] = 0.0


def _sent() -> dict:
    if time.monotonic() - _cache["at"] > CACHE_SECONDS:
        try:
            _cache["rows"] = loader()
        except Exception:
            pass  # database unavailable: the repo's pages still open
        _cache["at"] = time.monotonic()
    return _cache["rows"]


def _newer(sent_at) -> bool:
    return sent_at is not None and sent_at > BOOT


def library() -> tuple[dict, ...]:
    """docs/library.json, read again when it changes, with the pages Claude sent: a sent entry newer than the repo's
    takes its place, and one the repo doesn't have yet comes first (the list is newest first)."""
    repo = _library(LIBRARY.stat().st_mtime)
    sent = _sent()["docs"]
    if not sent:
        return repo
    out, seen = [], set()
    for e in repo:
        s = sent.get(e["source"])
        out.append({**s[0], "source": e["source"], "id": e["id"], "sent": True} if s and _newer(s[1]) else e)
        seen.add(e["source"])
    new = sorted(((src, ent, at) for src, (ent, at) in sent.items() if src not in seen), key=lambda x: x[2], reverse=True)
    return tuple([{**ent, "source": src, "id": doc_id(src), "sent": True} for src, ent, _ in new] + out)


def find(did: str) -> dict | None:
    return next((e for e in library() if e["id"] == did), None)


_LINK = re.compile(r"claude\.ai/(?:code/)?artifact/([A-Za-z0-9_-]+)|(docs/[A-Za-z0-9_./-]+\.(?:html|md))")


def linked(*texts: str) -> list[dict]:
    """The pages these words point to (a claude.ai link or a docs/ path), each as it opens inside askdnd: Documents'
    entry, in the order first named (issue 105, Brett's note Nov 23: a Roadmap item's scope named its page but nothing
    opened it). A link that isn't in docs/library.json is left out."""
    out: dict[str, dict] = {}
    for words in texts:
        for m in _LINK.finditer(words or ""):
            art, path = m.group(1), m.group(2)
            e = next((x for x in library() if (art and (x.get("link") or "").rstrip("/").endswith("/" + art)) or (path and x["source"] == path)), None)
            if e is not None and e["id"] not in out:
                out[e["id"]] = {"id": e["id"], "title": e["title"], "status": e.get("status", ""), "href": f"/manage/documents/{e['id']}"}
    return list(out.values())


def safe(rel: str) -> bool:
    """A path under docs/, never outside it and never a hidden file."""
    if not rel or "\\" in rel or rel.startswith("/") or any(part.startswith(".") for part in Path(rel).parts):
        return False
    return (DOCS / rel).resolve().is_relative_to(DOCS)


def inside_docs(rel: str) -> Path | None:
    """A path under docs/ that's in the repo's copy; None otherwise."""
    if not safe(rel):
        return None
    path = (DOCS / rel).resolve()
    return path if path.exists() else None


def _from_sent(rel: str) -> bool:
    """Whether a file is read from what Claude sent: the repo has none, or the sent one is newer."""
    at = _sent()["files"].get(rel)
    if at is None:
        return False
    path = inside_docs(rel)
    return path is None or not path.is_file() or _newer(at)


def read(db, rel: str) -> bytes | None:
    """A file's contents, from the newer copy: Claude's sent one or the repo's."""
    if not safe(rel):
        return None
    if _from_sent(rel):
        from sqlalchemy import select

        from app.fft.models import FftSentFile

        body = db.scalar(select(FftSentFile.body).where(FftSentFile.path == rel))
        if body is not None:
            return bytes(body)
    path = inside_docs(rel)
    return path.read_bytes() if path is not None and path.is_file() else None


def pages_of(entry: dict) -> list[str]:
    """What a document opens to: one file, or a design's boards (its HTML files, the main one first), from the repo's
    copy and what Claude sent."""
    rel = entry["source"].removeprefix("docs/")
    sent = _sent()["files"]
    if rel in sent or ((p := inside_docs(rel)) is not None and p.is_file()):
        return [rel] if safe(rel) else []
    if not safe(rel.rstrip("/")):
        return []
    folder = rel.rstrip("/") + "/"
    found = {p.relative_to(DOCS).as_posix() for p in (DOCS / folder).rglob("*.html")
             if not any(x.startswith(".") for x in p.relative_to(DOCS).parts)} if inside_docs(folder.rstrip("/")) else set()
    found |= {f for f in sent if f.startswith(folder) and f.endswith(".html")}
    return sorted(found, key=lambda f: (Path(f).stem.lower() not in ("main", "index"), f.removeprefix(folder).lower()))


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.SESSION_SECRET or "local", salt="documents")


def file_url(page: str) -> str:
    """The sealed frame's address for one page: a key for the page's own folder (so its pictures and styles load),
    then the page's path."""
    folder, name = page.rsplit("/", 1) if "/" in page else ("", page)
    return f"/manage/documents/f/{_signer().dumps(folder)}/{page}"


@router.get("/manage/documents")
def library_page(request: Request):
    """Every document, in its group, newest first within it; the page's search box finds by title, status and what
    each is (the shared list pieces, the UI review)."""
    _, stop = web.require(request, is_admin, "askdnd's documents are for admins.")
    if stop:
        return stop
    entries = library()
    groups = [(key, name, about, [e for e in entries if e["kind"] == key]) for key, name, about in KINDS]
    return templates.TemplateResponse(request, "manage_documents.html", {"groups": groups, "count": len(entries)})


@router.get("/manage/documents/{did}")
def document_page(request: Request, did: str, page: str = "", part: int = 0, db=Depends(get_db)):
    """One document: a plan in the page, anything else in the sealed frame, a design's boards as tabs. `part=1`: the
    page alone in a window nearly as big as the screen (For you's Open mockup, Brett, Nov 17: "a large modal")."""
    _, stop = web.require(request, is_admin, "askdnd's documents are for admins.")
    if stop:
        return stop
    entry = find(did)
    pages = pages_of(entry) if entry else []
    if not pages:
        return web.not_found(request, "That document isn't in the library.")
    current = next((p for p in pages if p == page), pages[0])  # (one of its own listed pages, never the address's text)
    body = None
    if current.endswith(".md"):
        body = Markup(markdown_to_html((read(db, current) or b"").decode(errors="replace"), lambda _name: None))  # noqa: S704
    if part:  # (a plan written as text too, in the window as itself: it showed the whole page there, unscrollable, Nov 19)
        return templates.TemplateResponse(request, "_document_window.html", {"e": entry, "body": body, "frame": None if body else file_url(current)})
    return templates.TemplateResponse(request, "manage_document.html", {
        "e": entry, "pages": pages, "current": current, "body": body, "frame": None if body else file_url(current),
        "label": lambda p: Path(p).name.removesuffix(".dc.html").removesuffix(".html")})


@router.get("/manage/documents/f/{key}/{rel:path}")
def document_file(key: str, rel: str, db=Depends(get_db)):
    """A page or one of its files, for the sealed frame: only under the folder its key was made for, only for an
    hour, never askdnd's origin (the sandbox), never sent on to anyone (no referrer)."""
    try:
        folder = _signer().loads(key, max_age=KEY_SECONDS)
    except BadSignature:
        return Response("This link has run out. Open the document again from Backstage › Global › Documents.", status_code=403)
    data = read(db, rel) if (folder == "" or rel.startswith(folder + "/")) and not (folder == "" and "/" in rel) else None
    if data is None:
        return Response("Not found", status_code=404)
    headers = {"Content-Security-Policy": SANDBOX, "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
               "Cache-Control": "private, max-age=300"}
    kind = mimetypes.guess_type(Path(rel).name)[0] or "application/octet-stream"
    if kind == "text/html":
        page = data.decode(errors="replace")
        if not page.lstrip()[:15].lower().startswith("<!doctype"):  # (claude.ai pages are written without their skeleton)
            page = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
                    'initial-scale=1"></head><body style="margin:0">' + page + "</body></html>")
        # (every mockup, older ones too, gets the comment layer: pins where Brett clicks, issue 24; it does nothing alone)
        layer = f'<script src="{_static("doc-layer.js")}" defer></script>'
        at = page.lower().rfind("</body>")
        page = page[:at] + layer + page[at:] if at >= 0 else page + layer
        return HTMLResponse(page, headers=headers)
    return Response(data, media_type=kind, headers=headers)
