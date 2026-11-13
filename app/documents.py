"""Manage › askdnd › Documents (Brett, Nov 6): every page made for askdnd (guides, plans, designs, earlier ones) in one
place, for admins, read from the repo's own copies, so nothing depends on claude.ai to be found or kept.

The list is docs/library.json, the one source: the roadmap's table of documents is written from it too
(scripts/library.py). A plan (Markdown) is shown in the page; an HTML page or a design's boards open in a sealed
frame: served with a Content-Security-Policy sandbox, so their scripts run without askdnd's origin (no sign-in, no
storage, no requests as you), from an address that carries a signed key good for an hour (the frame's own requests
for a page's pictures and styles can't carry the sign-in), and with no referrer, so the key never leaves askdnd.
"""

import json
import mimetypes
import re
from functools import cache
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from markupsafe import Markup

from app import config, web
from app.auth import is_admin
from app.render import markdown_to_html
from app.templating import templates

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
SANDBOX = ("sandbox allow-scripts allow-popups allow-popups-to-escape-sandbox; default-src 'self' 'unsafe-inline' data: blob:; "
           "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' data: https://fonts.gstatic.com; "
           "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://cdn.jsdelivr.net https://unpkg.com; "
           "img-src 'self' data: blob: https:")


def doc_id(source: str) -> str:
    """A document's address in askdnd: its repo path, as a word (docs/artifacts/recording-to-recap.html → artifacts-recording-to-recap)."""
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"\.(html|md)$", "", source.removeprefix("docs/")).lower()).strip("-")


@cache
def _library(mtime: float) -> tuple[dict, ...]:
    return tuple({**e, "id": doc_id(e["source"])} for e in json.loads(LIBRARY.read_text()))


def library() -> tuple[dict, ...]:
    """docs/library.json, read again when it changes."""
    return _library(LIBRARY.stat().st_mtime)


def find(did: str) -> dict | None:
    return next((e for e in library() if e["id"] == did), None)


def inside_docs(rel: str) -> Path | None:
    """A path under docs/, never outside it and never a hidden file; None otherwise."""
    if not rel or "\\" in rel or any(part.startswith(".") for part in Path(rel).parts):
        return None
    path = (DOCS / rel).resolve()
    return path if path.is_relative_to(DOCS) and path.exists() else None


def pages_of(entry: dict) -> list[str]:
    """What a document opens to: one file, or a design's boards (its HTML files, the main one first)."""
    path = inside_docs(entry["source"].removeprefix("docs/"))
    if path is None:
        return []
    if path.is_file():
        return [path.relative_to(DOCS).as_posix()]
    boards = sorted((p for p in path.rglob("*.html") if not any(x.startswith(".") for x in p.relative_to(DOCS).parts)),
                    key=lambda p: (p.stem.lower() not in ("main", "index"), p.relative_to(path).as_posix().lower()))
    return [p.relative_to(DOCS).as_posix() for p in boards]


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.SESSION_SECRET or "local", salt="documents")


def file_url(page: str) -> str:
    """The sealed frame's address for one page: a key for the page's own folder (so its pictures and styles load),
    then the page's path."""
    folder, name = page.rsplit("/", 1) if "/" in page else ("", page)
    return f"/manage/documents/f/{_signer().dumps(folder)}/{page}"


@router.get("/manage/documents")
def library_page(request: Request, q: str = ""):
    """Every document, in its group, newest first within it; a search over titles and what each is."""
    _, stop = web.require(request, is_admin, "askdnd's documents are for admins.")
    if stop:
        return stop
    words = q.lower().split()
    shown = [e for e in library() if all(w in f"{e['title']} {e['what']} {e['status']}".lower() for w in words)]
    groups = [(key, name, about, [e for e in shown if e["kind"] == key]) for key, name, about in KINDS]
    return templates.TemplateResponse(request, "manage_documents.html", {"groups": groups, "q": q, "count": len(library())})


@router.get("/manage/documents/{did}")
def document_page(request: Request, did: str, page: str = ""):
    """One document: a plan in the page, anything else in the sealed frame, a design's boards as tabs."""
    _, stop = web.require(request, is_admin, "askdnd's documents are for admins.")
    if stop:
        return stop
    entry = find(did)
    pages = pages_of(entry) if entry else []
    if not pages:
        return web.not_found(request, "That document isn't in the library.")
    current = page if page in pages else pages[0]
    body = None
    if current.endswith(".md"):
        body = Markup(markdown_to_html((DOCS / current).read_text(), lambda _name: None))  # noqa: S704
    return templates.TemplateResponse(request, "manage_document.html", {
        "e": entry, "pages": pages, "current": current, "body": body, "frame": None if body else file_url(current),
        "label": lambda p: Path(p).name.removesuffix(".dc.html").removesuffix(".html")})


@router.get("/manage/documents/f/{key}/{rel:path}")
def document_file(key: str, rel: str):
    """A page or one of its files, for the sealed frame: only under the folder its key was made for, only for an
    hour, never askdnd's origin (the sandbox), never sent on to anyone (no referrer)."""
    try:
        folder = _signer().loads(key, max_age=KEY_SECONDS)
    except BadSignature:
        return Response("This link has run out. Open the document again from Manage › askdnd › Documents.", status_code=403)
    path = inside_docs(rel)
    if path is None or not path.is_file() or not (folder == "" or rel.startswith(folder + "/")) or (folder == "" and "/" in rel):
        return Response("Not found", status_code=404)
    headers = {"Content-Security-Policy": SANDBOX, "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff",
               "Cache-Control": "private, max-age=300"}
    kind = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    if kind == "text/html":
        page = path.read_text(errors="replace")
        if not page.lstrip()[:15].lower().startswith("<!doctype"):  # (claude.ai pages are written without their skeleton)
            page = ('<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,'
                    'initial-scale=1"></head><body style="margin:0">' + page + "</body></html>")
        return HTMLResponse(page, headers=headers)
    return FileResponse(path, media_type=kind, headers=headers)
