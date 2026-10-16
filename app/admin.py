"""Admin pages (Brett): import campaign data."""

import json

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

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
def import_form(request: Request):
    user, denied = _guard(request)
    if denied:
        return denied
    return templates.TemplateResponse(request, "admin_import.html", {"user": user})


@router.post("/import")
async def import_upload(request: Request, file: UploadFile = File(...), db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    context = {"user": user, "filename": file.filename}
    if len(raw) > MAX_UPLOAD_BYTES:
        context["error"] = "That file is too large (2 MB max)."
    else:
        try:
            counts = import_bundle(db, json.loads(raw))
            db.commit()
            context["counts"] = dict(counts) or {"nothing new": 0}
        except json.JSONDecodeError as e:
            db.rollback()
            context["error"] = f"That isn't valid JSON (line {e.lineno}): {e.msg}"
        except (BundleError, KeyError, ValueError, TypeError) as e:
            db.rollback()
            context["error"] = f"Nothing was imported. Problem: {e}"
    return templates.TemplateResponse(request, "admin_import.html", context)
