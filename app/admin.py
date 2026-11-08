"""Manage › Backups and imports (admins): the nightly backups, then importing campaign data, then the private rules
books' entries (a file from scripts/book_load.py --export: beta's database has no public address, so a book reaches it
this way)."""

import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import web
from app import import_preview
from app.auth import is_admin, is_reviewer
from app.db import get_db
from app.importer import BundleError, import_bundle
from app.templating import templates

router = APIRouter(prefix="/manage/backups")  # askdnd-wide

MAX_UPLOAD_BYTES = 2_000_000


def _guard(request: Request, allow=is_admin):
    """(user, None) if allowed, else (None, a redirect or 403 page). Admins by default."""
    return web.require(request, allow)


def _reviewer_guard(request: Request):
    return _guard(request, allow=is_reviewer)


@router.get("")
def import_form(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    from app.history_pages import recent_imports

    from app.manage import backup_status
    from app.models import JobRun

    runs = list(db.scalars(select(JobRun).where(JobRun.name == "backup").order_by(JobRun.id.desc()).limit(10)))
    return templates.TemplateResponse(request, "admin_import.html", {"user": user, "toast": request.session.pop("toast", None),
                                                                     "imports": recent_imports(db), "backups": runs,
                                                                     "backup": backup_status(db), "books": _books(db)})


def _books(db: Session) -> list[dict]:
    from app import books

    have = books.counts(db)
    return [{"title": b.title, "short": b.short, "kinds": have.get(b.key, {})} for b in books.BOOKS]


MAX_BOOK_BYTES = 20_000_000  # (the whole Monster Manual is about 130 KB packed, 1.5 MB unpacked)


@router.post("/books")
def book_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """A book's entries, from scripts/book_load.py --export: written as the loader writes them (books.replace), each
    checked against askdnd's shapes first; nothing is written if any doesn't fit."""
    import gzip

    from app import books

    user, denied = _guard(request)
    if denied:
        return denied
    raw = file.file.read(MAX_BOOK_BYTES + 1)
    try:
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        if len(raw) > MAX_BOOK_BYTES:
            raise ValueError("that file is too large")
        data = json.loads(raw)
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list) or not data["rows"]:
            raise ValueError("it isn't a book file from scripts/book_load.py --export")
        rows = [(r[0], r[1], r[2]) for r in data["rows"]]
        written, gone = books.replace(db, str(data.get("book")), str(data.get("kind")), rows)
        db.commit()
        b = books.book(str(data.get("book")))
        request.session["toast"] = web.notice(f"{b.title}: {written} entries written" + (f", {gone} no longer in the file removed" if gone else "") + ".")
    except (OSError, ValueError, TypeError, KeyError, IndexError) as e:
        db.rollback()
        request.session["toast"] = web.notice(f"Nothing was written: {e}", "error")
    return RedirectResponse("/manage/backups#books", status_code=303)


@router.post("/import")
def import_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Step 1: read the file and show what it would change. Nothing is written yet."""
    user, denied = _guard(request)
    if denied:
        return denied
    raw = file.file.read(MAX_UPLOAD_BYTES + 1)
    context = {"user": user, "filename": file.filename}
    if len(raw) > MAX_UPLOAD_BYTES:
        context["error"] = "That file is too large (2 MB max)."
    else:
        try:
            bundle = json.loads(raw)
            context["preview"] = import_preview.preview(db, bundle)
            context["token"] = import_preview.hold(bundle, file.filename or "bundle.json", user["email"])
        except json.JSONDecodeError as e:
            context["error"] = f"That isn't valid JSON (line {e.lineno}): {e.msg}"
        except (BundleError, KeyError, ValueError, TypeError, AttributeError) as e:
            db.rollback()
            context["error"] = f"Nothing was imported. Problem: {e}"
    return templates.TemplateResponse(request, "admin_import.html", context)


@router.post("/import/apply")
def import_apply(request: Request, token: str = Form(""), keep_text: str = Form(""), db: Session = Depends(get_db)):
    """Step 2: the admin looked at the preview and pressed Import."""
    user, denied = _guard(request)
    if denied:
        return denied
    pending = import_preview.take(token, user["email"])
    if pending is None:
        return templates.TemplateResponse(request, "admin_import.html", {
            "user": user, "error": "That upload expired or was already imported. Choose the file again."})
    context = {"user": user, "filename": pending["filename"]}
    try:
        counts = import_bundle(db, pending["bundle"], keep_text=keep_text == "1")
        db.commit()
        context["counts"] = dict(counts) or {"nothing new": 0}
        context["kept"] = keep_text == "1"
    except (BundleError, KeyError, ValueError, TypeError, AttributeError) as e:
        db.rollback()
        context["error"] = f"Nothing was imported. Problem: {e}"
    return templates.TemplateResponse(request, "admin_import.html", context)


@router.post("/import/cancel")
def import_cancel(request: Request, token: str = Form("")):
    user, denied = _guard(request)
    if denied:
        return denied
    import_preview.take(token, user["email"])
    request.session["toast"] = "Import cancelled. Nothing changed."
    return RedirectResponse("/manage/backups", status_code=303)
