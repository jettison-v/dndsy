"""Manage › Tool corrections (admins, /manage/tool-corrections): corrections to how askdnd reads D&D Beyond, made
from character side panels (tool_corrections). They apply to every character in every campaign, so they belong to
askdnd as a whole. A DM's rulings for one table are House rules instead."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import character_views as views
from app.admin import _guard
from app.db import get_db
from app.models import ToolCorrection
from app.templating import templates

router = APIRouter(prefix="/manage/tool-corrections")


@router.get("")
def page(request: Request, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    overrides = list(db.scalars(select(ToolCorrection).order_by(ToolCorrection.updated_at.desc())))
    labels = {f: dict(c) for f, c in {**views.OVERRIDE_CHOICES, **views.TERM_CHOICES}.items()}
    return templates.TemplateResponse(request, "tool_corrections.html", {
        "overrides": overrides, "labels": labels, "field_labels": views.FIELD_LABELS,
        "toast": request.session.pop("toast", None),
    })


@router.post("/overrides/{override_id:int}/delete")
def undo_override(request: Request, override_id: int, db: Session = Depends(get_db)):
    user, denied = _guard(request)
    if denied:
        return denied
    row = db.get(ToolCorrection, override_id)
    if row:
        db.delete(row)
        db.commit()
        request.session["toast"] = "Back to automatic"
    return RedirectResponse("/manage/tool-corrections", status_code=303)


@router.post("/overrides/{override_id:int}/reason")
def override_reason(request: Request, override_id: int, reason: str = Form(""), db: Session = Depends(get_db)):
    """Why a tool correction was needed (feedback for fixing the parser)."""
    user, denied = _guard(request)
    if denied:
        return denied
    row = db.get(ToolCorrection, override_id)
    if row:
        row.reason = " ".join(reason.split())[:300]
        db.commit()
        request.session["toast"] = "Saved"
    return RedirectResponse("/manage/tool-corrections", status_code=303)
