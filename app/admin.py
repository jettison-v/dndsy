"""Admin pages (Brett): import campaign data."""

import json

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import import_preview
from app.auth import current_user, is_admin, is_reviewer
from app.db import get_db
from app.importer import BundleError, import_bundle
from app.templating import templates

router = APIRouter(prefix="/admin")

MAX_UPLOAD_BYTES = 2_000_000


def _guard(request: Request, allow=is_admin):
    """(user, None) if allowed, else (None, a redirect or 403 page)."""
    user = current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=303)
    if not allow(user):
        return None, templates.TemplateResponse(
            request, "message.html", {"title": "Not available", "message": "This page is for the campaign admin."}, status_code=403
        )
    return user, None


def _reviewer_guard(request: Request):
    return _guard(request, allow=is_reviewer)


@router.get("/import")
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
                                                                     "backup": backup_status(db)})


@router.post("/import")
async def import_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Step 1: read the file and show what it would change. Nothing is written yet."""
    user, denied = _guard(request)
    if denied:
        return denied
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
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
    return RedirectResponse("/admin/import", status_code=303)
